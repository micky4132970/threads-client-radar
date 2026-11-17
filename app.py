from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlparse

import requests

ROOT = Path(__file__).resolve().parent
KEYWORDS_FILE = ROOT / "keywords.txt"
OUTPUT_FILE = ROOT / "docs" / "posts.json"
MAX_STORED_POSTS = 800
REQUEST_TIMEOUT = 25
DELAY_BETWEEN_REQUESTS = 4

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
SESSION = requests.Session()
SESSION.headers.update({
    # 一般瀏覽器識別；不使用登入 Cookie、代理輪替或反封鎖技巧
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/130.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "zh-TW,zh;q=0.9,en;q=0.8",
})


def load_keywords() -> list[str]:
    if not KEYWORDS_FILE.exists():
        raise FileNotFoundError("找不到 keywords.txt")
    words = []
    for line in KEYWORDS_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and line not in words:
            words.append(line)
    return words


def text_from_caption(value):
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("text") or value.get("value") or ""
    return ""


def walk(value):
    """遞迴走訪頁面內可見 JSON；不依賴單一固定巢狀路徑。"""
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def normalize_post(obj: dict, keyword: str) -> dict | None:
    code = obj.get("code")
    pk = obj.get("pk") or obj.get("id")
    user = obj.get("user") or obj.get("owner") or {}
    if not isinstance(user, dict):
        user = {}
    username = user.get("username") or obj.get("username") or ""
    caption = obj.get("caption") or obj.get("text") or obj.get("caption_text") or ""
    caption = text_from_caption(caption)

    if not code or not isinstance(caption, str) or not caption.strip():
        return None

    # 不猜測或拼接不完整的貼文識別碼
    url = obj.get("permalink") or obj.get("url")
    if isinstance(url, str):
        host = urlparse(url).netloc.lower()
        if host not in {"threads.com", "www.threads.com", "threads.net", "www.threads.net"}:
            url = None
    else:
        url = None
    if not url and username:
        url = f"https://www.threads.com/@{username}/post/{code}"
    if not url:
        return None

    taken_at = obj.get("taken_at") or obj.get("timestamp") or obj.get("created_at")
    if isinstance(taken_at, (int, float)):
        try:
            created_at = datetime.fromtimestamp(taken_at, tz=timezone.utc).isoformat()
        except (ValueError, OSError):
            created_at = ""
    elif isinstance(taken_at, str):
        created_at = taken_at
    else:
        created_at = ""

    return {
        "id": str(pk or code),
        "code": str(code),
        "keyword": keyword,
        "username": username,
        "text": caption.strip(),
        "url": url,
        "created_at": created_at,
        "likes": obj.get("like_count"),
        "replies": obj.get("reply_count") or obj.get("direct_reply_count"),
        "discovered_at": datetime.now(timezone.utc).isoformat(),
    }


def extract_posts(html: str, keyword: str) -> list[dict]:
    # 僅解析公開 HTML 中已送出的 JSON 區塊，不呼叫內部 GraphQL 或登入端點。
    scripts = re.findall(
        r'<script[^>]*type=["\\\']application/json["\\\'][^>]*>(.*?)</script>',
        html,
        flags=re.I | re.S,
    )
    candidates = []
    for raw in scripts:
        raw = raw.strip()
        if not raw:
            continue
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            continue
        for obj in walk(payload):
            post = normalize_post(obj, keyword)
            if post:
                candidates.append(post)

    # 有些版本會把 JSON 放在一般 script 中；只嘗試解析完整 JSON，不執行 JavaScript。
    if not candidates:
        for raw in re.findall(r"<script[^>]*>(.*?)</script>", html, flags=re.I | re.S):
            raw = raw.strip()
            if not raw.startswith("{") and not raw.startswith("["):
                continue
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                continue
            for obj in walk(payload):
                post = normalize_post(obj, keyword)
                if post:
                    candidates.append(post)

    unique = {}
    for post in candidates:
        unique[post["code"]] = post
    return list(unique.values())


def search_keyword(keyword: str) -> tuple[list[dict], str | None]:
    params = urlencode({"q": keyword, "serp_type": "default"})
    url = f"https://www.threads.com/search?{params}"
    try:
        response = SESSION.get(url, timeout=REQUEST_TIMEOUT)
        if response.status_code in (403, 429):
            return [], f"Threads 回應 HTTP {response.status_code}；本輪停止該搜尋，不嘗試繞過限制。"
        response.raise_for_status()
        posts = extract_posts(response.text, keyword)
        if not posts:
            return [], "頁面沒有可辨識的公開貼文資料。可能需要登入、頁面結構已變更，或匿名搜尋未提供結果。"
        return posts, None
    except requests.RequestException as exc:
        return [], f"連線錯誤：{type(exc).__name__}: {exc}"


def load_existing() -> list[dict]:
    if not OUTPUT_FILE.exists():
        return []
    try:
        data = json.loads(OUTPUT_FILE.read_text(encoding="utf-8"))
        return data.get("posts", []) if isinstance(data, dict) else []
    except (json.JSONDecodeError, OSError):
        logging.warning("舊的 posts.json 無法讀取，將建立新檔。")
        return []


def main():
    keywords = load_keywords()
    existing = load_existing()
    merged = {p.get("code") or p.get("url"): p for p in existing if p.get("code") or p.get("url")}
    errors = []
    observed_this_run = 0
    newly_added_this_run = 0

    for index, keyword in enumerate(keywords):
        logging.info("搜尋關鍵字：%s", keyword)
        posts, error = search_keyword(keyword)
        if error:
            errors.append({"keyword": keyword, "error": error})
            logging.warning("%s：%s", keyword, error)
        else:
            observed_this_run += len(posts)
            for post in posts:
                key = post.get("code") or post.get("url")
                if key not in merged:
                    merged[key] = post
                    newly_added_this_run += 1
                else:
                    # 同一貼文可能被不同詞命中，保留最初發現資料並合併關鍵字
                    old = merged[key]
                    kws = set(old.get("matched_keywords", [old.get("keyword", "")]))
                    kws.add(keyword)
                    old["matched_keywords"] = sorted(k for k in kws if k)
        if index < len(keywords) - 1:
            time.sleep(DELAY_BETWEEN_REQUESTS)

    posts = list(merged.values())
    posts.sort(key=lambda p: p.get("discovered_at", ""), reverse=True)
    posts = posts[:MAX_STORED_POSTS]

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "source": "Threads public search page; best-effort sample only",
        "keywords": keywords,
        "posts_observed_this_run": observed_this_run,
        "new_posts_added_this_run": newly_added_this_run,
        "errors": errors,
        "posts": posts,
    }
    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_FILE.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    logging.info("本輪觀察到 %s 筆，其中新加入 %s 筆；目前保存 %s 筆；錯誤 %s 項。", observed_this_run, newly_added_this_run, len(posts), len(errors))


if __name__ == "__main__":
    main()
