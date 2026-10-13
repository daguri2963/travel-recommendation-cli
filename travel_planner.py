"""OpenAI 호환 채팅 API와 Kakao Local을 연결하는 국내 여행 추천 CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from datetime import date
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


BASE_DIR = Path(__file__).resolve().parent
KAKAO_URL = "https://dapi.kakao.com/v2/local/search/keyword.json"
DEFAULT_MODEL = "gpt-4o-mini"
DEFAULT_LLM_BASE_URL = "https://api.openai.com/v1"
REQUIRED_HEADINGS = (
    "## 추천 지역",
    "## 추천 이유",
    "## 날씨 요약",
    "## 행사/축제",
    "## 맛집 추천",
    "## 1일 일정",
)


class PlannerError(Exception):
    """사용자에게 출력 가능한, 비밀 정보가 없는 오류."""

    def __init__(self, message: str, kind: str = "API_ERROR") -> None:
        super().__init__(message)
        self.kind = kind


def load_dotenv(path: Path) -> None:
    """프로젝트의 간단한 KEY=VALUE 형식 .env를 읽는다. 기존 환경변수 우선."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", key):
            if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                value = value[1:-1]
            os.environ.setdefault(key, value)


def parse_date(value: str) -> str:
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", value):
        raise argparse.ArgumentTypeError("날짜는 YYYY-MM-DD 형식이어야 합니다.")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("존재하지 않는 날짜입니다.") from exc
    return value


def request_json(url: str, headers: dict[str, str], payload: dict | None = None) -> dict:
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = Request(url, data=body, headers=headers, method="POST" if body is not None else "GET")
    try:
        with urlopen(request, timeout=25) as response:
            result = json.load(response)
    except HTTPError as exc:
        status = exc.code
        if url.startswith(KAKAO_URL) and status == 403:
            try:
                error = json.load(exc)
            except (ValueError, UnicodeError):
                error = {}
            if isinstance(error, dict) and "disabled OPEN_MAP_AND_LOCAL" in str(error.get("message", "")):
                raise PlannerError(
                    "카카오맵 API가 비활성화되어 있습니다. 앱의 카카오맵 > 사용 설정에서 켜세요.",
                    "SERVICE_DISABLED",
                ) from None
        kind = "AUTH_ERROR" if status in (401, 403) else "QUOTA_ERROR" if status == 429 else "HTTP_ERROR"
        raise PlannerError(f"HTTP {status}", kind) from None
    except (URLError, TimeoutError) as exc:
        raise PlannerError("네트워크 연결 또는 시간 초과 오류", "NETWORK_ERROR") from exc
    except (ValueError, UnicodeError) as exc:
        raise PlannerError("API 응답 JSON을 읽을 수 없습니다.", "RESPONSE_PARSE_ERROR") from exc
    if not isinstance(result, dict):
        raise PlannerError("API 응답 형식이 올바르지 않습니다.", "RESPONSE_PARSE_ERROR")
    return result


def response_text(response: dict) -> str:
    choices = response.get("choices")
    if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
        raise PlannerError("LLM 응답에 choices가 없습니다.", "LLM_RESPONSE_ERROR")
    message = choices[0].get("message")
    content = message.get("content") if isinstance(message, dict) else None
    if not isinstance(content, str) or not content.strip():
        raise PlannerError("LLM 텍스트 응답이 비어 있습니다.", "LLM_RESPONSE_ERROR")
    return content.strip()


