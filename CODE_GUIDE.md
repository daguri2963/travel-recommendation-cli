# 코드 해설: `travel_planner.py`

처음 읽을 때는 `main()` → `run()` → 각 API 함수 순서로 따라가면 된다. 이 프로그램의 흐름은 **날짜 입력 → LLM 추천 JSON → 추천 도시로 카카오 맛집 검색 → LLM Markdown 리포트 → 파일 저장**이다.

## 파일별 역할

| 파일 | 의미 |
| --- | --- |
| `travel_planner.py` | CLI 입력, API 요청, 응답 처리, 파일 저장을 담당하는 실행 코드 |
| `.env.example` | 필요한 설정 변수의 이름과 예시 값. 실제 키를 넣어 커밋하면 안 됨 |
| `.gitignore` | `.env`, Python 캐시 등을 Git 추적에서 제외 |
| `tests/test_travel_planner.py` | 실제 API를 호출하지 않고 주요 동작을 확인하는 자동 테스트 |
| `results/*_raw.json` | 1차 추천, 맛집 목록, 오류 목록을 구조화해 보관 |
| `results/*_travel_plan.md` | 사람이 읽는 최종 여행 리포트 |

## 1. 시작 부분: 가져오기와 상수

- `argparse`: 터미널에서 `--date` 또는 `-date` 옵션을 받는다.
- `json`: Python 딕셔너리·리스트와 JSON 텍스트를 서로 변환한다.
- `os`: 환경변수에서 키와 설정을 읽는다.
- `re`: 날짜 형식과 `.env` 변수 이름의 패턴을 확인한다.
- `sys`: 오류 메시지를 표준 오류로 보내고 종료 코드를 반환한다.
- `datetime.date`: 실제 존재하는 날짜인지 검사한다.
- `pathlib.Path`: 파일·폴더 경로를 다룬다.
- `urllib`: URL 쿼리를 만들고 HTTP 요청·응답 및 오류를 처리한다. 외부 Python 패키지가 필요 없다.
- `BASE_DIR`: 실행 파일이 있는 프로젝트 폴더다. 현재 터미널 위치와 무관하게 `.env`와 `results/`를 찾는 기준이 된다.
- `KAKAO_URL`: 카카오 키워드 장소 검색 API 주소다.
- `DEFAULT_MODEL`, `DEFAULT_LLM_BASE_URL`: 환경변수로 따로 설정하지 않았을 때의 기본값이다. 학습용 키를 쓸 때는 `.env`에서 Codyssey 주소와 모델로 바꾼다.
- `REQUIRED_HEADINGS`: 리포트에 반드시 있어야 하는 Markdown 제목 목록이다.

## 2. 입력과 설정

### `main()`과 `parse_date()`

`main()`은 `argparse.ArgumentParser`로 필수 날짜 옵션을 만든다. `parser.add_argument("--date", "-date", required=True, type=parse_date)`의 의미는 날짜 옵션이 없으면 실행을 거부하고, 값이 있으면 `parse_date()`로 검사한다는 것이다.

`parse_date()`는 먼저 정규식으로 `YYYY-MM-DD` 모양을 확인하고, `date.fromisoformat()`으로 2월 30일처럼 존재하지 않는 날짜도 거른다. 잘못된 입력은 `ArgumentTypeError`를 발생시키므로 `argparse`가 사용법과 오류를 출력한다.

### `load_dotenv()`와 `run()`의 키 확인

`load_dotenv()`는 `.env`의 각 줄을 `이름=값`으로 나눠 `os.environ`에 넣는다. `os.environ.setdefault()`를 사용하므로 이미 터미널에 설정된 환경변수 값이 우선한다.

`run()`은 `LLM_API_KEY`(또는 호환용 `OPENAI_API_KEY`)와 `KAKAO_REST_API_KEY`를 확인한다. 하나라도 비어 있으면 API 요청 전에 설정 안내를 출력하고 종료 코드 `2`를 반환한다. 키는 요청 헤더에만 사용하며 결과 파일에 저장하지 않는다.

## 3. HTTP 요청과 응답

### `request_json(url, headers, payload=None)`

두 API가 공통으로 쓰는 HTTP 함수다. `payload`가 있으면 JSON으로 직렬화해 **POST** 요청을 보내고, 없으면 **GET** 요청을 보낸다. `urlopen(..., timeout=25)`는 응답을 최대 25초 기다리며, `json.load(response)`는 응답 본문을 Python 딕셔너리로 읽는다.

| 상황 | 프로그램의 처리 |
| --- | --- |
| HTTP 401/403 | 인증 또는 권한 문제로 `AUTH_ERROR` 반환 |
| HTTP 429 | 사용량 제한으로 `QUOTA_ERROR` 반환 |
| 카카오맵 비활성화 403 | 설정 안내가 있는 `SERVICE_DISABLED` 반환 |
| 네트워크·시간 초과 | `NETWORK_ERROR` 반환 |
| 응답 JSON 오류 | `RESPONSE_PARSE_ERROR` 반환 |

