#!/usr/bin/env python3
"""Refresh bounded public metrics, preserving unknown values and stale snapshots."""
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
AUTO_SNAPSHOT_PATH = OUTPUT_PATH.with_name("public-channel-snapshot.json")
USER_AGENT = "yt-ailazybag-public-report/2.0 (+https://github.com/ryamhome/yt-ailazybag-report)"
INITIAL_DATA_MARKER = "var ytInitialData = "
MAX_PUBLIC_VIDEOS = 12
TARGET_VIEWS = 1_000
TARGET_WINDOW_DAYS = 7
TAIPEI = ZoneInfo("Asia/Taipei")
STALE_AFTER_HOURS = 96
PREVIOUS_REPORT_URL = os.environ.get("PREVIOUS_REPORT_URL", "https://ryamhome.github.io/yt-ailazybag-report/data.json")
COUNT = r"([0-9][0-9,.]*\s*[萬千億KMB]?)"
VIEW_PATTERNS = (
    re.compile(r"觀看次數\s*[:：]?\s*" + COUNT, re.I),
    re.compile(COUNT + r"\s*(?:次觀看|觀看次數|views?\b)", re.I),
)
AGE_PATTERN = re.compile(
    r"(?:\d+\s*(?:分鐘|小時|天|週|個月|月|年)\s*前|\d+\s*(?:minutes?|hours?|days?|weeks?|months?|years?)\s+ago|剛剛|just now)", re.I
)


def walk(value: Any) -> Iterable[Any]:
    yield value
    if isinstance(value, dict):
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def text_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    if not isinstance(value, dict):
        return ""
    for key in ("content", "simpleText"):
        if isinstance(value.get(key), str):
            return value[key]
    if isinstance(value.get("runs"), list):
        return "".join(str(run.get("text", "")) for run in value["runs"] if isinstance(run, dict))
    return ""


def extract_initial_data(html_text: str) -> dict[str, Any]:
    # YouTube varies the assignment syntax; parse exactly one JSON object.
    match = re.search(r'(?:var\s+ytInitialData\s*=\s*|window\["ytInitialData"\]\s*=\s*|ytInitialData\s*=\s*)', html_text)
    if match is None:
        raise RuntimeError("Public YouTube page did not contain ytInitialData")
    payload, _ = json.JSONDecoder().raw_decode(html_text[match.end():])
    if not isinstance(payload, dict):
        raise RuntimeError("ytInitialData was not an object")
    return payload


def parse_compact_count(text: str) -> int | None:
    normalized = str(text).replace("\u00a0", " ").strip()
    if re.search(r"(?:no\s+views?|(?:尚無|沒有|無)\s*(?:觀看次數|觀看))", normalized, re.I):
        return 0
    match = re.search(COUNT, normalized, re.I)
    if not match:
        return None
    token = match.group(1).replace(" ", "").replace(",", "")
    number = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)([萬千億KMB]?)", token, re.I)
    if not number:
        return None
    value = float(number.group(1))
    multiplier = {"": 1, "千": 1_000, "K": 1_000, "萬": 10_000, "億": 100_000_000, "M": 1_000_000, "B": 1_000_000_000}[number.group(2).upper()]
    return round(value * multiplier)


def known_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int) and value >= 0:
        return value
    if isinstance(value, str) and re.fullmatch(r"\d+", value):
        return int(value)
    return None


def parse_timestamp(text: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(re.sub(r"[Zz]$", "+00:00", str(text)))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=TAIPEI)
        return parsed.astimezone(TAIPEI)
    except (ValueError, TypeError):
        return None


