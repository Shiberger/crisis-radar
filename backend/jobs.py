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
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.classify import archive, lexicon, overrides   # noqa: E402
from src.classify.pipeline import HybridClassifier    # noqa: E402
from src.crisis import detector                        # noqa: E402
from src.models import Classified                      # noqa: E402
from src.sources.sample import SampleFacebookSource   # noqa: E402
from src.timeutil import now_ict                       # noqa: E402

DEFAULT_FIXTURE = ROOT / "data" / "sample_talesrunner_fb_comments.json"
TARGETS_FILE = ROOT / "data" / "targets.json"

JOBS: dict[str, dict] = {}
_LOCK = threading.Lock()
_FILE_LOCK = threading.Lock()   # กันเขียน data/facebook_live_*.json ทับกันตอน monitor + manual ชนกัน


def _update(job_id: str, **kw) -> None:
    with _LOCK:
        JOBS[job_id].update(kw)


def _log(job_id: str, msg: str) -> None:
    with _LOCK:
        JOBS[job_id]["logs"].append(f"{now_ict():%H:%M:%S}  {msg}")


def get_job(job_id: str) -> dict | None:
    with _LOCK:
        j = JOBS.get(job_id)
        return dict(j) if j else None


def set_job_result(job_id: str, result: dict) -> bool:
    """เขียนผลที่คิดใหม่ทับงานเดิม (ใช้ตอนทีมแก้ label แล้วรายงานต้องเปลี่ยนตาม)."""
    with _LOCK:
        if job_id not in JOBS:
            return False
        JOBS[job_id]["result"] = result
    return True


def start_job(params: dict) -> str:
    job_id = uuid.uuid4().hex[:8]
    with _LOCK:
        JOBS[job_id] = {"status": "queued", "logs": [], "result": None, "error": None}
    threading.Thread(target=_run, args=(job_id, params), daemon=True).start()
    return job_id


def get_targets() -> dict:
    """ค่าตั้งต้นสำหรับฟอร์มหน้าเว็บ — URL เพจ/โพสต์ที่ตั้งไว้ใน data/targets.json."""
    try:
        cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"page_url": "", "post_urls": []}
    page = next((t for t in cfg.get("targets", []) if t.get("type") == "page"), None)
    return {"page_name": cfg.get("page_name", ""),
            "page_url": (page or {}).get("url", ""),
            "post_urls": cfg.get("post_urls", [])}


def _clean_fb_urls(raw) -> list[str]:
    """กรอง URL ที่ผู้ใช้พิมพ์บนหน้าเว็บ — รับเฉพาะ facebook.com/fb.com เท่านั้น.

    กันไม่ให้ endpoint ถูกใช้ยิง Apify ไปที่เว็บอื่น (เปลืองเครดิตเจ้าของ token).
    """
    ok = []
    for u in raw if isinstance(raw, list) else []:
        u = str(u).strip()
        if not u.startswith(("http://", "https://")):
            continue
        host = u.split("/", 3)[2].lower().split(":")[0]
        if host == "fb.com" or host.endswith(("facebook.com", ".fb.com")):
            ok.append(u)
    return ok


