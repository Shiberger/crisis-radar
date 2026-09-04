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
from datetime import timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.classify import archive, lexicon, overrides   # noqa: E402
from src.classify.pipeline import HybridClassifier    # noqa: E402
from src.crisis import detector                        # noqa: E402
from src.models import Classified                      # noqa: E402
from src import notify                                 # noqa: E402
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


def page_presets(cfg: dict) -> list[dict]:
    """เพจที่ทีมดูแลอยู่ จัดกลุ่มตามค่าย — หน้าเว็บเอาไปทำตัวเลือกติ๊กได้ (เลือกหลายเพจ).

    ทำไมอยู่ใน targets.json ไม่ใช่ในโค้ด: รายชื่อเพจเป็นของทีม ไม่ใช่ของระบบ — เพิ่มเพจใหม่
    ควรเป็นการแก้ไฟล์ config บรรทัดเดียว ไม่ใช่แก้ JS แล้ว deploy ใหม่
    กรอง URL ที่ไม่ใช่ facebook ทิ้งตั้งแต่ตรงนี้ เพื่อไม่ให้ปุ่มบนหน้าเว็บพาไปยิง Apify ผิดที่
    """
    out = []
    for g in cfg.get("page_presets") or []:
        pages = [{"name": str(pg.get("name") or pg.get("url", "")).strip(), "url": u}
                 for pg in (g.get("pages") or [])
                 for u in _clean_fb_urls([pg.get("url", "")])]
        if pages:
            out.append({"group": str(g.get("group") or "อื่น ๆ"), "pages": pages})
    return out


def monitor_page_urls(cfg: dict | None = None) -> list[str]:
    """เพจที่ตัวเฝ้าอัตโนมัติต้องตรวจทุกรอบ — env ทับไฟล์ได้ (เปลี่ยนบน Render โดยไม่ต้อง deploy).

    ว่างทั้งคู่ = คืน [] แล้วให้ผู้เรียก fallback ไปเพจแรกใน targets[] เหมือนพฤติกรรมเดิม
    """
    if cfg is None:
        try:
            cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            cfg = {}
    raw = os.environ.get("MONITOR_PAGE_URLS", "").strip()
    urls = ([u for u in raw.replace(",", "\n").split("\n")] if raw
            else list(cfg.get("monitor_pages") or []))
    return _dedup_urls(_clean_fb_urls([str(u).strip() for u in urls]))[:MAX_PAGES]


def get_targets() -> dict:
    """ค่าตั้งต้นสำหรับฟอร์มหน้าเว็บ — URL เพจ/โพสต์ + รายชื่อเพจที่ติ๊กเลือกได้."""
    try:
        cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"page_url": "", "post_urls": [], "page_presets": [], "monitor_pages": []}
    page = next((t for t in cfg.get("targets", []) if t.get("type") == "page"), None)
    return {"page_name": cfg.get("page_name", ""),
            "page_url": (page or {}).get("url", ""),
            "post_urls": cfg.get("post_urls", []),
            "page_presets": page_presets(cfg),
            "monitor_pages": monitor_page_urls(cfg)}


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


# เพดานเพจต่อรอบ — Apify คิดเงินต่อเพจ (1 posts run + N comments runs) ถ้าไม่จำกัด
# คนวางลิงก์ทีเดียว 50 เพจ = บิลบานโดยไม่ตั้งใจ · ต้องการมากกว่านี้ให้แบ่งหลายรอบ
MAX_PAGES = 10


def _dedup_urls(urls: list[str]) -> list[str]:
    """ตัด URL ซ้ำแบบไม่สนใจ / ปิดท้ายและตัวพิมพ์ — กันจ่าย Apify 2 รอบให้เพจเดียวกัน."""
    seen, out = set(), []
    for u in urls:
        k = u.rstrip("/").lower()
        if k not in seen:
            seen.add(k)
            out.append(u)
    return out