def parse_age_days(text: str, now: datetime | None = None) -> int | None:
    normalized = str(text).strip().lower()
    if not normalized:
        return None
    match = AGE_PATTERN.search(normalized)
    if match:
        phrase = match.group(0)
        if re.search(r"分鐘|小時|minutes?|hours?|剛剛|just now", phrase):
            return 0
        for pattern, multiplier in ((r"(\d+)\s*(?:天|days?)", 1), (r"(\d+)\s*(?:週|weeks?)", 7), (r"(\d+)\s*(?:個月|月|months?)", 30), (r"(\d+)\s*(?:年|years?)", 365)):
            value = re.search(pattern, phrase)
            if value:
                return int(value.group(1)) * multiplier
    # Official API dates are authoritative; bare integers are never an age.
    parsed = parse_timestamp(normalized) if re.match(r"\d{4}-\d{2}-\d{2}", normalized) else None
    if parsed is not None:
        days = ((now or datetime.now(TAIPEI)) - parsed).days
        return days if days >= 0 else None
    return None


def evaluate_video(video: dict[str, Any], now: datetime | None = None) -> dict[str, Any]:
    age_days = parse_age_days(str(video.get("published_at") or video.get("published_text") or ""), now)
    views = known_count(video.get("views"))
    if views is None or age_days is None:
        status = "data_unavailable"
    elif age_days < TARGET_WINDOW_DAYS:
        status = "early_watch"
    elif views >= TARGET_VIEWS:
        status = "target_met"
    else:
        status = "under_target"
    return {**video, "views": views, "age_days": age_days, "goal_views": TARGET_VIEWS,
            "goal_window_days": TARGET_WINDOW_DAYS,
            "goal_gap": max(0, TARGET_VIEWS - views) if views is not None else None,
            "achievement_rate": round(min(views / TARGET_VIEWS, 9.999), 3) if views is not None else None,
            "performance_status": status}


def build_weekly_review(videos: list[dict[str, Any]], report_date: str, *, available: bool = True,
                        as_of: datetime | None = None) -> dict[str, Any]:
    # Age and cumulative views must describe the same snapshot, never wall-clock
    # age paired with an older snapshot's view count.
    snapshot_time = as_of or parse_timestamp(report_date)
    evaluated = [evaluate_video(video, snapshot_time) for video in videos]
    unknown = [v for v in evaluated if v["performance_status"] == "data_unavailable"]
    complete = available and bool(videos) and not unknown
    mature = [v for v in evaluated if v["age_days"] is not None and v["age_days"] >= TARGET_WINDOW_DAYS and v["views"] is not None]
    under = sorted((v for v in mature if v["performance_status"] == "under_target"), key=lambda v: v["views"])
    early = [v for v in evaluated if v["performance_status"] == "early_watch"]
    met = [v for v in mature if v["performance_status"] == "target_met"]
    if not complete:
        summary = "資料不完整或更新失敗，暫停成效判讀；未知值不代表零觀看，也不能判斷影片尚未滿七天。"
    elif not mature:
        summary = "這次樣本尚無發布滿七天的影片，先追蹤已知資料。"
    elif under:
        summary = f"樣本中 {len(under)} 支上架滿七天影片的累計觀看未達 1,000；這不是上架首七日觀看統計。"
    else:
        summary = "樣本中已滿七天的影片，累計觀看均達 1,000；仍需點閱率與留存資料判斷原因。"
    script = ["首秒進入具體事件，十五秒內建立單一疑問。", "每三十至四十五秒帶出新的證據或轉折，避免重複摘要。", "清楚區分已知事實、推測與仍未解的問題。"] if complete else []
    packaging = ["標題與縮圖呈現具體事件或證據，每次只測試一個變因。"] if complete else []
    images = ["固定史料與場景圖像；用對應動畫說明人數、航線、日期及物件關係。"] if complete else []
    return {"status": "available" if complete else "data_unavailable", "review_date": report_date,
            "goal_views": TARGET_VIEWS, "goal_window_days": TARGET_WINDOW_DAYS,
            "mature_video_count": len(mature), "target_met_count": len(met), "under_target_count": len(under),
            "early_watch_count": len(early), "unknown_video_count": len(unknown), "summary": summary,
            "underperformers": [{k: v[k] for k in ("video_id", "title", "url", "views", "age_days", "goal_gap")} for v in under] if complete else [],
            "limitations": "只比較這次樣本的累計公開觀看，無法回推上架首七日。公開資料不能判定曝光、CTR、留存或收益；建議是待驗證假設。",
            "next_video_strategy": {"summary": summary, "script_directives": script, "packaging_directives": packaging, "image_directives": images}}


