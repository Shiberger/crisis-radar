"""กติกาว่า "คอมเมนต์ไหนต้องเด้งเข้า Discord ตอนไหน" + ตัวส่งจริง (ผ่าน n8n).

alert เกิดได้ 2 ทาง — ตั้งใจให้ครอบทั้งกรณีที่ AI ถูกและกรณีที่ AI พลาด:

  1) auto   — คอมเมนต์ที่ "ลบและแรง" ตั้งแต่รอบตรวจ ไม่ต้องรอให้มีคนเห็นหน้าจอ
              (ดราม่าตอนตี 2 ไม่มีใครนั่งเฝ้า แต่ต้องมีคนรู้)
  2) manual — คนที่นั่ง monitor กดปุ่ม "แจ้ง Discord" เองที่คอมเมนต์นั้น
              เคสหลักคือ AI ให้เป็น "กลาง/บวก" แต่คนอ่านออกว่าเป็นเรื่อง (ประชด/นัยแฝง/
              บริบทที่โมเดลไม่รู้) — คนตัดสินทับได้เสมอ เหมือนที่แก้ label ได้

ปลายทางเป็น **n8n webhook** ไม่ใช่ Discord ตรง ๆ เพราะ n8n คือที่ที่ทีมเปลี่ยน channel
เพิ่ม mention role หรือต่อไป Jira/Sheet ได้เองโดยไม่ต้องแก้โค้ดแล้ว deploy ใหม่
(ยังไม่มี n8n ก็ตั้ง DISCORD_WEBHOOK_URL แทนได้ — payload ชั้น discord ยิงเข้า Discord ได้ตรง ๆ)

กันสแปม 3 ชั้น เพราะ alert ที่เด้งซ้ำจนคนปิดแจ้งเตือน = เท่ากับไม่มีระบบเตือน:
  - คอมเมนต์เดิมส่งซ้ำไม่ได้ (data/alerts_sent.json จำ comment_id ที่ส่งแล้ว) — สำคัญมาก
    เพราะรอบ scrape ถัดไปได้คอมเมนต์เดิมกลับมาเกือบทั้งหมด
  - auto ส่งได้มากสุด ALERT_MAX_PER_RUN ต่อรอบ (เรียงจาก reach มากสุดลงมา)
  - คอมเมนต์ที่ทีมกด "อ่านแล้ว" ไม่ auto ส่ง — ถือว่าจัดการไปแล้ว

ตั้งค่าผ่าน env (ดู .env.example):
  N8N_WEBHOOK_URL       ปลายทางหลัก — Webhook node ใน n8n
  N8N_WEBHOOK_SECRET    ส่งไปกับ header X-Crisis-Radar-Token ให้ n8n ตรวจก่อนรับ
  DISCORD_WEBHOOK_URL   ใช้แทนได้ถ้ายังไม่มี n8n (ยิงเข้า Discord ตรง ๆ)
  ALERT_AUTO=off        ปิดการส่งอัตโนมัติ เหลือแต่ปุ่มที่คนกดเอง
  ALERT_MIN_REACH=150   เกณฑ์ auto: คอมเมนต์ลบที่ไลก์+ตอบกลับถึงเท่านี้ (ค่าเริ่มต้น = เกณฑ์ไวรัล)
  ALERT_MAX_PER_RUN=5   auto ส่งได้กี่คอมเมนต์ต่อรอบตรวจ
  DISCORD_ROLE_MAP      JSON {"bug/technical":"<role id>"} → ping ทีมเจ้าของเรื่อง
  PUBLIC_URL            ลิงก์ dashboard ที่แนบไปในข้อความ
"""
from __future__ import annotations

import json
import os
import threading
import urllib.error
import urllib.request
from pathlib import Path

from ..crisis.detector import VIRAL_REACH
from ..env import ssl_context
from ..models import Classified
from ..timeutil import now_ict
from .payload import SENT_TH, build_event

STORE = Path(__file__).resolve().parent.parent.parent / "data" / "alerts_sent.json"
TIMEOUT = 8          # วินาที — ปลายทางช้ากว่านี้ถือว่าล่ม ไม่ให้รอบตรวจค้างตาม
_LOCK = threading.Lock()


def _int_env(key: str, default: int) -> int:
    try:
        return int(str(os.environ.get(key, "")).strip() or default)
    except ValueError:
        return default


