"""คลังคอมเมนต์ที่ทีม "อ่านแล้ว" — เอาออกจากหน้า Monitor แล้วไม่ต้องวิเคราะห์ซ้ำ.

ทำไมต้องมี:
  รอบ scrape ถัดไปจะได้คอมเมนต์เดิมกลับมาเกือบทั้งหมด (โพสต์เดิม คนเดิม) ถ้าไม่มีที่จำว่า
  "อันนี้ทีมอ่าน/จัดการไปแล้ว" หน้าจอจะเต็มไปด้วยของเก่า จนของใหม่ที่ต้องรีบดูจมหาย

ประหยัดอะไรได้จริงบ้าง (ตรงไปตรงมา):
  ✅ **token ของ AI** — คอมเมนต์ในคลังจะไม่ถูกส่งเข้า classifier อีก ใช้ label เดิมที่เก็บไว้
     วันที่สลับชั้น LLM เป็น Claude Haiku จริง จะประหยัดตามจำนวนคอมเมนต์ในคลังตรง ๆ
  ✅ เวลา/CPU ต่อรอบ และภาระสายตาคน
  ❌ **ไม่ได้ลดค่า Apify** — Apify คิดเงินตอนดึงคอมเมนต์ ซึ่งเกิดก่อนที่เราจะรู้ว่าอันไหนอ่านแล้ว
     และ actor สั่งข้ามคอมเมนต์รายตัวไม่ได้ · อยากลดค่า Apify ต้องลด MONITOR_MAX_POSTS /
     MONITOR_MAX_COMMENTS หรือยืด MONITOR_INTERVAL_MIN

ผลต่อการตรวจ crisis:
  คอมเมนต์ในคลัง **ไม่ถูกนับ** ในสถานะ/สถิติ/spike (ถือว่าทีมจัดการแล้ว) — แปลว่าถ้า archive
  คอมเมนต์ลบเยอะ ๆ สถานะจะดูดีขึ้นได้ จึงต้องโชว์จำนวนในคลังคู่กับสถานะเสมอ (ดู index.html)
  และเอากลับออกจากคลังได้ตลอด

รูปข้อมูล: {comment_id: {"at": iso, "item": <classified dict ล่าสุด>}}
เก็บ item เต็มเพราะต้องใช้ 2 อย่าง — ข้ามการ classify ซ้ำ และวาดหน้า "คลัง" ให้ดูย้อนหลังได้
ปลายทาง = ไฟล์ data/archive.json หรือแถวเดียวใน Supabase แล้วแต่ env (ดู src/state.py)
"""
from __future__ import annotations

import threading
from pathlib import Path
from typing import Iterable

from .. import state
from ..models import Classified, Comment
from ..timeutil import now_ict

STORE = Path(__file__).resolve().parent.parent.parent / "data" / "archive.json"
_LOCK = threading.Lock()


def load() -> dict:
    data = state.read_json(STORE, default={})
    return data if isinstance(data, dict) else {}


def _write(data: dict) -> None:
    state.write_json(STORE, data, indent=1)


def add(items: Iterable[dict]) -> int:
    """เก็บเข้าคลัง. items = classified dict (ต้องมี comment_id) — เก็บทั้งก้อนไว้ใช้ทีหลัง."""
    n = 0
    with _LOCK:
        data = load()
        for it in items:
            cid = str(it.get("comment_id") or "").strip()
            if not cid:
                continue
            at = (data.get(cid) or {}).get("at") or now_ict().isoformat(timespec="minutes")
            data[cid] = {"at": at, "item": {**it, "archived": True}}
            n += 1
        _write(data)
    return n


def remove(comment_ids: Iterable[str]) -> int:
    """เอากลับออกจากคลัง → กลับไปนับในสถานะ/สถิติตามปกติ."""
    n = 0
    with _LOCK:
        data = load()
        for cid in comment_ids:
            if data.pop(str(cid), None) is not None:
                n += 1
        _write(data)
    return n


def apply(items: list[Classified], store: dict | None = None) -> int:
    """ตั้งธง .archived ตามไฟล์ (แก้ items ในที่). คืนจำนวนที่อยู่ในคลัง."""
    data = load() if store is None else store
    n = 0
    for it in items:
        it.archived = it.comment.comment_id in data
        n += it.archived
    return n


def partition(comments: list[Comment], store: dict | None = None):
    """แยกคอมเมนต์ที่ scrape มา เป็น (ยังไม่เคยอ่าน, อยู่ในคลังแล้ว).

    ตัวหลังจะไม่ถูกส่งเข้า classifier — นี่คือจุดที่ประหยัด token จริง
    """
    data = load() if store is None else store
    fresh, known = [], []
    for c in comments:
        (known if c.comment_id in data else fresh).append(c)
    return fresh, known


def rehydrate(comments: list[Comment], store: dict | None = None) -> list[Classified]:
    """สร้าง Classified ของคอมเมนต์ในคลังจาก label ที่เก็บไว้ (ไม่เรียก AI ซ้ำ).

    ใช้ตัว Comment สด ๆ จากรอบ scrape ล่าสุด — ยอดไลก์/ตอบกลับจะได้เป็นปัจจุบัน
    ส่วน label (อารมณ์/ประเด็น/ที่ทีมเคยแก้) ใช้ของเดิม
    """
    data = load() if store is None else store
    out = []
    for c in comments:
        saved = (data.get(c.comment_id) or {}).get("item") or {}
        item = Classified(
            comment=c,
            sentiment=saved.get("sentiment", "neutral"),
            confidence=float(saved.get("confidence") or 0),
            topics=list(saved.get("topics") or []),
            escalated_to_llm=bool(saved.get("escalated_to_llm")),
            overridden=bool(saved.get("overridden")),
            ai_sentiment=saved.get("ai_sentiment") or "",
            ai_topics=list(saved.get("ai_topics") or []),
        )
        item.archived = True
        out.append(item)
    return out


def sync(items: list[Classified]) -> None:
    """เขียน snapshot ของตัวที่อยู่ในคลังให้ตรงกับ label ล่าสุด (เช่น หลังทีมแก้อารมณ์).

    ไม่แตะ 'at' เดิม — เวลาที่กดอ่านคือข้อมูลที่ควรคงไว้
    """
    archived = [it for it in items if it.archived]
    if not archived:
        return
    with _LOCK:
        data = load()
        changed = False
        for it in archived:
            cid = it.comment.comment_id
            if cid not in data:
                continue
            data[cid]["item"] = it.to_dict()
            changed = True
        if changed:
            _write(data)