def _fetch_facebook(params: dict, log=print):
    """ดึง Facebook จริงผ่าน Apify → เขียน live file → คืน comments (masked).

    log: callback รับ str — manual job ส่งเข้า JOBS[...]['logs'], monitor ส่งเข้า log ของตัวเอง
    """
    from src.sources.facebook_apify import ApifyFacebookScraper

    cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    only = params.get("only", "page")
    targets = [t for t in cfg["targets"] if only == "all" or t["type"] == only]

    # ถ้าผู้ใช้พิมพ์ URL เพจเองบนหน้าเว็บ → ใช้อันนั้นแทนที่ตั้งไว้ใน targets.json
    # พิมพ์มาแล้วแต่ใช้ไม่ได้ → ฟ้องเลย ไม่เงียบ ๆ ไปใช้ค่า default (ผู้ใช้จะเข้าใจผิดว่าดึงเพจที่ตัวเองใส่)
    raw_page = str(params.get("page_url") or "").strip()
    custom_page = _clean_fb_urls([raw_page])
    if raw_page and not custom_page:
        raise ValueError(f"URL เพจไม่ถูกต้อง (ต้องเป็นลิงก์ facebook.com): {raw_page}")
    if custom_page:
        targets = [{"type": "page", "name": custom_page[0], "url": custom_page[0]}]

    cookies = None
    cpath = os.environ.get("FB_COOKIES_JSON")
    if cpath and Path(cpath).exists():
        cookies = json.loads(Path(cpath).read_text(encoding="utf-8"))

    scraper = ApifyFacebookScraper(cookies=cookies)   # raise ถ้าไม่มี token/lib
    comments: list[dict] = []
    max_comments = int(params.get("max_comments", 30))
    max_posts = int(params.get("max_posts", 10))

    # scope = 'page' → กวาดทั้งเพจ: Posts Scraper หาโพสต์ล่าสุด N โพสต์ → Comments Scraper ทีละโพสต์
    #         'urls' → เจาะเฉพาะโพสต์ที่ระบุ (actor เดียว ถูกกว่า/เร็วกว่า)
    # URL เอาจากที่ผู้ใช้พิมพ์บนหน้าเว็บก่อน ถ้าไม่พิมพ์ค่อย fallback ไป targets.json
    scope = params.get("scope", "page")
    raw_posts = [u for u in (params.get("post_urls") or []) if str(u).strip()]
    user_posts = _clean_fb_urls(raw_posts)
    if raw_posts and not user_posts:
        raise ValueError("URL โพสต์ที่ใส่มาใช้ไม่ได้เลย — ต้องเป็นลิงก์ facebook.com")
    post_urls = user_posts or _clean_fb_urls(cfg.get("post_urls"))

    if scope == "urls" and post_urls:
        log(f"เจาะ {len(post_urls)} โพสต์ที่ระบุ (Comments Scraper)")
        comments = scraper.scrape_post_urls(post_urls, max_comments, log=log)
    else:
        if scope == "urls":
            log("ไม่มี URL โพสต์ที่ใช้ได้ (ต้องเป็นลิงก์ facebook.com) — สลับไปโหมดทั้งเพจให้")
        for t in targets:
            if t["type"] == "group" and not scraper.cookies:
                log(f"ข้าม {t['name']} — กลุ่ม private ต้องมี cookie")
                continue
            log(f"กวาดทั้งเพจ {t['name']} — โพสต์ล่าสุด {max_posts} โพสต์ …")
            comments += scraper.scrape_target(t, max_posts, max_comments, log=log)

    from src.sources.facebook_apify import filter_noise
    comments, dropped = filter_noise(comments, cfg.get("page_id", ""), cfg.get("exclude_authors"))
    if dropped:
        log(f"กรอง admin/โฆษณา (เช่น IDRLAB) ออก {dropped} รายการ")

    live = {"page": cfg.get("page_name"), "page_id": cfg.get("page_id"),
            "brand": cfg["brand"], "comments": comments}
    live_path = ROOT / "data" / f"facebook_live_{cfg['brand']}.json"
    # monitor กับ manual job อาจดึงพร้อมกัน → กันเขียนไฟล์ทับกันกลางคัน
    with _FILE_LOCK:
        live_path.write_text(json.dumps(live, ensure_ascii=False, indent=2), encoding="utf-8")
        return SampleFacebookSource(live_path, brand=cfg["brand"]).fetch()


def run_pipeline(params: dict, log=print) -> dict:
    """ดึง → classify → crisis detect → คืน result dict พร้อมส่งให้หน้าเว็บ.

    ใช้ร่วมกันทั้งงานที่ผู้ใช้กดเอง (jobs) และตัวเฝ้าเพจอัตโนมัติ (monitor)
    ล้มเหลว = raise ให้ผู้เรียกตัดสินใจเอง (manual job โชว์ error, monitor เก็บผลเดิมไว้ก่อน)
    """
    source = params.get("source", "sample")

    if source == "sample":
        log("โหลดข้อมูลตัวอย่าง (demo)…")
        comments = SampleFacebookSource(DEFAULT_FIXTURE).fetch()
    else:
        log("เชื่อม Apify ดึง Facebook จริง… (อาจใช้เวลาหลายนาที)")
        comments = _fetch_facebook(params, log)

    log(f"ได้ {len(comments)} คอมเมนต์")
    if not comments:
        raise RuntimeError("ไม่มีคอมเมนต์ — เช็ก APIFY_TOKEN / cookie / เป้าหมาย")

    # คอมเมนต์ที่ทีมกด "อ่านแล้ว" ไปแล้วไม่ต้องส่งเข้า AI ซ้ำ — ใช้ label เดิมที่เก็บไว้
    # (จุดที่ประหยัด token จริง · ไม่ได้ลดค่า Apify เพราะจ่ายไปแล้วตอนดึง)
    fresh, known = archive.partition(comments)
    if known:
        log(f"ข้าม {len(known)} คอมเมนต์ที่ทีมอ่านแล้ว — ไม่เรียก AI ซ้ำ")

    log(f"จัด sentiment + topic ด้วย AI ({len(fresh)} คอมเมนต์ใหม่)…")
    classified = HybridClassifier().classify_all(fresh) + archive.rehydrate(known)
    esc = sum(1 for c in classified if c.escalated_to_llm and not c.archived)
    log(f"วิเคราะห์เสร็จ · ส่งต่อ LLM {esc} เคส")

    # คำตัดสินของคนทับ AI ก่อนตรวจ crisis เสมอ — คอมเมนต์ที่ทีมเคยแก้ไว้ต้องไม่ถูกนับผิดซ้ำ
    fixed = overrides.apply(classified)
    if fixed:
        log(f"ใช้คำตัดสินที่ทีมแก้เอง {fixed} คอมเมนต์")
    archive.sync(classified)

    log("ตรวจจับ crisis (spike detection)…")
    result = build_result(classified, source=source)
    log(f"เสร็จ — สถานะ {result['status']} · alert {len(result['alerts'])} รายการ")
    return result


