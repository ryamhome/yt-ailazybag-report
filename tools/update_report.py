#!/usr/bin/env python3
"""Refresh the report from one public YouTube channel-page request."""

from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import requests


CHANNEL_URL = "https://www.youtube.com/@ailazybag/videos"
OUTPUT_PATH = Path(__file__).resolve().parents[1] / "docs" / "data.json"
USER_AGENT = (
    "Mozilla/5.0 (compatible; yt-ailazybag-public-report/1.0; "
    "+https://github.com/ryamhome/yt-ailazybag-report)"
)
INITIAL_DATA_MARKER = "var ytInitialData = "
MAX_PUBLIC_VIDEOS = 12


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def extract_initial_data(html_text: str) -> dict[str, Any]:
    marker_index = html_text.find(INITIAL_DATA_MARKER)
    if marker_index < 0:
        raise RuntimeError("Public YouTube page did not contain ytInitialData")
    start = marker_index + len(INITIAL_DATA_MARKER)
    payload, _ = json.JSONDecoder().raw_decode(html_text[start:])
    if not isinstance(payload, dict):
        raise RuntimeError("ytInitialData was not an object")
    return payload


def parse_compact_count(text: str) -> int:
    cleaned = text.replace("觀看次數：", "").replace("觀看次數", "").replace("次", "")
    match = re.search(r"([0-9][0-9,.]*)\s*([萬千KMB]?)", cleaned, re.IGNORECASE)
    if not match:
        return 0
    value = float(match.group(1).replace(",", ""))
    unit = match.group(2).upper()
    multiplier = {"": 1, "千": 1_000, "K": 1_000, "萬": 10_000, "M": 1_000_000, "B": 1_000_000_000}[unit]
    return round(value * multiplier)


def classify_series(title: str) -> str:
    if "真實犯罪" in title or any(word in title for word in ("殺手", "謀殺", "命案", "犯罪", "案件")):
        return "真實犯罪"
    if any(word in title for word in ("女巫", "靈異", "鬼", "騷靈", "超自然")):
        return "靈異檔案"
    return "歷史謎案"


def short_title(title: str) -> str:
    cleaned = re.sub(r"[\[【].*?[\]】]", "", title).strip()
    cleaned = cleaned.split("：", 1)[0].split("｜", 1)[0].strip()
    return cleaned[:18]


def metadata_parts(node: dict[str, Any]) -> list[str]:
    model = node.get("metadata", {}).get("lockupMetadataViewModel", {})
    rows = model.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
    parts: list[str] = []
    for row in rows:
        for part in row.get("metadataParts", []):
            content = part.get("text", {}).get("content")
            if isinstance(content, str):
                parts.append(content)
    return parts


def duration_text(node: dict[str, Any]) -> str:
    for item in walk(node.get("contentImage", {})):
        if isinstance(item, dict):
            badge = item.get("thumbnailBadgeViewModel")
            if isinstance(badge, dict) and isinstance(badge.get("text"), str):
                return badge["text"]
    return "-"


def extract_videos(data: dict[str, Any], previous: dict[str, int]) -> list[dict[str, Any]]:
    videos: dict[str, dict[str, Any]] = {}
    for node in walk(data):
        if not isinstance(node, dict):
            continue
        video_id = node.get("contentId")
        model = node.get("metadata", {}).get("lockupMetadataViewModel")
        if not isinstance(video_id, str) or not isinstance(model, dict):
            continue
        title = model.get("title", {}).get("content")
        if not isinstance(title, str) or not title.strip():
            continue
        parts = metadata_parts(node)
        view_text = next((part for part in parts if "觀看" in part or "view" in part.lower()), "0")
        published = next((part for part in parts if part != view_text), "-")
        views = parse_compact_count(view_text)
        videos[video_id] = {
            "video_id": video_id,
            "title": title.strip(),
            "short_title": short_title(title),
            "views": views,
            "view_delta": max(0, views - previous.get(video_id, views)),
            "published_text": published,
            "duration": duration_text(node),
            "series": classify_series(title),
            "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "url": f"https://www.youtube.com/watch?v={video_id}",
        }
        if len(videos) >= MAX_PUBLIC_VIDEOS:
            break
    return list(videos.values())


def extract_subscribers(data: dict[str, Any]) -> int | None:
    for node in walk(data):
        if isinstance(node, dict):
            content = node.get("content")
            if isinstance(content, str) and ("位訂閱者" in content or "subscriber" in content.lower()):
                return parse_compact_count(content)
    return None


def existing_views(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {str(video["video_id"]): int(video.get("views", 0)) for video in data.get("videos", [])}


def fetch_page() -> str:
    response = requests.get(
        CHANNEL_URL,
        headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"},
        timeout=25,
    )
    response.raise_for_status()
    if len(response.text) < 100_000:
        raise RuntimeError("Public YouTube response was unexpectedly small")
    return response.text


def build_report(data: dict[str, Any], previous: dict[str, int]) -> dict[str, Any]:
    now = datetime.now(ZoneInfo("Asia/Taipei"))
    videos = extract_videos(data, previous)
    if not videos:
        raise RuntimeError("No public videos found; keeping the previous deployed report")
    return {
        "report_date": now.date().isoformat(),
        "generated_at": now.isoformat(timespec="seconds"),
        "source": CHANNEL_URL,
        "public_video_count": len(videos),
        "public_view_total": sum(video["views"] for video in videos),
        "public_subscriber_count": extract_subscribers(data),
        "videos": videos,
    }


def main() -> int:
    previous = existing_views(OUTPUT_PATH)
    report = build_report(extract_initial_data(fetch_page()), previous)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
