"""ที่เก็บ 'คำตัดสินของคน' ที่ทับผลของ AI — เมื่อ AI อ่านผิด ทีมแก้เองได้.

ทำไมต้องมี:
  AI อ่านภาษาไทยแบบขำ ๆ / ประชด / บ่นเล่น ๆ พลาดได้เสมอ เช่น
  "รำคาญหัวเด้งสุดละไม่มีไรแก้ทางเลย…👋" — lexicon เจอ 'รำคาญ' + 'เด้ง' → ตัดสินเป็นลบ
  ทั้งที่คนอ่านออกว่าเป็นการหยอกเล่น ถ้าปล่อยไว้ ตัวเลขคอมเมนต์ลบจะเฟ้อและ crisis จะเตือนผิด

หลักการ:
  - แก้แล้ว **ติดตัวคอมเมนต์นั้นตลอด** (key = comment_id) → รอบ scrape ถัดไปก็ยังถูกต้อง
    ไม่ต้องมานั่งแก้ซ้ำทุกครั้ง
  - เก็บค่าที่ AI ทายไว้เดิมด้วยเสมอ → ตรวจสอบย้อนหลังได้ และเอาไปเป็นชุดข้อมูลปรับ
    lexicon/prompt ต่อได้ (ดู tests/labeled_test_set.json)
  - ไฟล์เดียว JSON — ไม่ต้องมี DB ให้ทีมดูแล
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Iterable, Optional

from ..models import Classified
from ..timeutil import now_ict
from .lexicon import TOPIC_LABELS

STORE = Path(__file__).resolve().parent.parent.parent / "data" / "overrides.json"
SENTIMENTS = ("positive", "neutral", "negative")
MAX_NOTE = 300
_LOCK = threading.Lock()


def load() -> dict:
    try:
        data = json.loads(STORE.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write(data: dict) -> None:
    STORE.parent.mkdir(parents=True, exist_ok=True)
    STORE.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")


def clean_topics(topics: Optional[Iterable[str]]) -> list[str]:
    """รับเฉพาะประเด็นที่ระบบรู้จัก — กันข้อมูลมั่วจากหน้าเว็บเข้ามาทำ report เพี้ยน."""
    seen, out = set(), []
    for t in topics or []:
        t = str(t).strip()
        if t in TOPIC_LABELS and t not in seen:
            seen.add(t)
            out.append(t)
    return out


def set_override(comment_id: str, sentiment: Optional[str] = None,
                 topics: Optional[Iterable[str]] = None, note: str = "",
                 ai_sentiment: str = "", ai_topics: Optional[Iterable[str]] = None) -> dict:
    """บันทึกคำตัดสินของคน. sentiment=None แปลว่าไม่แก้อารมณ์ (แก้แต่ประเด็น)."""
    comment_id = str(comment_id).strip()
    if not comment_id:
        raise ValueError("ไม่มี comment_id")
    if sentiment is not None and sentiment not in SENTIMENTS:
        raise ValueError(f"อารมณ์ต้องเป็นหนึ่งใน {', '.join(SENTIMENTS)}")

    rec = {"at": now_ict().isoformat(timespec="minutes"), "note": str(note or "")[:MAX_NOTE]}
    if sentiment is not None:
        rec["sentiment"] = sentiment
    if topics is not None:
        rec["topics"] = clean_topics(topics)
    # เก็บค่าที่ AI ทายไว้ ณ ตอนที่คนกดแก้ครั้งแรก — แก้ซ้ำต้องไม่ทับของเดิม
    # เช็ก key ไม่ใช่ค่าความจริง เพราะ "AI ไม่ได้จัดประเด็นไว้เลย" (= ลิสต์ว่าง) ก็เป็นค่าที่ถูกต้อง
    with _LOCK:
        data = load()
        old = data.get(comment_id) or {}
        rec["ai_sentiment"] = old["ai_sentiment"] if "ai_sentiment" in old else ai_sentiment
        rec["ai_topics"] = old["ai_topics"] if "ai_topics" in old else clean_topics(ai_topics)
        data[comment_id] = rec
        _write(data)
    return rec


def clear(comment_id: str) -> bool:
    """คืนค่าให้ AI ตัดสินเหมือนเดิม."""
    with _LOCK:
        data = load()
        if str(comment_id) not in data:
            return False
        data.pop(str(comment_id))
        _write(data)
    return True


def apply(items: list[Classified], store: Optional[dict] = None) -> int:
    """ทับ label ของ AI ด้วยคำตัดสินของคน (แก้ items ในที่). คืนจำนวนที่ถูกทับ.

    เรียกก่อน detector.detect() เสมอ — ไม่งั้น crisis จะยังคิดจากค่าที่ AI ทายผิด
    """
    data = load() if store is None else store
    if not data:
        return 0
    n = 0
    for it in items:
        rec = data.get(it.comment.comment_id)
        if not rec:
            continue
        it.ai_sentiment = rec["ai_sentiment"] if rec.get("ai_sentiment") else it.sentiment
        it.ai_topics = list(rec["ai_topics"]) if "ai_topics" in rec else list(it.topics)
        if rec.get("sentiment"):
            it.sentiment = rec["sentiment"]
        if rec.get("topics") is not None:
            it.topics = list(rec["topics"])
        it.overridden = True
        n += 1
    return n
