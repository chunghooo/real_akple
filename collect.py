# collect.py
import re
import requests

API_URL = "https://www.googleapis.com/youtube/v3"

ERROR_MESSAGES = {
    "commentsDisabled": "이 영상은 댓글이 꺼져 있어요.",
    "videoNotFound": "영상을 찾을 수 없어요.",
    "quotaExceeded": "오늘 API 사용량을 다 썼어요.",
    "keyInvalid": "API 키가 올바르지 않아요.",
}

_VIDEO_ID_RE = re.compile(
    r"(?:watch\?v=|youtu\.be/|shorts/|embed/|live/)([0-9A-Za-z_-]{11})"
)


def video_id(url: str):
    if not url:
        return None
    m = _VIDEO_ID_RE.search(url)
    if m:
        return m.group(1)
    if re.fullmatch(r"[0-9A-Za-z_-]{11}", url.strip()):
        return url.strip()
    return None


def _raise_api_error(resp_json: dict, status_code: int):
    errors = resp_json.get("error", {}).get("errors", [])
    reason = errors[0].get("reason") if errors else None
    if reason in ERROR_MESSAGES:
        raise RuntimeError(ERROR_MESSAGES[reason])
    if status_code == 403:
        msg = resp_json.get("error", {}).get("message", "")
        if "quota" in msg.lower():
            raise RuntimeError(ERROR_MESSAGES["quotaExceeded"])
        if "key" in msg.lower() or "API key" in msg:
            raise RuntimeError(ERROR_MESSAGES["keyInvalid"])
    raise RuntimeError(resp_json.get("error", {}).get("message", "알 수 없는 오류가 발생했어요."))


def _get(path: str, params: dict):
    resp = requests.get(f"{API_URL}/{path}", params=params, timeout=15)
    try:
        data = resp.json()
    except ValueError:
        data = {}
    if resp.status_code != 200 or "error" in data:
        if resp.status_code == 400 and data.get("error", {}).get("errors", [{}])[0].get("reason") == "keyInvalid":
            raise RuntimeError(ERROR_MESSAGES["keyInvalid"])
        _raise_api_error(data, resp.status_code)
    return data


def _common_row(snippet: dict, comment_id: str, vid: str) -> dict:
    author = snippet.get("authorDisplayName", "미확인")
    channel = snippet.get("authorChannelUrl", "미확인")
    cid = snippet.get("authorChannelId", {}).get("value", "미확인")
    text = snippet.get("textOriginal", snippet.get("textDisplay", ""))
    time_ = snippet.get("publishedAt", "미확인")
    return {
        "id": comment_id,
        "author": author,
        "channel": channel,
        "cid": cid,
        "text": text,
        "time": time_,
        "link": f"https://www.youtube.com/watch?v={vid}&lc={comment_id}",
        "label": "미확인",
        "severity": 0,
        "category": "미확인",
        "reason": "미확인",
        "law": "미확인",
        "statute": "미확인",
        "ai": "미확인",
        "gem": "미확인",
        "target": "",
        "memo": "",
    }


def _fetch_all_replies(parent_id: str, key: str, vid: str):
    rows = []
    page_token = None
    while True:
        params = {
            "part": "snippet",
            "parentId": parent_id,
            "maxResults": 100,
            "textFormat": "plainText",
            "key": key,
        }
        if page_token:
            params["pageToken"] = page_token
        data = _get("comments", params)
        for item in data.get("items", []):
            snippet = item.get("snippet", {})
            cid_ = item.get("id")
            rows.append(_common_row(snippet, cid_, vid))
        page_token = data.get("nextPageToken")
        if not page_token:
            break
    return rows


def fetch(video_id: str, key: str, limit: int, progress=None):
    rows = []
    raw_pages = []
    seen = set()
    page_token = None
    n = 0

    while True:
        params = {
            "part": "snippet,replies",
            "videoId": video_id,
            "maxResults": 100,
            "textFormat": "plainText",
            "key": key,
        }
        if page_token:
            params["pageToken"] = page_token

        data = _get("commentThreads", params)
        raw_pages.append(data)

        for item in data.get("items", []):
            top_snippet = item["snippet"]["topLevelComment"]["snippet"]
            top_id = item["snippet"]["topLevelComment"]["id"]
            if top_id not in seen:
                seen.add(top_id)
                rows.append(_common_row(top_snippet, top_id, video_id))
                n += 1
                if progress:
                    progress(n)
                if len(rows) >= limit:
                    return rows[:limit], raw_pages

            total_reply_count = item["snippet"].get("totalReplyCount", 0)
            replies_obj = item.get("replies", {}).get("comments", [])

            if total_reply_count > len(replies_obj):
                reply_rows = _fetch_all_replies(top_id, key, video_id)
            else:
                reply_rows = []
                for r in replies_obj:
                    rid = r.get("id")
                    reply_rows.append(_common_row(r.get("snippet", {}), rid, video_id))

            for rr in reply_rows:
                if rr["id"] not in seen:
                    seen.add(rr["id"])
                    rows.append(rr)
                    n += 1
                    if progress:
                        progress(n)
                    if len(rows) >= limit:
                        return rows[:limit], raw_pages

        page_token = data.get("nextPageToken")
        if not page_token:
            break

    return rows[:limit], raw_pages