def llm_response(api_key: str, model: str, base_url: str, prompt: str) -> str:
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
    }
    result = request_json(
        base_url.rstrip("/") + "/chat/completions",
        {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        payload,
    )
    return response_text(result)


def validate_recommendation(raw: str) -> dict:
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise PlannerError("추천 결과가 JSON이 아닙니다.", "LLM_PARSE_ERROR") from exc
    if not isinstance(data, dict):
        raise PlannerError("추천 결과가 JSON 객체가 아닙니다.", "LLM_PARSE_ERROR")
    for field in ("recommended_city", "weather", "reason"):
        if not isinstance(data.get(field), str) or not data[field].strip():
            raise PlannerError(f"추천 결과의 {field} 값이 올바르지 않습니다.", "LLM_PARSE_ERROR")
    if not isinstance(data.get("events"), list) or not all(isinstance(x, str) for x in data["events"]):
        raise PlannerError("추천 결과의 events 값이 올바르지 않습니다.", "LLM_PARSE_ERROR")
    return data


def recommend(travel_date: str, api_key: str, model: str, base_url: str) -> dict:
    prompt = (
        f"여행 날짜: {travel_date}. 이 시기에 국내 여행하기 좋은 도시 1곳을 추천하세요. "
        "반드시 지정된 JSON 스키마로만 답하세요. recommended_city는 검색 가능한 국내 지역명, "
        "weather는 그 시기의 일반적인 날씨 경향, events는 확인 전인 행사/축제 후보 1~3개, "
        "reason은 추천 근거 2~4문장으로 작성하세요. 실제 예보나 확정 행사처럼 단정하지 마세요."
    )
    for attempt in range(2):
        raw = llm_response(api_key, model, base_url, prompt)
        try:
            return validate_recommendation(raw)
        except PlannerError:
            if attempt:
                raise
            prompt += " 이전 응답을 파싱할 수 없었습니다. 필수 키와 타입을 지킨 JSON 객체만 다시 출력하세요."
    raise AssertionError("unreachable")


def search_restaurants(city: str, api_key: str) -> list[dict]:
    query = urlencode({"query": f"{city} 맛집", "size": 5})
    result = request_json(KAKAO_URL + "?" + query, {"Authorization": f"KakaoAK {api_key}"})
    documents = result.get("documents")
    if not isinstance(documents, list):
        raise PlannerError("장소 검색 응답 형식이 올바르지 않습니다.", "RESPONSE_PARSE_ERROR")
    restaurants = []
    for item in documents[:5]:
        if not isinstance(item, dict):
            continue
        name = item.get("place_name")
        address = item.get("road_address_name") or item.get("address_name")
        if not isinstance(name, str) or not isinstance(address, str):
            continue
        place = {"name": name, "address": address}
        if isinstance(item.get("category_name"), str) and item["category_name"]:
            place["category"] = item["category_name"]
        if isinstance(item.get("place_url"), str) and item["place_url"]:
            place["url"] = item["place_url"]
        for coordinate in ("x", "y"):
            try:
                place[coordinate] = float(item[coordinate])
            except (KeyError, TypeError, ValueError):
                pass
        restaurants.append(place)
    return restaurants


def make_report(travel_date: str, recommendation: dict, restaurants: list[dict], errors: list[dict], api_key: str, model: str, base_url: str) -> str:
    source = json.dumps({"date": travel_date, "recommendation": recommendation, "restaurants": restaurants, "errors": errors}, ensure_ascii=False)
    prompt = (
        "아래 JSON 데이터만 근거로 한국어 Markdown 여행 리포트를 작성하세요. "
        f"제목은 '# {travel_date} 국내 여행 추천 리포트'로 하세요. "
        "다음 2단계 제목을 정확히 포함하세요: 추천 지역, 추천 이유, 날씨 요약, 행사/축제, 맛집 추천, 1일 일정. "
        "일정은 오전·오후·저녁으로 나누세요. 맛집이 0건이면 '데이터 없음'이라고 쓰세요. "
        "날씨와 행사는 일반적 경향과 후보이며 방문 전 확인이 필요하다고 적으세요. "
        "오류가 있으면 '## 오류 요약' 섹션에 간단히 적으세요. JSON에 없는 특정 업체나 확정 행사를 만들지 마세요.\n\n"
        + source
    )
    report = llm_response(api_key, model, base_url, prompt)
    if any(heading not in report for heading in REQUIRED_HEADINGS):
        raise PlannerError("리포트에 필수 섹션이 빠졌습니다.", "REPORT_FORMAT_ERROR")
    if not restaurants and "데이터 없음" not in report:
        raise PlannerError("리포트에 맛집 데이터 없음 표시가 빠졌습니다.", "REPORT_FORMAT_ERROR")
    return report.rstrip() + "\n"


def save_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def run(travel_date: str, output_dir: Path = BASE_DIR / "results") -> int:
    load_dotenv(BASE_DIR / ".env")
    llm_key = (os.environ.get("LLM_API_KEY") or os.environ.get("OPENAI_API_KEY", "")).strip()
    kakao_key = os.environ.get("KAKAO_REST_API_KEY", "").strip()
    missing = [name for name, value in (("LLM_API_KEY (또는 OPENAI_API_KEY)", llm_key), ("KAKAO_REST_API_KEY", kakao_key)) if not value]
    if missing:
        print("오류: 필수 환경변수가 없습니다: " + ", ".join(missing), file=sys.stderr)
        print("README.md의 API 키 설정 방법을 확인하세요.", file=sys.stderr)
        return 2

    model = (os.environ.get("LLM_MODEL") or os.environ.get("OPENAI_MODEL") or DEFAULT_MODEL).strip()
    base_url = (os.environ.get("LLM_API_BASE_URL") or DEFAULT_LLM_BASE_URL).strip()
    if not base_url.startswith("https://"):
        print("오류: LLM_API_BASE_URL은 https:// 주소여야 합니다.", file=sys.stderr)
        return 2
    raw_path = output_dir / f"{travel_date}_raw.json"
    report_path = output_dir / f"{travel_date}_travel_plan.md"
    errors: list[dict] = []
    data = {"date": travel_date, "recommendation": None, "restaurants": [], "errors": errors}

    print("[1/3] 1차 추천 생성 중(LLM)...")
    try:
        data["recommendation"] = recommend(travel_date, llm_key, model, base_url)
    except PlannerError as exc:
        errors.append({"step": "recommendation", "type": exc.kind, "message": str(exc)})
        save_json(raw_path, data)
        print(f"오류: 추천을 생성하지 못했습니다. {exc} 원본: {raw_path}", file=sys.stderr)
        return 1
    print(f"  - 추천 지역: {data['recommendation']['recommended_city']}")

    print("[2/3] 맛집 검색 중(Kakao Local)...")
    try:
        data["restaurants"] = search_restaurants(data["recommendation"]["recommended_city"], kakao_key)
        if not data["restaurants"]:
            errors.append({"step": "place_search", "type": "EMPTY_RESULT", "message": "검색 결과 0건"})
            print("  - 검색 결과 0건. 데이터 없음으로 계속 진행합니다.")
        else:
            print(f"  - 맛집 {len(data['restaurants'])}곳 검색 완료")
    except PlannerError as exc:
        errors.append({"step": "place_search", "type": exc.kind, "message": str(exc)})
        print(f"  - 장소 검색 오류({exc}). 데이터 없음으로 계속 진행합니다.")

    save_json(raw_path, data)
    print("[3/3] 최종 리포트 생성 중(LLM)...")
    try:
        report = make_report(travel_date, data["recommendation"], data["restaurants"], errors, llm_key, model, base_url)
    except PlannerError as exc:
        errors.append({"step": "report", "type": exc.kind, "message": str(exc)})
        save_json(raw_path, data)
        print(f"오류: 리포트를 생성하지 못했습니다. {exc} 원본: {raw_path}", file=sys.stderr)
        return 1
    report_path.write_text(report, encoding="utf-8")
    print(f"완료! 원본: {raw_path}")
    print(f"       리포트: {report_path}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="국내 여행 추천 리포트 생성")
    parser.add_argument("--date", "-date", required=True, type=parse_date, help="여행 날짜 (YYYY-MM-DD)")
    args = parser.parse_args()
    return run(args.date)


if __name__ == "__main__":
    sys.exit(main())
