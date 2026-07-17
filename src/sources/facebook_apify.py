"""ดึงคอมเมนต์ Facebook จริงผ่าน Apify actors → แปลงเป็น fixture schema ของ Crisis Radar.

ทำไม Apify (แนะนำเป็น primary):
  - Apify จัดการ login / anti-bot / proxy ให้ → เสถียรกว่าเขียน scraper เอง และทีมเคยใช้มาแล้ว
  - รองรับทั้งเพจ public และกลุ่ม (กลุ่ม private ต้องแนบ cookie ล็อกอินของสมาชิก)

2 ขั้นตอน (เพราะ actor คอมเมนต์รับ "URL โพสต์" ไม่ใช่ URL เพจ):
  1) facebook-posts-scraper : จาก URL เพจ/กลุ่ม → รายการ URL โพสต์ล่าสุด
  2) facebook-comments-scraper : จากแต่ละ URL โพสต์ → คอมเมนต์

ต้องมี:
  APIFY_TOKEN ในไฟล์ .env          # จาก console.apify.com > Settings > Integrations
  (เรียกผ่าน REST API ด้วย urllib — ไม่ต้องลง apify-client)
  (กลุ่ม private) FB_COOKIES_JSON=path/to/cookies.json  # export cookie ตอนล็อกอินแล้ว

หมายเหตุ field mapping: ชื่อ field ของ output แต่ละ actor/เวอร์ชันอาจต่างกันเล็กน้อย
→ ตัว map เขียนแบบ defensive (ลอง key หลายชื่อ). ถ้าเจอ field ใหม่ ใช้ scrape_facebook.py --inspect
  ดู raw item แล้วเพิ่ม key ใน _pick() ได้.
"""
from __future__ import annotations

import hashlib
import os
from datetime import datetime, timezone
from typing import Any, Optional

POSTS_ACTOR = "apify/facebook-posts-scraper"
COMMENTS_ACTOR = "apify/facebook-comments-scraper"


def _ssl_context():
    """หา CA bundle ให้เจอเอง (python.org build บน mac มักหา cert ไม่เจอ).

    ยัง verify cert ตามปกติ (ไม่ปิด verification) — ปลอดภัยเวลาส่ง token.
    """
    import ssl
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for p in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/usr/local/etc/openssl@3/cert.pem"):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


def _pick(item: dict, *keys, default=None):
    """คืนค่าแรกที่เจอจากหลายชื่อ key (รองรับ actor เวอร์ชันต่างกัน)."""
    for k in keys:
        if k in item and item[k] not in (None, ""):
            return item[k]
    return default