def config() -> dict:
    """อ่าน env ทุกครั้งที่เรียก — เปลี่ยนค่าแล้วไม่ต้อง restart ตอน dev/test (เหมือน monitor.config())."""
    n8n = os.environ.get("N8N_WEBHOOK_URL", "").strip()
    direct = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    try:
        roles = json.loads(os.environ.get("DISCORD_ROLE_MAP") or "{}")
    except json.JSONDecodeError:
        roles = {}
    return {
        "url": n8n or direct,
        "via": "n8n" if n8n else ("discord" if direct else ""),
        "secret": os.environ.get("N8N_WEBHOOK_SECRET", "").strip(),
        "auto": os.environ.get("ALERT_AUTO", "").strip().lower() not in ("off", "0", "false", "no"),
        "min_reach": max(1, _int_env("ALERT_MIN_REACH", VIRAL_REACH)),
        "max_per_run": max(1, _int_env("ALERT_MAX_PER_RUN", 5)),
        "dashboard_url": os.environ.get("PUBLIC_URL", "").strip(),
        "roles": roles if isinstance(roles, dict) else {},
    }


def status() -> dict:
    """สรุปให้หน้าเว็บรู้ว่าปุ่ม 'แจ้ง Discord' ใช้ได้ไหม และเกณฑ์อัตโนมัติเป็นเท่าไร."""
    cfg = config()
    return {"configured": bool(cfg["url"]), "via": cfg["via"],
            "auto": cfg["auto"] and bool(cfg["url"]), "min_reach": cfg["min_reach"]}


# ───────────────────────── ที่จำว่าส่งอะไรไปแล้ว ─────────────────────────

def load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def sent_record(comment_id: str) -> dict | None:
    return load().get(str(comment_id))


def _mark(comment_id: str, rec: dict) -> dict:
    with _LOCK:
        data = load()
        data[str(comment_id)] = rec
        _write(data)
    return {"comment_id": str(comment_id), **rec}


def apply(items: list[Classified], store: dict | None = None) -> int:
    """ติดเวลาที่เคยแจ้งไว้กลับเข้าคอมเมนต์ (แก้ items ในที่). คืนจำนวนที่เคยแจ้งแล้ว.

    ต้องเรียกทุกครั้งที่ประกอบรายงานใหม่ ไม่งั้นรอบ scrape ถัดไปหน้าเว็บจะลืมว่าแจ้งไปแล้ว
    """
    data = load() if store is None else store
    n = 0
    for it in items:
        rec = data.get(it.comment.comment_id)
        it.alerted_at = (rec or {}).get("at", "")
        n += bool(rec)
    return n


# ───────────────────────── ตัวส่ง ─────────────────────────

def _post(cfg: dict, event: dict) -> None:
    # ส่ง n8n = ก้อนเต็ม (มีข้อมูลดิบให้ route ต่อ) · ส่ง Discord ตรง = เฉพาะชั้นข้อความ
    body = event if cfg["via"] == "n8n" else event["discord"]
    headers = {"Content-Type": "application/json"}
    if cfg["via"] == "n8n" and cfg["secret"]:
        headers["X-Crisis-Radar-Token"] = cfg["secret"]
    req = urllib.request.Request(cfg["url"], data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
                                 headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT, context=ssl_context()):
            return
    except urllib.error.HTTPError as e:
        # 401/403 = secret ไม่ตรง · 404 = workflow ไม่ได้เปิด/URL ผิด — บอกให้ตรงจุดจะได้ไม่ต้องเดา
        raise RuntimeError(f"ปลายทางตอบกลับ {e.code} — เช็ก URL/สิทธิ์ของ webhook ({cfg['via']})") from e
    except (urllib.error.URLError, OSError, TimeoutError) as e:
        raise RuntimeError(f"ต่อ webhook ไม่ได้ ({cfg['via']}): {e}") from e


def _severity(reach: int, cfg: dict) -> str:
    return "high" if reach >= cfg["min_reach"] else "medium"


def _role_for(topics, cfg: dict) -> str:
    for t in topics or []:
        if cfg["roles"].get(t):
            return str(cfg["roles"][t])
    return ""


