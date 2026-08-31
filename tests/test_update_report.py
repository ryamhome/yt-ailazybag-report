import json
import tempfile
import unittest
from pathlib import Path

from tools.update_report import (
    INITIAL_DATA_MARKER,
    build_weekly_review,
    classify_series,
    evaluate_video,
    existing_views,
    extract_initial_data,
    extract_videos,
    parse_age_days,
    parse_compact_count,
    short_title,
)


class UpdateReportTests(unittest.TestCase):
    def test_compact_counts(self) -> None:
        self.assertEqual(parse_compact_count("觀看次數：1.2萬次"), 12_000)
        self.assertEqual(parse_compact_count("2.4K views"), 2_400)

    def test_title_helpers(self) -> None:
        self.assertEqual(classify_series("貝爾女巫事件"), "靈異檔案")
        self.assertEqual(classify_series("佐迪亞克殺手"), "真實犯罪")
        self.assertEqual(short_title("[真實犯罪] 比利時孟德里案：未解之謎"), "比利時孟德里案")

    def test_relative_publish_age(self) -> None:
        self.assertEqual(parse_age_days("6 小時前"), 0)
        self.assertEqual(parse_age_days("7 天前"), 7)
        self.assertEqual(parse_age_days("2 weeks ago"), 14)
        self.assertIsNone(parse_age_days("premiered recently"))

    def test_video_is_not_failed_before_seven_days(self) -> None:
        video = evaluate_video({"views": 10, "published_text": "6 天前"})
        self.assertEqual(video["performance_status"], "early_watch")

    def test_video_under_target_after_seven_days(self) -> None:
        video = evaluate_video({"views": 250, "published_text": "7 天前"})
        self.assertEqual(video["performance_status"], "under_target")
        self.assertEqual(video["goal_gap"], 750)

    def test_weekly_review_emits_bounded_improvement_plan(self) -> None:
        review = build_weekly_review(
            [
                {
                    "video_id": "abc",
                    "title": "測試影片",
                    "url": "https://www.youtube.com/watch?v=abc",
                    "views": 100,
                    "published_text": "8 天前",
                }
            ],
            "2026-08-22",
        )
        self.assertEqual(review["under_target_count"], 1)
        self.assertEqual(review["underperformers"][0]["goal_gap"], 900)
        self.assertGreaterEqual(
            len(review["next_video_strategy"]["script_directives"]),
            3,
        )

    def test_extracts_public_video_and_delta(self) -> None:
        data = {
            "items": [{
                "contentId": "abc123",
                "contentImage": {"items": [{"thumbnailBadgeViewModel": {"text": "3:21"}}]},
                "metadata": {"lockupMetadataViewModel": {
                    "title": {"content": "貝爾女巫事件"},
                    "metadata": {"contentMetadataViewModel": {"metadataRows": [{"metadataParts": [
                        {"text": {"content": "觀看次數：12次"}},
                        {"text": {"content": "7 天前"}},
                    ]}]}}
                }}
            }]
        }
        html = f"<script>{INITIAL_DATA_MARKER}{json.dumps(data)};</script>"
        videos = extract_videos(extract_initial_data(html), {"abc123": 10})
        self.assertEqual(videos[0]["view_delta"], 2)
        self.assertEqual(videos[0]["duration"], "3:21")

    def test_existing_views(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "data.json"
            path.write_text('{"videos":[{"video_id":"abc","views":9}]}', encoding="utf-8")
            self.assertEqual(existing_views(path), {"abc": 9})


if __name__ == "__main__":
    unittest.main()