def classify_series(title: str) -> str:
    if "真實犯罪" in title or any(word in title for word in ("殺手", "謀殺", "命案", "犯罪", "案件")):
        return "真實犯罪"
    if any(word in title for word in ("女巫", "靈異", "鬼", "騷靈", "超自然")):
        return "靈異檔案"
    return "歷史謎案"


def short_title(title: str) -> str:
    cleaned = re.sub(r"[\[【].*?[\]】]", "", title).strip()
    return cleaned.split("：", 1)[0].split("｜", 1)[0].strip()[:18]


def metadata_parts(node: dict[str, Any]) -> list[str]:
    model = node.get("metadata", {}).get("lockupMetadataViewModel", {})
    rows = model.get("metadata", {}).get("contentMetadataViewModel", {}).get("metadataRows", [])
    # Keep each complete row. Split numeric/label pieces must not lose context.
    return [" ".join(text_value(part.get("text", {})) for part in row.get("metadataParts", [])) for row in rows]


def accessibility_texts(node: dict[str, Any]) -> list[str]:
    texts = []
    for value in walk(node):
        if not isinstance(value, dict):
            continue
        for key in ("accessibilityText", "label"):
            if isinstance(value.get(key), str):
                texts.append(value[key])
    return texts


def view_count(texts: list[str]) -> int | None:
    for text in texts:
        if re.search(r"(?:no\s+views?|(?:尚無|沒有|無)\s*(?:觀看次數|觀看))", text, re.I):
            return 0
        for pattern in VIEW_PATTERNS:
            match = pattern.search(text)
            if match:
                return parse_compact_count(match.group(1))
    return None


def published_text(texts: list[str]) -> str | None:
    for text in texts:
        match = AGE_PATTERN.search(text.replace("\u00a0", " "))
        if match:
            return match.group(0)
    return None


def duration_text(node: dict[str, Any]) -> str:
    for item in walk(node.get("contentImage", {})):
        if isinstance(item, dict):
            badge = item.get("thumbnailBadgeViewModel")
            if isinstance(badge, dict):
                text = text_value(badge.get("text"))
                if re.fullmatch(r"(?:\d+:)?\d{1,2}:\d{2}", text):
                    return text
    return "-"


def video_scope(data: dict[str, Any]) -> Any:
    tabs = data.get("contents", {}).get("twoColumnBrowseResultsRenderer", {}).get("tabs", [])
    for item in tabs:
        tab = item.get("tabRenderer", {})
        if tab.get("selected") is True:
            return tab.get("content", {})
    return data


