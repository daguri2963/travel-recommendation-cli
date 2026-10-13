import json
import io
import os
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError
from unittest.mock import patch

import travel_planner as planner


RECOMMENDATION = {
    "recommended_city": "제주",
    "weather": "가을철 일반적 경향",
    "events": ["지역 행사 후보"],
    "reason": "걷기 좋습니다. 풍경을 볼 수 있습니다.",
}
REPORT = """# 2026-10-20 국내 여행 추천 리포트
## 추천 지역
제주
## 추천 이유
걷기 좋습니다.
## 날씨 요약
가을철 일반적 경향
## 행사/축제
지역 행사 후보
## 맛집 추천
데이터 없음
## 1일 일정
오전 산책, 오후 관광, 저녁 식사
"""


class PlannerTests(unittest.TestCase):
    def test_date_validation(self):
        self.assertEqual(planner.parse_date("2026-10-20"), "2026-10-20")
        for bad in ("2026-2-20", "2026-02-30", "hello"):
            with self.assertRaises(Exception):
                planner.parse_date(bad)

    def test_recommendation_retries_once_after_bad_json(self):
        with patch.object(planner, "llm_response", side_effect=["not json", json.dumps(RECOMMENDATION, ensure_ascii=False)]) as api:
            self.assertEqual(planner.recommend("2026-10-20", "dummy", "gpt-5-mini", "https://example.test/v1"), RECOMMENDATION)
            self.assertEqual(api.call_count, 2)

    def test_compatible_chat_endpoint_shape(self):
        reply = {"choices": [{"message": {"role": "assistant", "content": "hello"}}]}
        with patch.object(planner, "request_json", return_value=reply) as api:
            self.assertEqual(planner.llm_response("dummy", "gpt-5-mini", "https://copa.codyssey.kr/v1", "hi"), "hello")
        self.assertEqual(api.call_args.args[0], "https://copa.codyssey.kr/v1/chat/completions")
        self.assertEqual(api.call_args.args[2], {"model": "gpt-5-mini", "messages": [{"role": "user", "content": "hi"}]})

    def test_kakao_result_is_normalized(self):
        response = {"documents": [{"place_name": "식당", "road_address_name": "제주시 길 1", "category_name": "음식점", "place_url": "https://place.map.kakao.com/1", "x": "126.5", "y": "33.5"}]}
        with patch.object(planner, "request_json", return_value=response) as api:
            places = planner.search_restaurants("제주", "dummy")
        self.assertEqual(places[0]["x"], 126.5)
        self.assertEqual(places[0]["address"], "제주시 길 1")
        self.assertIn("query=%EC%A0%9C%EC%A3%BC+%EB%A7%9B%EC%A7%91", api.call_args.args[0])

    def test_kakao_disabled_service_has_actionable_error(self):
        body = io.BytesIO(json.dumps({"errorType": "NotAuthorizedError", "message": "App disabled OPEN_MAP_AND_LOCAL service."}).encode())
        response = HTTPError(planner.KAKAO_URL, 403, "Forbidden", {}, body)
        with patch.object(planner, "urlopen", side_effect=response):
            with self.assertRaises(planner.PlannerError) as caught:
                planner.search_restaurants("제주", "dummy")
        self.assertEqual(caught.exception.kind, "SERVICE_DISABLED")

    def test_missing_keys_stops_before_api(self):
        with tempfile.TemporaryDirectory(dir=planner.BASE_DIR) as directory:
            with patch.dict(os.environ, {"LLM_API_KEY": "", "OPENAI_API_KEY": "", "KAKAO_REST_API_KEY": ""}):
                with patch.object(planner, "recommend") as api:
                    self.assertEqual(planner.run("2026-10-20", Path(directory)), 2)
                    api.assert_not_called()

    def test_place_error_still_writes_report(self):
        with tempfile.TemporaryDirectory(dir=planner.BASE_DIR) as directory:
            output = Path(directory)
            with patch.dict(os.environ, {"LLM_API_KEY": "dummy", "KAKAO_REST_API_KEY": "dummy"}):
                with patch.object(planner, "recommend", return_value=RECOMMENDATION), patch.object(planner, "search_restaurants", side_effect=planner.PlannerError("HTTP 401", "AUTH_ERROR")), patch.object(planner, "make_report", return_value=REPORT) as report:
                    self.assertEqual(planner.run("2026-10-20", output), 0)
            raw = json.loads((output / "2026-10-20_raw.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["restaurants"], [])
            self.assertEqual(raw["errors"][0]["type"], "AUTH_ERROR")
            self.assertTrue((output / "2026-10-20_travel_plan.md").is_file())
            self.assertEqual(report.call_args.args[2], [])

    def test_report_failure_saves_raw_error(self):
        with tempfile.TemporaryDirectory(dir=planner.BASE_DIR) as directory:
            output = Path(directory)
            with patch.dict(os.environ, {"LLM_API_KEY": "dummy", "KAKAO_REST_API_KEY": "dummy"}):
                with patch.object(planner, "recommend", return_value=RECOMMENDATION), patch.object(planner, "search_restaurants", return_value=[]), patch.object(planner, "make_report", side_effect=planner.PlannerError("HTTP 429", "QUOTA_ERROR")):
                    self.assertEqual(planner.run("2026-10-20", output), 1)
            raw = json.loads((output / "2026-10-20_raw.json").read_text(encoding="utf-8"))
            self.assertEqual(raw["errors"][-1]["step"], "report")
            self.assertFalse((output / "2026-10-20_travel_plan.md").exists())


if __name__ == "__main__":
    unittest.main()