def send(row: dict, report: dict, *, trigger: str, severity: str, reason: str,
         note: str = "", page: dict | None = None, force: bool = False,
         cfg: dict | None = None) -> dict:
    """ส่ง alert ของคอมเมนต์เดียว. คืน record ที่บันทึกไว้ (มี 'at' = เวลาไทย).

    ล้มเหลว → raise: ValueError = ตั้งค่า/เงื่อนไขไม่ผ่าน (คนแก้ได้เอง)
                     RuntimeError = ส่งไม่ถึงปลายทาง
    **บันทึกว่าส่งแล้วเฉพาะตอนยิงสำเร็จ** — ไม่งั้นครั้งหน้าจะไม่มีใครส่งซ้ำให้
    """
    cfg = cfg or config()
    if not cfg["url"]:
        raise ValueError("ยังไม่ได้ตั้งค่าปลายทางแจ้งเตือน — ตั้ง N8N_WEBHOOK_URL "
                         "(หรือ DISCORD_WEBHOOK_URL) ฝั่ง server ก่อน")
    cid = str(row.get("comment_id") or "").strip()
    if not cid:
        raise ValueError("ไม่มี comment_id")

    prev = sent_record(cid)
    if prev and not force:
        raise ValueError(f"คอมเมนต์นี้แจ้งเข้า Discord ไปแล้วเมื่อ {prev.get('at', '')}")

    event = build_event(row, trigger=trigger, severity=severity, reason=reason,
                        report=report, note=note, page=page,
                        role_id=_role_for(row.get("topics"), cfg),
                        dashboard_url=cfg["dashboard_url"])
    _post(cfg, event)
    return _mark(cid, {"at": now_ict().isoformat(timespec="minutes"), "trigger": trigger,
                       "severity": severity, "reason": reason, "note": note,
                       "via": cfg["via"], "status": report.get("status", "")})


def send_manual(row: dict, report: dict, note: str = "", page: dict | None = None,
                force: bool = False) -> dict:
    """คนกดปุ่มแจ้งเอง — ใช้กับเคสที่ AI อ่านพลาด (ให้เป็นกลาง/บวก ทั้งที่เป็นเรื่อง).

    ถือเป็น severity 'high' เสมอ: ผ่านสายตาคนมาแล้วว่าต้องรีบดู ไม่ใช่การเดาของโมเดล
    """
    ai = row.get("ai_sentiment") if row.get("overridden") else row.get("sentiment")
    reason = (f"คนที่นั่งดูหน้า Monitor กดแจ้งเอง — ระบบอ่านคอมเมนต์นี้เป็น "
              f"“{SENT_TH.get(ai, ai or '—')}” ซึ่งไม่ตรงกับที่คนอ่านแล้วเข้าใจ")
    return send(row, report, trigger="manual", severity="high", reason=reason,
                note=note, page=page, force=force)


def dispatch_auto(items: list[Classified], report: dict, page: dict | None = None,
                  log=None) -> list[dict]:
    """ส่ง alert ให้คอมเมนต์ที่ "ลบและแรง" ตั้งแต่รอบตรวจ (ยังไม่เคยส่ง) — แก้ .alerted_at ในที่.

    ช่วง CRISIS ลดเกณฑ์ลงครึ่งหนึ่ง เพราะตอนเพจกำลังไหม้ คอมเมนต์ลบที่ reach ปานกลาง
    ก็มีน้ำหนักกว่าปกติ — โควตาต่อรอบยังคุมไม่ให้ท่วมอยู่ดี
    """
    cfg = config()
    if not (cfg["url"] and cfg["auto"]):
        return []

    threshold = cfg["min_reach"]
    if report.get("status") == "CRISIS":
        threshold = max(1, threshold // 2)

    known = load()
    cands = [it for it in items
             if it.sentiment == "negative" and not it.archived
             and it.comment.reach >= threshold
             and it.comment.comment_id not in known]
    cands.sort(key=lambda it: it.comment.reach, reverse=True)

    out: list[dict] = []
    for it in cands[:cfg["max_per_run"]]:
        reason = (f"คอมเมนต์เชิงลบที่คนกดไลก์/ตอบกลับ {it.comment.reach:,} ครั้ง "
                  f"(เกณฑ์แจ้งอัตโนมัติตอนนี้ {threshold:,})")
        try:
            rec = send(it.to_dict(), report, trigger="auto", severity=_severity(it.comment.reach, cfg),
                       reason=reason, page=page, cfg=cfg)
        except (ValueError, RuntimeError) as e:
            # ปลายทางล่ม → หยุดทั้งรอบ ไม่ต้องไล่ยิงตัวที่เหลือให้เสียเวลา (รอบหน้าค่อยส่งใหม่)
            if log:
                log(f"แจ้ง Discord ไม่สำเร็จ: {e}")
            break
        it.alerted_at = rec["at"]
        out.append(rec)

    if log and out:
        log(f"แจ้ง Discord อัตโนมัติ {len(out)} คอมเมนต์ (เชิงลบ + คนเห็นเยอะเกินเกณฑ์)")
    if log and len(cands) > len(out) and out:
        log(f"อีก {len(cands) - len(out)} คอมเมนต์เข้าเกณฑ์แต่เกินโควตาต่อรอบ — ดูได้บนหน้าเว็บ")
    return out
