#!/usr/bin/env python3
"""Refresh the report from one public YouTube channel-page request."""

from __future__ import annotations

import json
import os
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
TARGET_VIEWS = 1_000
TARGET_WINDOW_DAYS = 7
PREVIOUS_REPORT_URL = os.environ.get(
    "PREVIOUS_REPORT_URL",
    "https://ryamhome.github.io/yt-ailazybag-report/data.json",
)


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


def parse_age_days(text: str) -> int | None:
    normalized = text.strip().lower()
    if any(marker in normalized for marker in ("分鐘前", "小時前", "minute", "hour", "剛剛")):
        return 0
    patterns = (
        (r"(\d+)\s*天前", 1),
        (r"(\d+)\s*週前", 7),
        (r"(\d+)\s*(?:個月|月)前", 30),
        (r"(\d+)\s*年前", 365),
        (r"(\d+)\s*day", 1),
        (r"(\d+)\s*week", 7),
        (r"(\d+)\s*month", 30),
        (r"(\d+)\s*year", 365),
    )
    for pattern, multiplier in patterns:
        match = re.search(pattern, normalized)
        if match:
            return int(match.group(1)) * multiplier
    return None


def evaluate_video(video: dict[str, Any]) -> dict[str, Any]:
    age_days = parse_age_days(str(video.get("published_text") or ""))
    views = int(video.get("views") or 0)
    gap = max(0, TARGET_VIEWS - views)
    if age_days is None:
        status = "tracking"
    elif age_days < TARGET_WINDOW_DAYS:
        status = "early_watch"
    elif views >= TARGET_VIEWS:
        status = "target_met"
    else:
        status = "under_target"
    return {
        **video,
        "age_days": age_days,
        "goal_views": TARGET_VIEWS,
        "goal_window_days": TARGET_WINDOW_DAYS,
        "goal_gap": gap,
        "achievement_rate": round(min(views / TARGET_VIEWS, 9.999), 3),
        "performance_status": status,
    }


def build_weekly_review(videos: list[dict[str, Any]], report_date: str) -> dict[str, Any]:
    evaluated = [evaluate_video(video) for video in videos]
    mature = [video for video in evaluated if (video.get("age_days") or 0) >= TARGET_WINDOW_DAYS]
    under = [video for video in mature if video["performance_status"] == "under_target"]
    early = [video for video in evaluated if video["performance_status"] == "early_watch"]
    met = [video for video in mature if video["performance_status"] == "target_met"]
    under.sort(key=lambda item: int(item.get("views") or 0))

    if not mature:
        summary = "尚無發布滿 7 天的影片；本週只做早期預警，不提前判定失敗。"
    elif under:
        summary = (
            f"{len(under)} 支滿 7 天影片未達 1,000 次觀看；"
            "下一輪優先改善題材包裝、前 15 秒鉤子與證據轉折密度。"
        )
    else:
        summary = "所有已滿 7 天的影片均達 1,000 次觀看；保留有效結構，每次只測一項包裝變因。"

    script_directives = [
        "前兩句必須交代具體時間、地點、人物行動與異常後果，15 秒內形成單一疑問。",
        "每 30 到 45 秒至少出現一項新證據、反證或解釋轉折，禁止重複摘要。",
        "結尾只保留一個仍無法解答的核心問題，並清楚區分已知事實與推測。",
    ]
    packaging_directives = [
        "標題使用主題全名加具體異常或關鍵證據，不使用空泛的未解之謎。",
        "縮圖維持檔案紙張品牌，主字 4 到 8 字、紅色副鉤子 8 到 14 字、只保留一個視覺焦點。",
    ]
    image_directives = [
        "畫面每 10 到 15 秒更換一次，影像必須對應當下旁白情境。",
        "照片只使用輕微且置中的運鏡，避免持續搖晃或大幅縮放。",
    ]

    return {
        "review_date": report_date,
        "goal_views": TARGET_VIEWS,
        "goal_window_days": TARGET_WINDOW_DAYS,
        "mature_video_count": len(mature),
        "target_met_count": len(met),
        "under_target_count": len(under),
        "early_watch_count": len(early),
        "summary": summary,
        "underperformers": [
            {
                "video_id": video["video_id"],
                "title": video["title"],
                "url": video["url"],
                "views": video["views"],
                "age_days": video["age_days"],
                "goal_gap": video["goal_gap"],
            }
            for video in under
        ],
        "limitations": (
            "本檢討只使用公開觀看數，無法判定曝光、CTR 或留存率；"
            "改善項目屬可驗證假設，不會宣稱單一原因。"
        ),
        "next_video_strategy": {
            "summary": summary,
            "script_directives": script_directives,
            "packaging_directives": packaging_directives,
            "image_directives": image_directives,
        },
    }


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
        videos[video_id] = evaluate_video({
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
        })
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


def deployed_views(url: str = PREVIOUS_REPORT_URL) -> dict[str, int]:
    if not url:
        return {}
    try:
        response = requests.get(
            url,
            headers={"User-Agent": USER_AGENT},
            timeout=12,
        )
        response.raise_for_status()
        data = response.json()
        return {
            str(video["video_id"]): int(video.get("views", 0))
            for video in data.get("videos", [])
        }
    except (requests.RequestException, ValueError, KeyError, TypeError):
        return {}


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
    report_date = now.date().isoformat()
    return {
        "report_date": report_date,
        "generated_at": now.isoformat(timespec="seconds"),
        "source": CHANNEL_URL,
        "public_video_count": len(videos),
        "public_view_total": sum(video["views"] for video in videos),
        "public_subscriber_count": extract_subscribers(data),
        "videos": videos,
        "weekly_review": build_weekly_review(videos, report_date),
    }


def main() -> int:
    previous = deployed_views() or existing_views(OUTPUT_PATH)
    report = build_report(extract_initial_data(fetch_page()), previous)
    OUTPUT_PATH.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