def _parse_date(val: Any) -> str:
    """คืน ISO string. รับ ISO/epoch/รูปแบบทั่วไป, ไม่รู้จัก → เวลาปัจจุบัน."""
    if val is None:
        return datetime.now().isoformat()
    if isinstance(val, (int, float)):
        return datetime.fromtimestamp(val, tz=timezone.utc).isoformat()
    s = str(val)
    for fmt in (None, "%Y-%m-%dT%H:%M:%S.%fZ", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return (datetime.fromisoformat(s.replace("Z", "+00:00")) if fmt is None
                    else datetime.strptime(s, fmt)).isoformat()
        except (ValueError, TypeError):
            continue
    return datetime.now().isoformat()


def _comment_id(item: dict, post_id: str) -> str:
    cid = _pick(item, "id", "commentId", "commentUrl", "url")
    if cid:
        return str(cid)
    raw = (post_id + _pick(item, "text", "message", default="")).encode("utf-8")
    return "c_" + hashlib.sha1(raw).hexdigest()[:10]


def map_comment_item(it: dict, post_id: str) -> dict:
    """แปลง 1 item จาก Facebook Comments Scraper → fixture schema (ใช้ร่วมทั้ง live + import)."""
    return {
        "comment_id": _comment_id(it, post_id),
        "post_id": post_id,
        "author": _pick(it, "profileName", "name", "authorName", "profile", default="unknown"),
        "text": _pick(it, "text", "message", "commentText", default=""),
        "created_at": _parse_date(_pick(it, "date", "createdTime", "time", "timestamp")),
        "reach": int(_pick(it, "likesCount", "likes", "reactionsCount", default=0) or 0)
                 + int(_pick(it, "repliesCount", "commentsCount", default=0) or 0),
        "comment_url": _pick(it, "commentUrl", "url", default=""),
        "profile_url": _pick(it, "profileUrl", default=""),
        "post_title": _pick(it, "postTitle", default=""),
    }


import re as _re

_PHONE = _re.compile(r"0\d[\d\-\s]{7,}")
_LINE_HANDLE = _re.compile(r"@[A-Za-z0-9_.]{3,}")
_PROMO_WORDS = (
    "ยินดีให้คำปรึกษา", "ติดต่อเรา", "พร้อมดูแล", "สนใจทัก", "โปรโมชั่น", "ปรึกษาฟรี",
    "สอบถามเพิ่มเติม", "ทักแชท", "inbox", "กู้ข้อมูล", "รับซ่อม", "จำหน่าย", "บริการ", "line :",
)


def looks_promotional(text: str) -> bool:
    """โฆษณา/บริการ (เช่น IDRLAB กู้ข้อมูล) — ไม่ใช่เสียงผู้เล่น จึงกรองออก."""
    t = text.lower()
    has_line = bool(_LINE_HANDLE.search(text))
    has_phone = bool(_PHONE.search(text))
    has_promo = any(w in t for w in _PROMO_WORDS)
    return (has_promo and (has_line or has_phone)) or (has_line and has_phone)


def filter_noise(comments: list[dict], page_id: str = "", exclude_authors=None):
    """คัดคอมเมนต์ที่ไม่ใช่เสียงผู้เล่นออก: ของเพจเอง / รายชื่อ block / โฆษณา.

    คืน (kept, dropped_count).
    """
    excl = [e.lower() for e in (exclude_authors or [])]
    kept, dropped = [], 0
    for c in comments:
        author = str(c.get("author", "")).lower()
        purl = str(c.get("profile_url", "")).lower()
        is_page = bool(page_id) and page_id.lower() in purl
        is_blocked = any(e in author for e in excl)
        if is_page or is_blocked or looks_promotional(c.get("text", "")):
            dropped += 1
            continue
        kept.append(c)
    return kept, dropped


def load_apify_export(path, brand: str = "talesrunner", page_id: str = "thehof.talesrunner",
                      exclude_authors=None) -> dict:
    """อ่านไฟล์ JSON ที่ Download มาจาก Apify Console (Comments Scraper) → fixture schema.

    ทางลัดที่ไม่ต้องต่อ token: กด Start ใน Apify UI เอง → Download JSON → ไฟล์นั้นเข้าที่นี่.
    """
    import json
    from pathlib import Path
    items = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(items, dict):
        items = items.get("items") or items.get("results") or [items]

    comments = [map_comment_item(it, _pick(it, "postUrl", "facebookUrl", default="import"))
                for it in items]
    comments = [c for c in comments if c["text"].strip()]
    kept, dropped = filter_noise(comments, page_id, exclude_authors)
    if dropped:
        print(f"  [import] กรอง admin/โฆษณา/เพจ ออก {dropped} รายการ")
    return {"page": brand.title(), "page_id": page_id, "brand": brand, "comments": kept}


class ApifyFacebookScraper:
    platform = "facebook"
    API = "https://api.apify.com/v2"

    def __init__(self, token: Optional[str] = None, cookies: Optional[list] = None):
        self.token = token or os.environ.get("APIFY_TOKEN")
        if not self.token:
            raise RuntimeError("ไม่พบ APIFY_TOKEN — ใส่ในไฟล์ .env (ดู .env.example)")
        self.cookies = cookies   # สำหรับกลุ่ม private

    def check_token(self) -> str:
        """เช็กว่า token ใช้ได้จริง (ไม่เสียเงิน) — คืน username. raise ถ้า token ผิด."""
        import json as _json
        import urllib.request
        req = urllib.request.Request(f"{self.API}/users/me",
                                     headers={"Authorization": f"Bearer {self.token}"})
        with urllib.request.urlopen(req, timeout=15, context=_ssl_context()) as r:
            return _json.loads(r.read()).get("data", {}).get("username", "?")

    def _run(self, actor: str, run_input: dict) -> list[dict]:
        """เรียก actor ผ่าน REST (run-sync-get-dataset-items) — stdlib urllib ล้วน."""
        import json as _json
        import urllib.error
        import urllib.request
        url = f"{self.API}/acts/{actor.replace('/', '~')}/run-sync-get-dataset-items"
        req = urllib.request.Request(
            url, data=_json.dumps(run_input).encode("utf-8"), method="POST",
            headers={"Content-Type": "application/json", "Authorization": f"Bearer {self.token}"})
        try:
            with urllib.request.urlopen(req, timeout=300, context=_ssl_context()) as r:
                return _json.loads(r.read())
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"Apify API error {e.code}: {e.read().decode('utf-8', 'ignore')[:300]}") from e

    def get_post_urls(self, target_url: str, max_posts: int) -> list[str]:
        run_input: dict = {"startUrls": [{"url": target_url}], "resultsLimit": max_posts}
        if self.cookies:
            run_input["cookies"] = self.cookies      # กลุ่ม private ต้องใช้
        items = self._run(POSTS_ACTOR, run_input)
        urls = [_pick(it, "url", "postUrl", "facebookUrl") for it in items]
        return [u for u in urls if u]

    def get_comments(self, post_url: str, post_id: str, max_comments: int) -> list[dict]:
        # input ขั้นต่ำ (ตรงกับฟอร์ม: Facebook URLs = startUrls, Results amount = resultsLimit)
        run_input: dict = {"startUrls": [{"url": post_url}], "resultsLimit": max_comments}
        if self.cookies:
            run_input["cookies"] = self.cookies
        out = [map_comment_item(it, post_id) for it in self._run(COMMENTS_ACTOR, run_input)]
        return [c for c in out if c["text"].strip()]

    def scrape_post_urls(self, post_urls: list[str], max_comments: int) -> list[dict]:
        """ทางที่แนะนำ: ป้อน URL โพสต์ตรง ๆ (ก็อปจากเพจเอง) → ดึงคอมเมนต์ actor เดียว ถูกสุด."""
        comments: list[dict] = []
        for i, url in enumerate(post_urls, 1):
            cs = self.get_comments(url, f"post_{i}", max_comments)
            comments += cs
            print(f"    - โพสต์ {i}/{len(post_urls)}: {len(cs)} คอมเมนต์")
        return comments

    def scrape_target(self, target: dict, max_posts: int, max_comments: int) -> list[dict]:
        print(f"  [apify] {target['type']}: {target['name']} — หาโพสต์…")
        post_urls = self.get_post_urls(target["url"], max_posts)
        print(f"  [apify] เจอ {len(post_urls)} โพสต์ → ดึงคอมเมนต์…")
        comments: list[dict] = []
        for i, url in enumerate(post_urls, 1):
            pid = f"{target['type']}_{i}"
            cs = self.get_comments(url, pid, max_comments)
            comments += cs
            print(f"    - โพสต์ {i}/{len(post_urls)}: {len(cs)} คอมเมนต์")
        return comments
