# 국내 여행 추천 CLI

입력한 날짜에 맞춰 OpenAI 호환 채팅 API로 국내 여행 지역을 추천하고, Kakao Local API로 맛집을 찾은 다음 Markdown 리포트를 만듭니다. 현재 설정은 학습용 Codyssey API(`https://copa.codyssey.kr/v1`)입니다. Python 3.10 이상이 필요하며 외부 Python 패키지는 사용하지 않습니다.

## API 키 준비

학습용 LLM 서비스 키와 Kakao Developers의 **REST API 키**가 각각 필요합니다. 학습용 키는 OpenAI 공식 API 서버에서 인증되지 않으므로 프로그램의 `LLM_API_BASE_URL`도 학습용 서버로 설정해야 합니다. 실제 키는 코드, README, 채팅, 버전 관리에 올리지 마세요. 이미 공개한 키가 있다면 발급처에서 폐기하고 새 키를 발급받으세요.

Kakao 앱에서는 **카카오맵 → 사용 설정 → 상태 ON**으로 카카오맵 API를 활성화해야 장소 검색이 동작합니다. 카카오 공식 문서에 따르면 개발자 계정에서 처음 활성화한 앱에만 무료 쿼터가 제공됩니다. 유료 설정 안내가 나오면 조건을 확인한 뒤 진행하세요.

PowerShell에서는 현재 터미널 세션에 다음과 같이 설정합니다. `YOUR_...`는 각자 발급받은 새 키로 바꿉니다.

```powershell
$env:LLM_API_KEY="YOUR_LEARNING_SERVICE_KEY"
$env:KAKAO_REST_API_KEY="YOUR_KAKAO_REST_API_KEY"
$env:LLM_API_BASE_URL="https://copa.codyssey.kr/v1"
$env:LLM_MODEL="gpt-5-mini"
```

또는 준비된 `.env` 파일에 값을 넣어도 됩니다. `.env`는 `.gitignore`에 포함되어 있습니다. 환경변수 값이 `.env`보다 우선합니다. `.env`는 단순한 `KEY=VALUE` 형식만 지원합니다. 이전 설정의 `OPENAI_API_KEY`도 호환용으로 읽지만, 새 설정에는 `LLM_API_KEY`를 사용하세요.

기본값은 OpenAI 공식 주소와 `gpt-4o-mini`입니다. 이 학습용 키를 사용할 때는 반드시 `.env`의 `LLM_API_BASE_URL=https://copa.codyssey.kr/v1`, `LLM_MODEL=gpt-5-mini`를 유지하세요. 프로그램은 `/chat/completions`로 요청하며 추천 JSON은 프롬프트와 로컬 검증으로 처리합니다. 학습용 서비스의 사용 조건과 요금은 해당 서비스에서 확인하세요.

## 실행

프로젝트 폴더에서 다음 명령을 실행합니다.

```powershell
python travel_planner.py --date "2026-10-20"
```

`-date`도 허용합니다. 날짜는 실제 달력 날짜여야 합니다. 키가 누락되면 API 호출 전에 설정 안내를 출력하고 종료합니다.

Windows에서 `python` 명령이 실행되지 않으면 `python --version`으로 설치 상태를 확인하세요. Python Launcher가 설치되어 있다면 다음처럼 실행할 수 있습니다.

```powershell
py -3 travel_planner.py --date "2026-10-20"
```

`py`도 없으면 Python 3.10 이상을 설치하고 새 터미널에서 다시 실행하세요.

## 결과 확인

성공하면 `results/YYYY-MM-DD_raw.json`과 `results/YYYY-MM-DD_travel_plan.md`가 생성됩니다. 파일명은 입력한 여행 날짜를 사용하며 같은 날짜로 다시 실행하면 덮어씁니다. 원본 JSON에는 추천, 맛집 목록, 오류 목록이 들어갑니다. 장소 검색이 실패하거나 0건이어도 리포트는 만들고 맛집은 `데이터 없음`으로 표시합니다. 추천이나 최종 리포트 호출이 실패하면 원본 JSON에 오류를 기록하고 종료합니다.

날씨는 일반적인 계절 경향, 행사는 후보 정보이므로 출발 전에 실제 예보와 행사 일정을 확인하세요. 맛집 영업 정보도 방문 전에 확인하세요.

## 키 없이 로컬 검증

아래 명령은 실제 API를 호출하지 않고 날짜 입력, 키 누락, 데이터 처리 흐름을 검사합니다.

```powershell
python -m unittest discover -s tests -v
```

실제 API 호출과 결과 파일 생성은 두 키를 준비한 뒤 확인할 수 있습니다.

## 학습 기록

- [개발 중 오류와 애로사항](TROUBLESHOOTING.md)
- [코드 해설](CODE_GUIDE.md)

## 사용한 API 문서

- [OpenAI 호환 Chat Completions 응답 형식](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)
- [Kakao Local 키워드 검색](https://developers.kakao.com/docs/ko/local/dev-guide)
- [카카오맵 API 활성화와 무료 쿼터](https://developers.kakao.com/docs/ko/kakaomap/common)
