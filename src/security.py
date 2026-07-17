"""มาตรการข้อมูลส่วนบุคคล (PII) — เป็นหัวข้อ Security Information ของ deliverable.

หลัก: เราสนใจ "สัญญาณรวม" (มีดราม่าไหม เรื่องอะไร) ไม่ใช่ตัวบุคคล
→ mask ชื่อผู้คอมเมนต์ก่อนเก็บ/ก่อนส่งเข้า LLM เสมอ. เก็บ hash ไว้พอให้นับ unique ได้
  โดยไม่รู้ว่าเป็นใคร.
"""
from __future__ import annotations

import hashlib

_SALT = "crisis-radar-v1"   # ใน production ย้ายไป env var


def mask_author(name: str) -> str:
    """'Somchai R' -> 'user_9f3a1c'. ตามตัวบุคคลกลับไม่ได้ แต่ยังนับ unique ได้."""
    name = (name or "").strip()
    if not name:
        return "user_anon"
    h = hashlib.sha256((_SALT + name).encode("utf-8")).hexdigest()[:6]
    return f"user_{h}"


def scrub_pii_in_text(text: str) -> str:
    """เผื่อคอมเมนต์แปะเบอร์/อีเมล/ไอดีเกม — แทนที่ก่อนเก็บ.

    เดโม่ทำแบบเบา ๆ (เบอร์โทร/อีเมล). production เพิ่ม pattern ไอดีเติมเงินได้.
    """
    import re
    text = re.sub(r"\b0\d{8,9}\b", "[phone]", text)                       # เบอร์ไทย
    text = re.sub(r"[\w.+-]+@[\w-]+\.[\w.-]+", "[email]", text)           # อีเมล
    return text
