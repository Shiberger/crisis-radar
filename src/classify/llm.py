"""ชั้นที่ 2 ของ Hybrid AI: LLM escalation.

หน้าที่: รับเฉพาะเคสที่ชั้น lexicon/Thai-model ไม่มั่นใจ (ประชด/สแลง/บวกลบปนกัน)
แล้ววิเคราะห์ให้ลึกขึ้น + สกัด topic + (ใน production) ช่วยสรุป crisis และร่างคำตอบ

ออกแบบเป็น interface สลับได้:
  - OfflineHeuristicLLM : ใช้ในเดโม่/CI — กฎประชดแบบ deterministic (ไม่ต้องเน็ต ทดสอบได้)
  - ClaudeLLM          : ใช้จริงตอน production (ต่อ Anthropic API — ดูโค้ดตัวอย่างด้านล่าง)

ต้นทุน LLM จึงแปรตาม "ปริมาณดราม่า" ไม่ใช่ปริมาณคอมเมนต์ทั้งหมด → คุมค่าใช้จ่ายได้.
"""
from __future__ import annotations

from typing import Protocol


class SentimentLLM(Protocol):
    def analyze(self, text: str, topics: list[str]) -> dict:
        ...


class OfflineHeuristicLLM:
    """ตัวแทน LLM สำหรับเดโม่/เทสต์ — กฎประชดง่าย ๆ ที่ lexicon จับไม่ได้.

    ในของจริงจะถูกแทนด้วย ClaudeLLM. จุดสำคัญคือ interface เหมือนกัน
    → pipeline ไม่ต้องแก้เมื่อสลับไปใช้โมเดลจริง.
    """

    name = "offline-heuristic"

    # ประชดที่พบบ่อยในคอมเมนต์เกมไทย: คำบวก + บริบทเชิงล่ม/ปัญหา = จริง ๆ แล้วลบ
    # ⚠️ cue ต้องยาวพอ — เคยใช้ "รอ" เฉย ๆ แล้วไปแมตช์ "รอบนี้" ทำให้คำถามธรรมดากลายเป็นลบ
    _SARCASM_NEG_CUES = ["ล่ม", "ไม่ได้", "พัง", "บั๊ก", "เด้ง", "หาย", "รอนาน", "ต้องรอ",
                          "ยังรอ", "รอมา", "ช้า", "error", "เจ๊ง"]
    _SARCASM_POS_WORDS = ["ดีจริง", "ขอบคุณมากค่า", "ดีจังเนอะ", "เก่งมาก", "แหม", "ดีมาก", "ดีเลิศ"]

    def analyze(self, text: str, topics: list[str]) -> dict:
        t = text.lower()
        looks_positive = any(w in text for w in self._SARCASM_POS_WORDS)
        has_neg_context = any(c in t for c in self._SARCASM_NEG_CUES)
        if looks_positive and has_neg_context:
            # ประชด: พูดดีแต่บริบทคือปัญหา → เป็นลบจริง
            return {"sentiment": "negative", "confidence": 0.82, "topics": topics}
        # ถ้ามี cue ปัญหาชัด ๆ ก็ลบ
        if has_neg_context:
            return {"sentiment": "negative", "confidence": 0.7, "topics": topics}
        return {"sentiment": "neutral", "confidence": 0.55, "topics": topics}


class ClaudeLLM:
    """โครงสำหรับ production — เรียก Anthropic API.

    เลือก Haiku 4.5 (claude-haiku-4-5-20251001) เพราะงานนี้คือ classification
    ปริมาณมาก ต้องเร็ว+ถูก. ไม่ถูกเรียกในเดโม่ offline (ต้องมี ANTHROPIC_API_KEY).
    """

    name = "claude-haiku-4.5"
    MODEL = "claude-haiku-4-5-20251001"

    _PROMPT = (
        "คุณคือผู้ช่วยวิเคราะห์คอมเมนต์โซเชียลภาษาไทยของชุมชนเกม "
        "ตอบเป็น JSON: sentiment (positive/neutral/negative), confidence 0-1, "
        "และ topics (bug/technical, billing/price, balance/fairness, service/support, content/event). "
        "ระวังการประชดประชัน (พูดดีแต่หมายถึงลบ) และสแลงเกมไทย.\n\nคอมเมนต์: {text}"
    )

    def __init__(self, client=None):
        # from anthropic import Anthropic; client = Anthropic()
        self._client = client

    def analyze(self, text: str, topics: list[str]) -> dict:
        if self._client is None:
            raise RuntimeError("ClaudeLLM ต้องมี Anthropic client — ตั้ง ANTHROPIC_API_KEY ก่อน")
        import json
        msg = self._client.messages.create(
            model=self.MODEL,
            max_tokens=200,
            messages=[{"role": "user", "content": self._PROMPT.format(text=text)}],
        )
        return json.loads(msg.content[0].text)
