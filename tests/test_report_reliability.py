from __future__ import annotations

import json
import os
from datetime import datetime, timedelta
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tools import update_report as report


def lockup(video_id="abc123", *, parts=None, title=None, accessibility=None):
    model = {
        "title": title or {"content": "瑪麗・賽勒斯特號之謎"},
        "metadata": {"contentMetadataViewModel": {"metadataRows": [
            {"metadataParts": [{"text": value if isinstance(value, dict) else {"content": value}} for value in (parts or [])]}
        ]}},
    }
    if accessibility is not None:
        model["accessibility"] = {"accessibilityData": {"label": accessibility}}
    return {
        "contentId": video_id,
        "contentType": "LOCKUP_CONTENT_TYPE_VIDEO",
        "contentImage": {"items": [{"thumbnailBadgeViewModel": {"text": "3:21"}}]},
        "metadata": {"lockupMetadataViewModel": model},
    }


class MetadataReliabilityTests(unittest.TestCase):
    def test_split_count_and_age_parts_keep_semantic_labels(self):
        videos = report.extract_videos({"items": [lockup(parts=["22", "次觀看", "2", "週前"])]}, {})
        self.assertEqual(videos[0]["views"], 22)
        self.assertEqual(videos[0]["published_text"], "2 週前")
        self.assertEqual(videos[0]["age_days"], 14)
        self.assertIsNone(videos[0]["view_delta"])

    def test_text_runs_and_compact_unit_split_across_parts(self):
        videos = report.extract_videos({"items": [lockup(
            title={"runs": [{"text": "一個"}, {"text": "故事"}]},
            parts=[{"runs": [{"text": "2.4"}]}, "K", "views", "7", "days ago"],
        )]}, {"abc123": 2300})
        self.assertEqual(videos[0]["title"], "一個故事")
        self.assertEqual(videos[0]["views"], 2400)
        self.assertEqual(videos[0]["view_delta"], 100)
        self.assertEqual(videos[0]["age_days"], 7)

    def test_accessibility_fallback_preserves_count_and_date(self):
        v = report.extract_videos({"items": [lockup(parts=[], accessibility="A story, 1,234 views, 3 weeks ago")]}, {})[0]
        self.assertEqual(v["views"], 1234)
        self.assertEqual(v["age_days"], 21)

    def test_outer_renderer_accessibility_label_is_supported(self):
        node = lockup(parts=[])
        node["rendererContext"] = {"accessibilityData": {"label": "A story 31 views 2 months ago"}}
        v = report.extract_videos({"items": [node]}, {})[0]
        self.assertEqual((v["views"], v["age_days"]), (31, 60))

    def test_legacy_video_renderer_is_supported(self):
        v = report.extract_videos({"items": [{"videoRenderer": {
            "videoId": "legacy", "title": {"runs": [{"text": "貝爾女巫事件"}]},
            "viewCountText": {"simpleText": "1,237 views"},
            "publishedTimeText": {"simpleText": "2 weeks ago"},
            "lengthText": {"simpleText": "2:45"},
        }}]}, {})[0]
        self.assertEqual((v["views"], v["age_days"], v["duration"]), (1237, 14, "2:45"))

    def test_selected_uploads_tab_excludes_other_page_nodes(self):
        data = {"items": [lockup("recommended", parts=["999 views", "7 days ago"])],
                "contents": {"twoColumnBrowseResultsRenderer": {"tabs": [{"tabRenderer": {
                    "selected": True, "content": {"items": [lockup("upload", parts=["12 views", "8 days ago"])]}
                }}]}}}
        self.assertEqual([v["video_id"] for v in report.extract_videos(data, {})], ["upload"])

    def test_unknown_count_and_bare_numeric_date_are_not_zero_or_young(self):
        v = report.extract_videos({"items": [lockup(parts=["22", "unknown field"])]}, {})[0]
        self.assertIsNone(v["views"])
        self.assertIsNone(v["age_days"])
        self.assertIsNone(v["goal_gap"])
        self.assertEqual(v["performance_status"], "data_unavailable")
        self.assertIsNone(report.parse_compact_count("views"))
        self.assertIsNone(report.parse_age_days("22"))
        self.assertIsNone(report.parse_age_days("3 minutes"))

    def test_genuine_zero_is_known_and_can_be_evaluated(self):
        for label in ["0 views", "No views", "觀看次數：0次", "尚無觀看次數"]:
            with self.subTest(label=label):
                v = report.extract_videos({"items": [lockup(parts=[label, "8 days ago"])]}, {})[0]
                self.assertEqual(v["views"], 0)
                self.assertEqual(v["performance_status"], "under_target")
                self.assertEqual(report.quality([v], "2026-10-20T10:00:00+08:00")["status"], "valid")

    def test_new_count_can_decrease_without_false_positive_growth(self):
        v = report.extract_videos({"items": [lockup(parts=["9 views", "8 days ago"])]}, {"abc123": 10})[0]
        self.assertEqual(v["view_delta"], -1)

    def test_unknown_metadata_suspends_review_and_directives(self):
        v = report.extract_videos({"items": [lockup(parts=["22"])]}, {})[0]
        review = report.build_weekly_review([v], "2026-10-20")
        self.assertEqual(review["status"], "data_unavailable")
        self.assertEqual(review["underperformers"], [])
        self.assertEqual(review["next_video_strategy"]["script_directives"], [])
        self.assertNotIn("尚無發布滿 7 天", review["summary"])

    def test_broken_deployed_legacy_snapshot_is_not_comparison_baseline(self):
        self.assertEqual(report.views_from_report({"videos": [{"video_id": "x", "views": 0, "published_text": "22"}]}), {})

    def test_partial_sample_does_not_claim_full_total(self):
        data = {"items": [lockup("known", parts=["12 views", "7 days ago"]), lockup("unknown", parts=["8 days ago"])]}
        snapshot = report.build_report(data, {})
        self.assertEqual(snapshot["data_quality"]["status"], "partial")
        self.assertIsNone(snapshot["public_view_total"])
        self.assertEqual(snapshot["scope"], "latest_public_sample")
        self.assertEqual(snapshot["sample_video_count"], 2)


