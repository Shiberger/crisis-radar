"""Hybrid classify pipeline: Thai lexicon (เร็ว/ถูก) → LLM เฉพาะเคสไม่มั่นใจ.

    comment
      → [lexicon.classify]
           ├─ confidence สูง + ไม่ต้อง LLM  → ใช้ผลเลย (กิน volume ส่วนใหญ่)
           └─ needs_llm / confidence ต่ำ     → [LLM.analyze] → ทับผล + escalated=True
"""
from __future__ import annotations

from ..models import Classified, Comment
from . import lexicon
from .llm import OfflineHeuristicLLM, SentimentLLM

CONF_THRESHOLD = 0.6


class HybridClassifier:
    def __init__(self, llm: SentimentLLM | None = None, conf_threshold: float = CONF_THRESHOLD):
        self.llm = llm or OfflineHeuristicLLM()
        self.conf_threshold = conf_threshold

    def classify_one(self, c: Comment) -> Classified:
        base = lexicon.classify(c.text)
        escalated = False

        if base["needs_llm"] or base["confidence"] < self.conf_threshold:
            out = self.llm.analyze(c.text, base["topics"])
            escalated = True
            sentiment = out["sentiment"]
            confidence = out["confidence"]
            topics = out.get("topics", base["topics"])
        else:
            sentiment = base["sentiment"]
            confidence = base["confidence"]
            topics = base["topics"]

        return Classified(
            comment=c,
            sentiment=sentiment,
            confidence=confidence,
            topics=topics,
            escalated_to_llm=escalated,
        )

    def classify_all(self, comments: list[Comment]) -> list[Classified]:
        return [self.classify_one(c) for c in comments]