def _since_from(params: dict):
    """days → เวลาตัด (ICT). ไม่ส่งมา/0/ค่าพัง = ไม่จำกัดช่วง (คืน None)."""
    try:
        days = int(params.get("days") or 0)
    except (TypeError, ValueError):
        return None
    if days <= 0:
        return None
    params["days"] = days
    return now_ict() - timedelta(days=days)


def _fetch_facebook(params: dict, log=print):
    """ดึง Facebook จริงผ่าน Apify → เขียน live file → คืน comments (masked).

    log: callback รับ str — manual job ส่งเข้า JOBS[...]['logs'], monitor ส่งเข้า log ของตัวเอง
    """
    from src.sources.facebook_apify import ApifyFacebookScraper

    cfg = json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    only = params.get("only", "page")
    targets = [t for t in cfg["targets"] if only == "all" or t["type"] == only]

    # ถ้าผู้ใช้พิมพ์ URL เพจเองบนหน้าเว็บ → ใช้อันนั้นแทนที่ตั้งไว้ใน targets.json
    # รับได้หลายเพจในรอบเดียว (page_urls) — page_url เดี่ยวยังใช้ได้ เพื่อไม่ให้ของเดิม/n8n พัง
    # พิมพ์มาแล้วแต่ใช้ไม่ได้ → ฟ้องเลย ไม่เงียบ ๆ ไปใช้ค่า default (ผู้ใช้จะเข้าใจผิดว่าดึงเพจที่ตัวเองใส่)
    raw_pages = [str(u).strip() for u in (params.get("page_urls") or []) if str(u).strip()]
    single = str(params.get("page_url") or "").strip()
    if single and single not in raw_pages:
        raw_pages.insert(0, single)
    custom_pages = _dedup_urls(_clean_fb_urls(raw_pages))
    if raw_pages and not custom_pages:
        raise ValueError("URL เพจไม่ถูกต้อง (ต้องเป็นลิงก์ facebook.com): "
                         + ", ".join(raw_pages[:3]))
    if len(custom_pages) > MAX_PAGES:
        raise ValueError(f"ใส่เพจได้มากสุด {MAX_PAGES} เพจต่อรอบ (ใส่มา {len(custom_pages)}) "
                         f"— ค่า Apify คิดต่อเพจ ถ้าต้องการมากกว่านี้ให้แบ่งเป็นหลายรอบ")
    if custom_pages:
        targets = [{"type": "page", "name": u, "url": u} for u in custom_pages]

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
    since = _since_from(params)
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
        if len(targets) > 1:
            log(f"กวาด {len(targets)} เพจในรอบนี้ — ค่า Apify คิดแยกต่อเพจ")
        for t in targets:
            if t["type"] == "group" and not scraper.cookies:
                log(f"ข้าม {t['name']} — กลุ่ม private ต้องมี cookie")
                continue
            window = f" ที่ลงใน {params['days']} วันล่าสุด" if since else ""
            log(f"กวาดทั้งเพจ {t['name']} — โพสต์ล่าสุดไม่เกิน {max_posts} โพสต์{window} …")
            comments += scraper.scrape_target(t, max_posts, max_comments, log=log, since=since)

    from src.sources.facebook_apify import filter_noise
    # แอดมินของทุกเพจที่กวาดรอบนี้ต้องถูกตัด ไม่ใช่แค่เพจหลักใน targets.json — slug ท้าย URL
    # ใช้เป็น page_id ได้ตรง ๆ เพราะ profile_url ของแอดมินเพจมี slug นั้นอยู่ข้างใน
    page_ids = [cfg.get("page_id", "")] + [t["url"].rstrip("/").rsplit("/", 1)[-1].split("?")[0]
                                           for t in targets if t.get("type") == "page"]
    comments, dropped = filter_noise(comments, page_ids, cfg.get("exclude_authors"))
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

    # ตัดตามช่วงเวลาที่ผู้ใช้เลือก — ตัวตัดสินสุดท้ายอยู่ที่ "เวลาของคอมเมนต์" ไม่ใช่เวลาโพสต์
    # (โพสต์เก่าอาทิตย์ที่แล้วอาจมีคนมาคอมเมนต์เมื่อวาน ซึ่งต้องนับ · และโพสต์ที่ actor ไม่ส่ง
    #  เวลามาก็ถูกดึงมาทั้งก้อน ต้องมากรองตรงนี้)
    since = _since_from(params)
    if since:
        before = len(comments)
        comments = [c for c in comments if c.created_at >= since]
        if before != len(comments):
            log(f"เอาเฉพาะช่วง {params['days']} วันล่าสุด — เหลือ {len(comments)} จาก {before} คอมเมนต์")

    log(f"ได้ {len(comments)} คอมเมนต์")
    if not comments:
        if since:
            raise RuntimeError(f"ไม่มีคอมเมนต์ในช่วง {params['days']} วันล่าสุด "
                               f"— ลองขยายช่วงเวลา หรือเช็กว่าเพจมีคนคอมเมนต์อยู่จริง")
        raise RuntimeError("ไม่มีคอมเมนต์ — เช็ก APIFY_TOKEN / cookie / เป้าหมาย")

    # คอมเมนต์ที่ทีมกด "อ่านแล้ว" ไปแล้วไม่ต้องส่งเข้า AI ซ้ำ — ใช้ label เดิมที่เก็บไว้
    # (จุดที่ประหยัด token จริง · ไม่ได้ลดค่า Apify เพราะจ่ายไปแล้วตอนดึง)
    fresh, known = archive.partition(comments)
    if known:
        log(f"ข้าม {len(known)} คอมเมนต์ที่ทีมอ่านแล้ว — ไม่เรียก AI ซ้ำ")

    clf = HybridClassifier(log=log)
    log(f"จัด sentiment + topic ด้วย AI ({len(fresh)} คอมเมนต์ใหม่) · ชั้นที่สอง: {clf.engine}…")
    classified = clf.classify_all(fresh) + archive.rehydrate(known)
    st = clf.stats
    log(f"วิเคราะห์เสร็จ · ชั้นแรกตัดสินเอง {st['total'] - st['gated'] - st['to_llm']} · "
        f"กฎเพิ่มเติม {st['gated']} · ส่งเข้า AI {st['to_llm']} เคส")
    # โชว์ค่าใช้จ่ายจริงต่อรอบ — ตัวเลขนี้คือสิ่งที่ต้องดูตอนตัดสินใจปรับ interval/เพดาน
    if hasattr(clf.llm, "usage_line") and clf.llm.usage["requests"]:
        log(f"ค่าใช้จ่าย AI รอบนี้: {clf.llm.usage_line()}")

    # คำตัดสินของคนทับ AI ก่อนตรวจ crisis เสมอ — คอมเมนต์ที่ทีมเคยแก้ไว้ต้องไม่ถูกนับผิดซ้ำ
    fixed = overrides.apply(classified)
    if fixed:
        log(f"ใช้คำตัดสินที่ทีมแก้เอง {fixed} คอมเมนต์")
    archive.sync(classified)
    notify.apply(classified)     # คอมเมนต์ที่เคยแจ้ง Discord แล้วต้องไม่ถูกแจ้งซ้ำรอบนี้

    log("ตรวจจับ crisis (spike detection)…")
    result = build_result(classified, source=source)

    # เคสที่ "ลบและแรง" ตั้งแต่แรก ไม่ต้องรอให้มีคนเปิดหน้าเว็บมาเห็น — เด้งเข้า Discord เลย
    # (เคสที่ AI อ่านพลาด ทีมกดแจ้งเองได้จากหน้าเว็บ ดู server.py /api/alert)
    if notify.dispatch_auto(classified, result, page=get_targets(), log=log):
        result = build_result(classified, source=source, generated_at=result["generated_at"])

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
    result["alert_sent_count"] = sum(1 for c in active if c.alerted_at)
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
    notify.apply(items)      # ป้าย "แจ้ง Discord แล้ว" ต้องอยู่ครบหลังคิดรายงานใหม่
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
