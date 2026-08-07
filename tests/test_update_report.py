import json
import tempfile
import unittest
from pathlib import Path

from tools.update_report import (
    INITIAL_DATA_MARKER,
    classify_series,
    existing_views,
    extract_initial_data,
    extract_videos,
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