class OfficialSnapshotAndFailureTests(unittest.TestCase):
    def snapshot(self):
        now = datetime.now(report.TAIPEI).replace(microsecond=0)
        return {"generated_at": now.isoformat(), "source": "YouTube Data API v3",
            "public_video_count": 99, "public_subscriber_count": 2,
            "videos": [{"video_id": "one", "title": "歷史謎案", "views": 0,
                         "published_at": (now-timedelta(days=8)).astimezone(report.ZoneInfo("UTC")).isoformat().replace("+00:00", "Z"), "duration": "3:05"}],
            "owner_analytics": {"status": "reauthorization_required", "message": "需要Analytics唯讀授權", "impressions": 9999}}

    def test_official_api_dates_count_zero_and_private_data_separation(self):
        result = report.build_report_from_snapshot(self.snapshot(), {})
        self.assertEqual(result["videos"][0]["views"], 0)
        self.assertEqual(result["videos"][0]["age_days"], 8)
        self.assertEqual(result["sample_video_count"], 1)
        self.assertEqual(result["public_video_count"], 1)  # 99 is channel count, not this sample.
        self.assertEqual(result["owner_analytics"]["status"], "reauthorization_required")
        self.assertNotIn("impressions", result["owner_analytics"])

    def test_review_age_is_anchored_to_official_snapshot_not_wall_clock(self):
        snapshot = self.snapshot()
        now = datetime.now(report.TAIPEI).replace(microsecond=0)
        captured = now-timedelta(days=3)
        snapshot["generated_at"] = captured.isoformat()
        # It is eight days old now, but the available count was captured at day
        # five. The day-five count cannot be judged against a seven-day goal.
        snapshot["videos"][0]["published_at"] = (captured-timedelta(days=5)).isoformat()
        snapshot["videos"][0]["views"] = 12
        result = report.build_report_from_snapshot(snapshot, {})
        self.assertEqual(result["videos"][0]["age_days"], 5)
        self.assertEqual(result["weekly_review"]["mature_video_count"], 0)
        self.assertEqual(result["weekly_review"]["early_watch_count"], 1)
        self.assertEqual(result["weekly_review"]["underperformers"], [])
        kept = report.sanitize_previous(result)
        self.assertEqual(kept["videos"][0]["age_days"], 5)
        stale = report.stale_report(result, "RequestException")
        self.assertEqual(stale["videos"][0]["age_days"], 5)
        self.assertEqual(stale["weekly_review"]["mature_video_count"], 0)
        self.assertEqual(stale["weekly_review"]["early_watch_count"], 1)
        self.assertEqual(stale["generated_at"], result["generated_at"])

    def test_official_snapshot_stale_unavailable_or_future_rejected(self):
        for mode in ["old", "future", "unavailable"]:
            snapshot = self.snapshot()
            if mode == "old": snapshot["generated_at"] = (datetime.now(report.TAIPEI)-timedelta(days=6)).isoformat()
            elif mode == "future": snapshot["generated_at"] = (datetime.now(report.TAIPEI)+timedelta(days=6)).isoformat()
            else: snapshot["data_quality"] = {"status": "unavailable"}
            with self.subTest(mode=mode), self.assertRaises(RuntimeError):
                report.build_report_from_snapshot(snapshot, {})

    def test_failed_refresh_keeps_last_valid_metrics_with_original_timestamp(self):
        original = report.build_report_from_snapshot(self.snapshot(), {})
        original["videos"][0]["views"] = 27
        stale = report.stale_report(original, "RequestException")
        self.assertEqual(stale["generated_at"], original["generated_at"])
        self.assertEqual(stale["videos"][0]["views"], 27)
        self.assertEqual(stale["data_quality"]["status"], "stale")
        self.assertEqual(stale["data_quality"]["last_valid_at"], original["generated_at"])
        self.assertEqual(stale["weekly_review"]["status"], "data_unavailable")
        self.assertEqual(stale["weekly_review"]["next_video_strategy"]["script_directives"], [])

    def test_failed_refresh_does_not_republish_private_owner_metrics(self):
        original = report.build_report_from_snapshot(self.snapshot(), {})
        original["owner_analytics"]["metrics"] = {"impressions": 9999, "revenue": 1234}
        stale = report.stale_report(original, "RequestException")
        self.assertNotIn("metrics", stale["owner_analytics"])
        self.assertEqual(stale["owner_analytics"]["status"], "reauthorization_required")

    def test_failed_refresh_sanitizes_broken_legacy_zero_snapshot(self):
        old = {"generated_at": "2026-10-19T16:02:08+08:00", "videos": [
            {"video_id": "x", "title": "故事", "url": "https://www.youtube.com/watch?v=x", "views": 0, "published_text": "22"}]}
        invalid = report.stale_report(old, "RuntimeError")
        self.assertEqual(invalid["data_quality"]["status"], "invalid")
        self.assertIsNone(invalid["videos"][0]["views"])
        self.assertIsNone(invalid["public_view_total"])

    def test_auto_saved_official_snapshot_only_used_when_fresh(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory)/"public-channel-snapshot.json"
            snapshot = self.snapshot()
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            self.assertEqual(report.fresh_saved_snapshot(path)["source"], "YouTube Data API v3")
            snapshot["generated_at"] = (datetime.now(report.TAIPEI)-timedelta(days=6)).isoformat()
            path.write_text(json.dumps(snapshot), encoding="utf-8")
            self.assertIsNone(report.fresh_saved_snapshot(path))
            path.write_text("not JSON", encoding="utf-8")
            self.assertIsNone(report.fresh_saved_snapshot(path))

    def test_explicitly_invalid_previous_is_not_promoted_to_valid(self):
        snapshot = report.build_report_from_snapshot(self.snapshot(), {})
        snapshot["data_quality"]["status"] = "invalid"
        self.assertEqual(report.sanitize_previous(snapshot)["data_quality"]["status"], "invalid")
        self.assertEqual(report.views_from_report(snapshot), {})

    def test_failure_deploys_explicit_state_and_exposes_failed_refresh_to_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            out = Path(directory)/"data.json"
            outputs = Path(directory)/"outputs"
            summary = Path(directory)/"summary"
            with patch.object(report, "OUTPUT_PATH", out), patch.object(report, "deployed_report", return_value=None), patch.object(report, "fresh_saved_snapshot", return_value=None), patch.object(report, "fetch_page", side_effect=RuntimeError("format failed")), patch.dict(os.environ, {"REPORT_SNAPSHOT_PATH": "", "GITHUB_OUTPUT": str(outputs), "GITHUB_STEP_SUMMARY": str(summary)}):
                self.assertEqual(report.main(), 0)  # The unhealthy status page can still deploy.
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["data_quality"]["status"], "invalid")
            self.assertIsNone(data["public_view_total"])
            self.assertIn("data_status=invalid", outputs.read_text(encoding="utf-8"))
            self.assertIn("Public report data: invalid", summary.read_text(encoding="utf-8"))

    def test_main_snapshot_path_skips_scrape_and_preserves_only_public_fields(self):
        with tempfile.TemporaryDirectory() as directory:
            snapshot = Path(directory)/"official.json"
            out = Path(directory)/"data.json"
            snapshot.write_text(json.dumps(self.snapshot()), encoding="utf-8")
            with patch.object(report, "OUTPUT_PATH", out), patch.object(report, "deployed_report", return_value=None), patch.object(report, "fetch_page") as scrape, patch.dict(os.environ, {"REPORT_SNAPSHOT_PATH": str(snapshot)}):
                self.assertEqual(report.main(), 0)
            scrape.assert_not_called()
            data = json.loads(out.read_text(encoding="utf-8"))
            self.assertEqual(data["source"], "YouTube Data API v3")
            self.assertNotIn("impressions", data["owner_analytics"])


if __name__ == "__main__":
    unittest.main()
