"""Background job runner สำหรับ Crisis Radar web — รันด้วย stdlib ล้วน (threading).

หน้าที่: รับคำสั่งจากหน้าเว็บ (กดปุ่ม) → ดึงข้อมูล → classify → crisis detect → เก็บผล
หน้าเว็บ poll สถานะได้เรื่อย ๆ จนเสร็จ (queued → running → done/error)

source:
  'sample'   → ข้อมูลตัวอย่าง (demo, ไม่ต้องเน็ต) — ให้ team เห็นตัว tool ทำงานทันที
  'facebook' → ดึงจริงผ่าน Apify (ต้องตั้ง APIFY_TOKEN ฝั่ง server ไว้ก่อน)
"""
from __future__ import annotations

import json
import os
import sys
import threading
import uuid
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.classify.pipeline import HybridClassifier    # noqa: E402
from src.crisis import detector                        # noqa: E402
from src.sources.sample import SampleFacebookSource   # noqa: E402

DEFAULT_FIXTURE = ROOT / "data" / "sample_talesrunner_fb_comments.json"
TARGETS_FILE = ROOT / "data" / "targets.json"

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()


def _update(job_id: str, **kw) -> None:
    with _LOCK:
        JOBS[job_id].update(kw)


def _log(job_id: str, msg: str) -> None:
    with _LOCK:
        JOBS[job_id]["logs"].append(f"{datetime.now():%H:%M:%S}  {msg}")


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        j = JOBS.get(job_id)
        return dict(j) if j else None


def start_job(params: dict) -> str:
    job_id = uuid.uuid4().hex[:8]
    with _LOCK:
        JOBS[job_id] = {"status": "queued", "logs": [], "result": None, "error": None}
    threading.Thread(target=_run, args=(job_id, params), daemon=True).start()
    return job_id


def _fetch_facebook(job_id: str, params: dict):
    """ดึง Facebook จริงผ่าน Apify → เขียน live file → คืน comments (masked)."""
    from src.sources.facebook_apify import ApifyFacebookScraper

    cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    only = params.get("only", "page")
    targets = [t for t in cfg["targets"] if only == "all" or t["type"] == only]

    cookies = None
    cpath = os.environ.get("FB_COOKIES_JSON")
    if cpath and Path(cpath).exists():
        cookies = json.loads(Path(cpath).read_text(encoding="utf-8"))

    scraper = ApifyFacebookScraper(cookies=cookies)   # raise ถ้าไม่มี token/lib
    comments: list[dict] = []

    # ทางแนะนำ: ใช้ post_urls ที่ระบุใน targets.json (Comments Scraper อย่างเดียว, ถูกสุด)
    post_urls = [u for u in cfg.get("post_urls", []) if isinstance(u, str) and u.startswith("http")]
    if post_urls:
        _log(job_id, f"ใช้ post_urls {len(post_urls)} โพสต์ (Comments Scraper)")
        comments = scraper.scrape_post_urls(post_urls, int(params.get("max_comments", 30)))
    else:
        for t in targets:
            if t["type"] == "group" and not scraper.cookies:
                _log(job_id, f"ข้าม {t['name']} — กลุ่ม private ต้องมี cookie")
                continue
            _log(job_id, f"ดึง {t['name']} …")
            comments += scraper.scrape_target(t, int(params.get("max_posts", 10)),
                                              int(params.get("max_comments", 30)))

    from src.sources.facebook_apify import filter_noise
    comments, dropped = filter_noise(comments, cfg.get("page_id", ""), cfg.get("exclude_authors"))
    if dropped:
        _log(job_id, f"กรอง admin/โฆษณา (เช่น IDRLAB) ออก {dropped} รายการ")

    live = {"page": cfg.get("page_name"), "page_id": cfg.get("page_id"),
            "brand": cfg["brand"], "comments": comments}
    live_path = ROOT / "data" / f"facebook_live_{cfg['brand']}.json"
    live_path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
    return SampleFacebookSource(live_path, brand=cfg["brand"]).fetch()


def _run(job_id: str, params: dict) -> None:
    try:
        _update(job_id, status="running")
        source = params.get("source", "sample")

        if source == "sample":
            _log(job_id, "โหลดข้อมูลตัวอย่าง (demo)…")
            comments = SampleFacebookSource(DEFAULT_FIXTURE).fetch()
        else:
            _log(job_id, "เชื่อม Apify ดึง Facebook จริง… (อาจใช้เวลาหลายนาที)")
            comments = _fetch_facebook(job_id, params)

        _log(job_id, f"ได้ {len(comments)} คอมเมนต์")
        if not comments:
            _update(job_id, status="error", error="ไม่มีคอมเมนต์ — เช็ก APIFY_TOKEN / cookie / เป้าหมาย")
            return

        _log(job_id, "จัด sentiment + topic ด้วย AI…")
        classified = HybridClassifier().classify_all(comments)
        esc = sum(1 for c in classified if c.escalated_to_llm)
        _log(job_id, f"วิเคราะห์เสร็จ · ส่งต่อ LLM {esc} เคส")

        _log(job_id, "ตรวจจับ crisis (spike detection)…")
        brand = comments[0].brand or "talesrunner"
        rep = detector.detect(classified, brand=brand)

        result = detector.report_to_dict(rep)
        # ส่งคอมเมนต์ครบทุกอัน (พร้อมชื่อ/ลิงก์/รายละเอียด) ให้หน้าเว็บทำตารางกรอง/ค้นหาเอง
        result["comments"] = [c.to_dict() for c in classified]
        reaches = [c.comment.reach for c in classified]
        result["unique_authors"] = len({c.comment.author for c in classified})
        result["avg_reach"] = round(sum(reaches) / len(reaches), 1) if reaches else 0
        result["max_reach"] = max(reaches) if reaches else 0
        result["generated_at"] = datetime.now().strftime("%Y-%m-%d %H:%M")
        result["source"] = source

        _update(job_id, status="done", result=result)
        _log(job_id, f"เสร็จ — สถานะ {rep.status} · alert {len(rep.alerts)} รายการ")

    except Exception as e:  # noqa: BLE001
        _update(job_id, status="error", error=str(e))
        _log(job_id, f"ERROR: {e}")
