"""Monitor mode — เฝ้าเพจที่ตั้งไว้ให้เอง ไม่ต้องกดปุ่ม/เลือกโพสต์เอง.

แนวคิด: หน้าเว็บไม่ควรเป็น "ฟอร์มที่รอคนกด" แต่ควรเป็น "จอสถานะ" ที่เปิดมาแล้วรู้เลยว่า
ตอนนี้เพจมีดราม่าไหม → เก็บผลตรวจล่าสุดไว้ 1 ชุด (snapshot) แล้วตรวจใหม่ให้เองเมื่อผลเก่าเกินรอบ

ทริกเกอร์ตรวจใหม่ 2 ทาง:
  1) มีคนเปิดหน้าเว็บ (lazy)  — ค่าเริ่มต้น: ไม่มีคนดู = ไม่เสียเครดิต Apify และรอดบน Render free tier
                                ที่ container หลับหลังไม่มีคนใช้ 15 นาที (thread ตายไปด้วย)
  2) ตั้ง MONITOR_ALWAYS=1     — มี thread เดินตรวจตามรอบตลอดเวลา (สำหรับ server ที่ไม่หลับ)

**กันเครดิตบาน:** ตรวจใหม่ได้อย่างมาก 1 รอบต่อ interval ไม่ว่าจะมีคนเปิดเว็บพร้อมกันกี่คน
และถ้ารอบล่าสุด error จะพักก่อน (ERROR_COOLDOWN) ไม่รีทรายรัว ๆ

ตั้งค่าผ่าน env (ดู .env.example):
  MONITOR=off                 ปิด monitor ทั้งหมด → หน้าเว็บกลับไปเป็นแบบกดเอง
  MONITOR_SOURCE=facebook|sample   ค่าเริ่มต้น: facebook ถ้ามี APIFY_TOKEN ไม่งั้น sample
  MONITOR_INTERVAL_MIN=120    ตรวจใหม่ทุกกี่นาที (ค่าเริ่มต้น 2 ชม. — คุมค่า Apify/AI)
  MONITOR_MAX_POSTS=5         ต่อรอบ ดูย้อนหลังกี่โพสต์ (เพดานคุมค่าใช้จ่าย)
  MONITOR_MAX_COMMENTS=30     ต่อโพสต์ อ่านกี่คอมเมนต์
  MONITOR_DAYS=7              เอาเฉพาะคอมเมนต์ใน N วันล่าสุด (0 = ไม่จำกัด)
                              ช่วยทั้งคุมค่าใช้จ่าย (ข้ามโพสต์เก่า) และให้หน้าจอเป็นข้อมูลสด
  MONITOR_ALWAYS=1            ตรวจตามรอบแม้ไม่มีคนเปิดเว็บ
  MONITOR_PAGE_URLS           เฝ้าหลายเพจในรอบเดียว (คั่นด้วย , หรือขึ้นบรรทัดใหม่ · สูงสุด 10)
                              ไม่ตั้ง = ใช้ monitor_pages ใน data/targets.json
                              **ค่า Apify คิดแยกต่อเพจต่อรอบ** — เฝ้า 3 เพจ = จ่าย 3 เท่า
"""
from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import jobs                                  # noqa: E402  (อยู่โฟลเดอร์เดียวกัน)
from src import state                        # noqa: E402
from src.timeutil import now_ict             # noqa: E402

STATE_FILE = ROOT / "data" / "monitor_latest.json"
HISTORY_FILE = ROOT / "data" / "monitor_history.json"
HISTORY_MAX = 120           # เก็บผลตรวจย้อนหลังพอให้เห็นแนวโน้ม ~5 วันที่ interval 1 ชม.
ERROR_COOLDOWN = 300        # ดึงพลาด → พัก 5 นาทีก่อนลองใหม่ (กันยิง Apify รัวตอน token เสีย)
LOG_MAX = 60

_LOCK = threading.Lock()
_STATE: dict = {
    "result": None,         # ผลตรวจเต็ม (ก้อนเดียวกับที่ manual job คืน)
    "updated_ts": 0.0,      # epoch ตอนตรวจสำเร็จล่าสุด
    "updated_at": "",       # ข้อความเวลาไทยสำหรับโชว์
    "refreshing": False,
    "started_ts": 0.0,
    "logs": [],
    "error": None,          # error ของรอบล่าสุด (ผลเก่ายังโชว์อยู่)
    "error_ts": 0.0,
    "history": [],
}


def _truthy(v: str) -> bool:
    return str(v).strip().lower() in ("1", "true", "on", "yes")


def _int_env(key: str, default: int) -> int:
    try:
        return int(str(os.environ.get(key, "")).strip() or default)
    except ValueError:
        return default