def build_result(items: list[Classified], source: str, generated_at: str = "") -> dict:
    """ตรวจ crisis จาก label ปัจจุบัน แล้วประกอบก้อนผลที่หน้าเว็บใช้.

    แยกออกมาเพราะถูกเรียก 2 ทาง: หลัง scrape รอบใหม่ · และตอนทีมแก้ label/กดอ่านแล้ว
    generated_at: เวลาที่ "ข้อมูลถูกดึงมา" — ตอนคิดใหม่ต้องส่งค่าเดิมมา ไม่ใช่เวลาที่กดแก้

    คอมเมนต์ในคลัง (archived) ยังถูกส่งไปหน้าเว็บครบเพื่อให้เปิดดูย้อนหลังได้
    แต่ **ไม่ถูกนับ** ในสถานะ/สถิติ/spike — ถือว่าทีมจัดการไปแล้ว
    """
    active = [c for c in items if not c.archived]
    brand = active[0].comment.brand if active else "talesrunner"
    rep = detector.detect(active, brand=brand or "talesrunner")

    result = detector.report_to_dict(rep)
    # ส่งคอมเมนต์ครบทุกอัน (พร้อมชื่อ/ลิงก์/รายละเอียด) ให้หน้าเว็บทำตารางกรอง/ค้นหาเอง
    result["comments"] = [c.to_dict() for c in items]
    reaches = [c.comment.reach for c in active]
    result["unique_authors"] = len({c.comment.author for c in active})
    result["avg_reach"] = round(sum(reaches) / len(reaches), 1) if reaches else 0
    result["max_reach"] = max(reaches) if reaches else 0
    result["generated_at"] = generated_at or (now_ict().strftime("%Y-%m-%d %H:%M") + " น.")
    result["source"] = source
    result["topic_labels"] = lexicon.TOPIC_LABELS   # ให้หน้าเว็บแสดงชื่อประเด็นเป็นไทย
    result["override_count"] = sum(1 for c in active if c.overridden)
    result["archived_count"] = len(items) - len(active)
    return result


def recompute(result: dict) -> dict:
    """คิดรายงานใหม่จากคอมเมนต์ชุดเดิม + override/คลังล่าสุด — ไม่ scrape ซ้ำ ไม่เสียเครดิต."""
    items = [Classified.from_dict(c) for c in (result.get("comments") or [])]
    # คืนค่า AI ก่อน แล้วค่อยทาบ override ล่าสุดจากไฟล์ — ไม่งั้นคนกด "คืนค่าที่ AI ทาย"
    # แล้วค่าเดิมของ AI จะไม่กลับมา (โดยเฉพาะกรณี AI ไม่ได้จัดประเด็นไว้เลย = ลิสต์ว่าง)
    for it in items:
        if it.overridden:
            it.sentiment = it.ai_sentiment or it.sentiment
            it.topics = list(it.ai_topics)
            it.overridden = False
            it.ai_sentiment, it.ai_topics = "", []
    overrides.apply(items)
    archive.apply(items)
    archive.sync(items)
    return build_result(items, source=result.get("source", "sample"),
                        generated_at=result.get("generated_at", ""))


def _run(job_id: str, params: dict) -> None:
    try:
        _update(job_id, status="running")
        result = run_pipeline(params, log=lambda m: _log(job_id, m))
        _update(job_id, status="done", result=result)
    except Exception as e:  # noqa: BLE001
        _update(job_id, status="error", error=str(e))
        _log(job_id, f"ERROR: {e}")