`PlannerError`는 사용자가 이해할 수 있는 메시지와 오류 종류(`kind`)를 묶은 예외다. 원본 요청 헤더나 실제 키가 오류 메시지에 섞이지 않도록 한다.

### `llm_response()`와 `response_text()`

`llm_response()`는 모델 이름, 사용자 프롬프트를 `messages` 배열에 넣고 LLM의 `/chat/completions`로 POST한다. `Authorization: Bearer ...` 헤더로 학습용 LLM 키를 보낸다. `response_text()`는 응답의 `choices[0].message.content`에서 생성된 문자열을 꺼내고, 없거나 비어 있으면 오류로 처리한다.

## 4. 첫 번째 LLM 호출: 추천 JSON

`recommend()`는 입력 날짜를 포함해 국내 도시 1곳, 일반적인 날씨, 행사 후보 1~3개, 추천 이유를 **JSON 객체로만** 답하라고 요청한다.

`validate_recommendation()`은 응답을 `json.loads()`로 파싱하고 아래 구조를 확인한다.

```json
{
  "recommended_city": "정읍",
  "weather": "일반적인 날씨 요약",
  "events": ["행사 후보"],
  "reason": "추천 이유"
}
```

도시·날씨·이유는 비어 있지 않은 문자열, 행사는 문자열 리스트여야 한다. 파싱 또는 필수 필드 검사에 실패하면 `recommend()`가 프롬프트를 보강해 **한 번만 재요청**한다. 재요청까지 실패하면 더 진행하지 않는다.

## 5. 카카오 호출: 맛집 검색

`search_restaurants(city, api_key)`는 첫 번째 LLM 결과의 `recommended_city`에 `맛집`을 붙여 검색어를 만든다. `urlencode()`가 한글과 공백을 URL에서 안전하게 쓸 수 있게 변환한다. 카카오 API는 **GET**이고 인증 헤더 형식은 `KakaoAK ...`이다.

응답의 `documents`에서 최대 5건을 읽고, 카카오의 `place_name`·`road_address_name`·`category_name`·`place_url`을 프로그램의 `name`·`address`·`category`·`url`로 바꾼다. `x`, `y`는 문자열로 올 수 있으므로 `float()`로 숫자로 변환한다. 일부 선택 필드가 없으면 해당 필드만 생략한다.

검색 결과가 0건이거나 카카오 API에 문제가 있어도 `run()`은 빈 맛집 목록과 오류를 기록하고 리포트 단계로 넘어간다.

## 6. 두 번째 LLM 호출: Markdown 리포트

`make_report()`는 날짜, 추천 JSON, 맛집 목록, 오류 목록을 하나의 JSON 텍스트로 묶어 LLM에 전달한다. 제목과 필수 섹션, 오전·오후·저녁 일정, 0건일 때 `데이터 없음` 표시를 요청한다.

응답을 받은 뒤 `REQUIRED_HEADINGS`의 제목이 모두 있는지 확인한다. 맛집이 비었는데 `데이터 없음`이 없으면 오류로 처리한다. 리포트 생성 실패 시 원본 JSON과 오류 정보는 남기지만 성공한 리포트 파일은 만들지 않는다.

## 7. 실행 흐름과 저장

`run()`은 세 단계를 순서대로 실행하고 `[1/3]`, `[2/3]`, `[3/3]` 진행 로그를 출력한다. `errors` 리스트는 각 단계에서 생긴 오류를 `step`·`type`·`message` 형태로 모은다.

`save_json()`은 `results/` 폴더를 만들고 추천·맛집·오류를 `YYYY-MM-DD_raw.json`에 저장한다. 성공한 Markdown은 `YYYY-MM-DD_travel_plan.md`에 저장한다. 파일명에 쓰는 날짜는 실행 시 입력한 여행 날짜다. 정상 완료하면 두 경로를 출력하고 종료 코드 `0`을 반환한다.

## 8. 테스트 코드 읽기

`tests/test_travel_planner.py`의 `unittest.mock.patch`는 실제 API 함수나 네트워크 응답을 가짜로 바꾼다. 이 덕분에 키와 쿼터 없이 날짜 검증, JSON 재요청, 카카오 데이터 변환, 키 누락, 검색 실패 후 리포트 생성, 리포트 실패 시 원본 저장을 확인할 수 있다.

```powershell
python -m unittest discover -s tests -v
```

테스트 통과는 로컬 처리 로직을 확인한다는 뜻이고, 실제 API 연결은 별도 실행 결과로 확인한다.