def config() -> dict:
    """อ่าน env ทุกครั้งที่เรียก — เปลี่ยนค่าแล้วไม่ต้อง restart ตอน dev/test."""
    enabled = not (os.environ.get("MONITOR", "").strip().lower() in ("off", "0", "false", "no"))

    source = os.environ.get("MONITOR_SOURCE", "").strip().lower()
    if source not in ("sample", "facebook"):
        source = "facebook" if os.environ.get("APIFY_TOKEN") else "sample"

    # floor กันตั้งถี่เกินจนยิง Apify ทุกครั้งที่มีคนกด F5
    floor = 15 if source == "facebook" else 1
    interval = max(_int_env("MONITOR_INTERVAL_MIN", 120), floor)

    t = jobs.get_targets()
    # เฝ้าได้หลายเพจในรอบเดียว (data/targets.json → monitor_pages หรือ env MONITOR_PAGE_URLS)
    # ไม่ตั้งไว้ = เพจเดียวตามเดิม — ของเก่าที่ตั้งค่าไว้แล้วจึงไม่เปลี่ยนพฤติกรรม
    pages = list(t.get("monitor_pages") or [])
    if not pages and t.get("page_url"):
        pages = [t["page_url"]]
    labels = [jobs.page_label([u]) for u in pages]
    return {
        "enabled": enabled,
        "source": source,
        "interval_min": interval,
        "max_posts": _int_env("MONITOR_MAX_POSTS", 5),
        "max_comments": _int_env("MONITOR_MAX_COMMENTS", 30),
        "days": max(0, _int_env("MONITOR_DAYS", 0)),
        "always": _truthy(os.environ.get("MONITOR_ALWAYS", "")),
        # page_name = ชื่อที่เอาไปโชว์ได้ทีละค่า — jobs.page_label ตัดสินให้ (เพจเดียว/หลายเพจ)
        "page_name": jobs.page_label(pages) or t.get("page_name", ""),
        "page_url": pages[0] if pages else t.get("page_url", ""),
        "page_urls": pages,
        "page_labels": labels,
    }


# ───────────────────────── persistence ─────────────────────────
# เก็บไว้นอก process เพื่อให้ restart server แล้วยังมีผลล่าสุดโชว์ทันที (ไม่ต้องรอตรวจรอบใหม่)
# ปลายทางจริงเป็นไฟล์หรือ Supabase แล้วแต่ env — src/state.py ตัดสินให้ (บน Render ต้องเป็น
# Supabase ไม่งั้น container restart ทีเดียวผลตรวจล่าสุด + ประวัติแนวโน้มหายหมด)

def _load() -> None:
    saved = state.read_json(STATE_FILE, default=None)
    if isinstance(saved, dict):
        try:
            updated_ts = float(saved.get("updated_ts") or 0)
        except (TypeError, ValueError):
            updated_ts = 0.0
        with _LOCK:
            _STATE["result"] = saved.get("result")
            _STATE["updated_ts"] = updated_ts
            _STATE["updated_at"] = saved.get("updated_at", "")
    hist = state.read_json(HISTORY_FILE, default=None)
    if isinstance(hist, list):
        with _LOCK:
            _STATE["history"] = hist[-HISTORY_MAX:]


def _save() -> None:
    with _LOCK:
        payload = {"result": _STATE["result"], "updated_ts": _STATE["updated_ts"],
                   "updated_at": _STATE["updated_at"]}
        history = list(_STATE["history"])
    # เขียนไม่ลง (ดิสก์ read-only / Supabase ล่ม) → ยังทำงานต่อได้ด้วย state ใน memory
    state.write_json(STATE_FILE, payload)
    state.write_json(HISTORY_FILE, history, indent=1)


def _log(msg: str) -> None:
    with _LOCK:
        _STATE["logs"].append(f"{now_ict():%H:%M:%S}  {msg}")
        del _STATE["logs"][:-LOG_MAX]


# ───────────────────────── refresh ─────────────────────────

def _due(cfg: dict, now: float) -> bool:
    """ถึงเวลาตรวจใหม่หรือยัง (ยังไม่เคยตรวจ = ถึงเวลา)."""
    with _LOCK:
        updated, err_ts = _STATE["updated_ts"], _STATE["error_ts"]
    if err_ts and now - err_ts < ERROR_COOLDOWN:
        return False
    return not updated or (now - updated) >= cfg["interval_min"] * 60


def request_refresh(force: bool = False) -> bool:
    """สั่งตรวจใหม่ถ้าถึงรอบ (หรือ force). คืน True ถ้าเริ่มรอบใหม่จริง.

    ปลอดภัยต่อการเรียกถี่ ๆ — ทุก request ที่เข้ามาเรียกได้ แต่จะเริ่มงานจริงแค่รอบละครั้ง
    """
    cfg = config()
    if not cfg["enabled"]:
        return False
    now = time.time()
    with _LOCK:
        if _STATE["refreshing"]:
            return False
    if not force and not _due(cfg, now):
        return False
    with _LOCK:
        if _STATE["refreshing"]:      # เช็กซ้ำใต้ lock — กัน 2 request เข้าพร้อมกัน
            return False
        _STATE.update(refreshing=True, started_ts=now, logs=[], error=None)
    threading.Thread(target=_worker, args=(cfg,), daemon=True).start()
    return True