def extract_videos(data: dict[str, Any], previous: dict[str, int]) -> list[dict[str, Any]]:
    videos: dict[str, dict[str, Any]] = {}
    for node in walk(video_scope(data)):
        if not isinstance(node, dict):
            continue
        if "videoRenderer" in node:
            legacy = node["videoRenderer"]
            video_id = legacy.get("videoId")
            title = text_value(legacy.get("title"))
            count = view_count([text_value(legacy.get("viewCountText")), text_value(legacy.get("shortViewCountText"))])
            published = published_text([text_value(legacy.get("publishedTimeText"))])
            duration = text_value(legacy.get("lengthText")) or "-"
        else:
            video_id = node.get("contentId")
            model = node.get("metadata", {}).get("lockupMetadataViewModel")
            if not isinstance(video_id, str) or not isinstance(model, dict):
                continue
            if node.get("contentType") not in (None, "LOCKUP_CONTENT_TYPE_VIDEO"):
                continue
            title = text_value(model.get("title"))
            texts = metadata_parts(node) + accessibility_texts(node)
            count = view_count(texts)
            published = published_text(texts)
            duration = duration_text(node)
        if not isinstance(video_id, str) or not video_id or not title.strip():
            continue
        delta = count - previous[video_id] if count is not None and video_id in previous else None
        videos[video_id] = evaluate_video({"video_id": video_id, "title": title.strip(), "short_title": short_title(title),
            "views": count, "view_delta": delta, "published_text": published, "duration": duration,
            "series": classify_series(title), "thumbnail_url": f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg", "url": f"https://www.youtube.com/watch?v={video_id}"})
        if len(videos) >= MAX_PUBLIC_VIDEOS:
            break
    return list(videos.values())


def extract_subscribers(data: dict[str, Any]) -> int | None:
    for node in walk(data):
        if not isinstance(node, dict):
            continue
        text = text_value(node)
        if re.search(r"位訂閱者|subscribers?\b", text, re.I):
            return parse_compact_count(text)
    return None


def views_from_report(data: dict[str, Any]) -> dict[str, int]:
    # Reject the known broken legacy snapshot, whose date fields were view counts.
    videos = data.get("videos", [])
    malformed = bool(videos) and all(v.get("views") == 0 and parse_age_days(str(v.get("published_at") or v.get("published_text") or "")) is None for v in videos)
    if malformed or data.get("data_quality", {}).get("status") == "invalid":
        return {}
    return {str(v["video_id"]): count for v in videos if (count := known_count(v.get("views"))) is not None}


def existing_views(path: Path) -> dict[str, int]:
    if not path.is_file():
        return {}
    return views_from_report(json.loads(path.read_text(encoding="utf-8")))


def deployed_report(url: str = PREVIOUS_REPORT_URL) -> dict[str, Any] | None:
    if not url:
        return None
    try:
        response = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=12)
        response.raise_for_status()
        data = response.json()
        return data if isinstance(data, dict) else None
    except (requests.RequestException, ValueError, TypeError):
        return None


def deployed_views(url: str = PREVIOUS_REPORT_URL) -> dict[str, int]:
    return views_from_report(deployed_report(url) or {})


def fetch_page() -> str:
    response = requests.get(CHANNEL_URL, headers={"User-Agent": USER_AGENT, "Accept-Language": "zh-TW,zh;q=0.9"}, timeout=25)
    response.raise_for_status()
    if len(response.text) < 100_000:
        raise RuntimeError("Public YouTube response was unexpectedly small")
    return response.text


def quality(videos: list[dict[str, Any]], checked_at: str) -> dict[str, Any]:
    known = sum(v.get("views") is not None for v in videos)
    unknown_age = sum(v.get("age_days") is None for v in videos)
    status = "valid" if videos and known == len(videos) and unknown_age == 0 else "partial"
    if not videos or known == 0 or unknown_age == len(videos):
        status = "invalid"
    return {"status": status, "message": {"valid": "這次樣本的觀看數與發布時間已讀取；不是整個頻道的總計。", "partial": "部分觀看數或發布時間未知，暫停自動成效判讀。", "invalid": "無法可靠讀取觀看數或發布時間；未知不是零，已暫停成效判讀。"}[status],
            "checked_at": checked_at, "last_valid_at": checked_at if status == "valid" else None,
            "known_view_count": known, "unknown_view_count": len(videos)-known, "unknown_age_count": unknown_age}


def make_report(videos: list[dict[str, Any]], subscribers: int | None, source: str, generated_at: str,
                owner_analytics: dict[str, Any] | None = None) -> dict[str, Any]:
    q = quality(videos, generated_at)
    owner = owner_analytics or {}
    owner_status = owner.get("status") if owner.get("status") in {"not_connected", "reauthorization_required", "available"} else "not_connected"
    public_owner = {"status": owner_status, "message": str(owner.get("message") or "尚未連接頻道擁有者 Analytics；曝光、CTR、留存與收益沒有可用數值。")}
    return {"schema_version": 2, "report_date": generated_at[:10], "generated_at": generated_at,
            "last_attempt_at": datetime.now(TAIPEI).isoformat(timespec="seconds"), "source": source,
            "scope": "latest_public_sample", "sample_limit": MAX_PUBLIC_VIDEOS,
            "sample_video_count": len(videos), "public_video_count": len(videos),
            "public_view_total": sum(v["views"] for v in videos) if videos and all(v["views"] is not None for v in videos) else None,
            "public_subscriber_count": known_count(subscribers), "videos": videos, "data_quality": q,
            "owner_analytics": public_owner,
            "weekly_review": build_weekly_review(videos, generated_at[:10], available=q["status"] == "valid", as_of=parse_timestamp(generated_at))}


def build_report(data: dict[str, Any], previous: dict[str, int]) -> dict[str, Any]:
    now = datetime.now(TAIPEI).isoformat(timespec="seconds")
    videos = extract_videos(data, previous)
    if not videos:
        raise RuntimeError("No public videos found")
    return make_report(videos, extract_subscribers(data), CHANNEL_URL, now)


def build_report_from_snapshot(snapshot: dict[str, Any], previous: dict[str, int]) -> dict[str, Any]:
    if snapshot.get("data_quality", {}).get("status") in {"invalid", "unavailable"}:
        raise RuntimeError("Official public snapshot is unavailable")
    generated_at = parse_timestamp(snapshot.get("generated_at", ""))
    if generated_at is None:
        raise RuntimeError("Official public snapshot has no valid generated_at")
    age_hours = (datetime.now(TAIPEI)-generated_at).total_seconds()/3600
    if age_hours > STALE_AFTER_HOURS or age_hours < -1:
        raise RuntimeError("Official public snapshot is stale or future-dated")
    videos = []
    for raw in snapshot.get("videos", [])[:MAX_PUBLIC_VIDEOS]:
        video_id = str(raw.get("video_id", "")); title = str(raw.get("title", "")).strip()
        if not video_id or not title:
            continue
        count = known_count(raw.get("views"))
        pub = str(raw.get("published_at") or "")
        video = evaluate_video({"video_id": video_id, "title": title, "short_title": short_title(title),
            "views": count, "view_delta": count-previous[video_id] if count is not None and video_id in previous else None,
            "published_at": pub, "published_text": pub[:10] if parse_timestamp(pub) else None,
            "duration": raw.get("duration", "-"), "series": raw.get("series") or classify_series(title),
            "thumbnail_url": raw.get("thumbnail_url") or f"https://i.ytimg.com/vi/{video_id}/hqdefault.jpg",
            "url": raw.get("url") or f"https://www.youtube.com/watch?v={video_id}"}, generated_at)
        videos.append(video)
    if not videos:
        raise RuntimeError("Official public snapshot has no usable videos")
    # Never copy private Analytics values into a public dashboard snapshot.
    owner = snapshot.get("owner_analytics") or {}
    owner_status = owner.get("status") if owner.get("status") in {"not_connected", "reauthorization_required", "available"} else "not_connected"
    return make_report(videos, snapshot.get("public_subscriber_count"), str(snapshot.get("source") or "YouTube Data API v3"), generated_at.isoformat(timespec="seconds"),
                       {"status": owner_status, "message": str(owner.get("message") or "頻道擁有者資料另存私人報表；公開頁只顯示公開資料。")})


def sanitize_previous(report: dict[str, Any]) -> dict[str, Any]:
    videos = report.get("videos", [])
    malformed = (report.get("data_quality", {}).get("status") == "invalid" or
                 bool(videos) and all(v.get("views") == 0 and parse_age_days(str(v.get("published_at") or v.get("published_text") or "")) is None for v in videos))
    cleaned = []
    generated_at = str(report.get("generated_at") or "")
    snapshot_time = parse_timestamp(generated_at)
    for v in videos:
        cleaned.append(evaluate_video({**v, "views": None if malformed else v.get("views"),
            "published_text": None if parse_age_days(str(v.get("published_at") or v.get("published_text") or "")) is None else v.get("published_text"),
            "view_delta": None if malformed else v.get("view_delta")}, snapshot_time))
    clean = make_report(cleaned, report.get("public_subscriber_count"), str(report.get("source") or CHANNEL_URL), generated_at, report.get("owner_analytics"))
    clean["generated_at"] = generated_at or None
    return clean


def stale_report(previous: dict[str, Any] | None, reason: str) -> dict[str, Any]:
    now = datetime.now(TAIPEI).isoformat(timespec="seconds")
    report = sanitize_previous(previous or {})
    valid = report["data_quality"]["status"] == "valid"
    report["last_attempt_at"] = now
    report["data_quality"].update({"status": "stale" if valid else "invalid", "checked_at": now,
        "last_valid_at": report.get("generated_at") if valid else None,
        "message": "本次更新失敗，顯示上次成功快照；數字不是目前即時資料。" if valid else "本次更新失敗，舊資料也無法可靠解析；未知值以 — 顯示，暫停成效判讀。",
        "failure_reason": reason})
    report["weekly_review"] = build_weekly_review(report["videos"], now[:10], available=False, as_of=parse_timestamp(report.get("generated_at") or ""))
    return report


def write_report(report: dict[str, Any], path: Path = OUTPUT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    temporary.replace(path)


def fresh_saved_snapshot(path: Path = AUTO_SNAPSHOT_PATH) -> dict[str, Any] | None:
    """Prefer a fresh public-only API artifact committed by the private collector."""
    if not path.is_file():
        return None
    try:
        snapshot = json.loads(path.read_text(encoding="utf-8"))
        stamp = parse_timestamp(snapshot.get("generated_at", ""))
        if stamp is None or snapshot.get("data_quality", {}).get("status") in {"invalid", "unavailable"}:
            return None
        age = (datetime.now(TAIPEI)-stamp).total_seconds()/3600
        return snapshot if -1 <= age <= STALE_AFTER_HOURS else None
    except (ValueError, TypeError, OSError):
        return None


def main() -> int:
    local = json.loads(OUTPUT_PATH.read_text(encoding="utf-8")) if OUTPUT_PATH.is_file() else None
    deployed = deployed_report()
    candidates = [x for x in (local, deployed) if x]
    valid = [x for x in candidates if sanitize_previous(x)["data_quality"]["status"] == "valid"]
    previous = max(valid or candidates, key=lambda x: str(x.get("generated_at") or "")) if candidates else None
    prior_views = views_from_report(previous or {})
    try:
        snapshot_path = os.environ.get("REPORT_SNAPSHOT_PATH", "").strip()
        snapshot = json.loads(Path(snapshot_path).read_text(encoding="utf-8")) if snapshot_path else fresh_saved_snapshot()
        report = build_report_from_snapshot(snapshot, prior_views) if snapshot is not None else build_report(extract_initial_data(fetch_page()), prior_views)
        if report["data_quality"]["status"] == "invalid":
            raise RuntimeError("Refreshed page has no reliable views or publication dates")
    except (requests.RequestException, OSError, RuntimeError, ValueError, TypeError, KeyError) as exc:
        # Publish a clear stale/invalid state, not a fresh-looking zero snapshot.
        report = stale_report(previous, type(exc).__name__)
        print("::warning::Public data refresh failed; deploying explicit stale/unknown status, with automatic analysis paused.")
    write_report(report, OUTPUT_PATH)
    state = report["data_quality"]["status"]
    print(f"Report state: {state}; sample: {report['sample_video_count']} videos")
    if os.environ.get("GITHUB_OUTPUT"):
        with Path(os.environ["GITHUB_OUTPUT"]).open("a", encoding="utf-8") as stream:
            stream.write(f"data_status={state}\n")
    if os.environ.get("GITHUB_STEP_SUMMARY"):
        with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a", encoding="utf-8") as stream:
            stream.write(f"## Public report data: {state}\n\n")
            stream.write(f"{report['data_quality']['message']}\n\n")
            stream.write(f"Snapshot: {report.get('generated_at') or 'unknown'}; checked: {report['last_attempt_at']}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