def _worker(cfg: dict) -> None:
    try:
        _log(f"เริ่มตรวจอัตโนมัติ — {cfg['page_name'] or 'เพจที่ตั้งไว้'}")
        result = jobs.run_pipeline({
            "source": cfg["source"], "only": "page", "scope": "page",
            "page_urls": cfg["page_urls"],
            "max_posts": cfg["max_posts"], "max_comments": cfg["max_comments"],
            "days": cfg["days"],
        }, log=_log)
        rec = {"at": now_ict().isoformat(timespec="minutes"),
               "status": result.get("status", "NORMAL"),
               "total": result.get("total", 0),
               "negative": (result.get("sentiment_mix") or {}).get("negative", 0),
               "alerts": len(result.get("alert_items") or result.get("alerts") or []),
               "source": cfg["source"], "pages": len(cfg["page_urls"])}
        with _LOCK:
            _STATE.update(result=result, updated_ts=time.time(),
                          updated_at=result.get("generated_at", ""), error=None, error_ts=0.0)
            _STATE["history"].append(rec)
            del _STATE["history"][:-HISTORY_MAX]
    except Exception as e:  # noqa: BLE001
        # ดึงรอบนี้พลาด → เก็บผลรอบก่อนไว้โชว์ต่อ แต่บอกผู้ใช้ว่าข้อมูลไม่สดแล้ว
        with _LOCK:
            _STATE["error"], _STATE["error_ts"] = str(e), time.time()
        _log(f"ERROR: {e}")
    finally:
        with _LOCK:
            _STATE["refreshing"] = False
        _save()


# ───────────────────────── read API ─────────────────────────

def snapshot() -> dict:
    """meta สำหรับให้หน้าเว็บ poll ถี่ ๆ — ไม่มีก้อน result (ใหญ่) ติดมาด้วย."""
    cfg = config()
    now = time.time()
    with _LOCK:
        updated_ts = _STATE["updated_ts"]
        result = _STATE["result"]
        out = {
            "enabled": cfg["enabled"],
            "source": cfg["source"],
            "page_name": cfg["page_name"],
            "page_url": cfg["page_url"],
            "interval_min": cfg["interval_min"],
            "page_urls": cfg["page_urls"],
            "page_labels": cfg["page_labels"],
            "days": cfg["days"],
            "always": cfg["always"],
            "refreshing": _STATE["refreshing"],
            "running_sec": int(now - _STATE["started_ts"]) if _STATE["refreshing"] else 0,
            "logs": list(_STATE["logs"]),
            "error": _STATE["error"],
            "updated_ts": updated_ts,
            "updated_at": _STATE["updated_at"],
            "history": list(_STATE["history"])[-48:],
            "has_result": result is not None,
            "status": (result or {}).get("status"),
        }
    out["age_sec"] = int(now - updated_ts) if updated_ts else None
    out["next_in_sec"] = (max(0, int(cfg["interval_min"] * 60 - (now - updated_ts)))
                          if updated_ts else 0)
    return out


def latest_result() -> dict:
    with _LOCK:
        return {"updated_ts": _STATE["updated_ts"], "updated_at": _STATE["updated_at"],
                "result": _STATE["result"]}


def replace_result(result: dict) -> None:
    """ทับผลด้วยรายงานที่คิดใหม่ (ทีมแก้ label) — ไม่ขยับ updated_ts เพราะข้อมูลดิบชุดเดิม
    ยังอายุเท่าเดิม ถ้าขยับจะกลายเป็นเลื่อนรอบ scrape ถัดไปออกไปทุกครั้งที่มีคนกดแก้."""
    with _LOCK:
        _STATE["result"] = result
        if _STATE["history"]:
            h = _STATE["history"][-1]
            h["status"] = result.get("status", h["status"])
            h["negative"] = (result.get("sentiment_mix") or {}).get("negative", h["negative"])
    _save()


# ───────────────────────── background loop (opt-in) ─────────────────────────

def start_background() -> None:
    """MONITOR_ALWAYS=1 → ตรวจตามรอบเองแม้ไม่มีคนเปิดเว็บ (server ที่ไม่หลับเท่านั้น)."""
    cfg = config()
    if not (cfg["enabled"] and cfg["always"]):
        return

    def loop() -> None:
        while True:
            try:
                request_refresh()     # กรองเองว่าถึงรอบหรือยัง
            except Exception:         # noqa: BLE001 — loop ต้องไม่ตายเพราะ error รอบเดียว
                pass
            time.sleep(30)

    threading.Thread(target=loop, daemon=True).start()


_load()
