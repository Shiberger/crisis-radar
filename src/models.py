"""Core domain types สำหรับ Crisis Radar.

- Comment      = 1 คอมเมนต์จาก social ช่องทางใดก็ได้ (normalize เป็นรูปเดียวแล้ว)
- CommentSource = interface เดียวที่ทุก connector ต้อง implement
                  → วันนี้ข้างในเป็น scraper, วันหน้าเปลี่ยนเป็น official API
                    โดย pipeline ส่วนที่เหลือ (classify/crisis/dashboard) ไม่ต้องแก้เลย
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Optional, Protocol


@dataclass
class Comment:
    platform: str            # 'facebook' | 'pantip' | 'google_play' ...
    source_id: str           # page/post id (หรือ thread id)
    comment_id: str
    author: str              # ชื่อผู้คอมเมนต์ — จะถูก mask ก่อนเก็บ (ดู security.py)
    text: str
    created_at: datetime
    url: str = ""
    reach: int = 0           # like + reply — ใช้ถ่วงน้ำหนักความรุนแรงของ crisis
    brand: str = ""          # 'talesrunner' | 'warz' ...

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d


@dataclass
class Classified:
    """ผลหลังผ่านชั้น AI: sentiment + topic + confidence."""
    comment: Comment
    sentiment: str           # 'positive' | 'neutral' | 'negative'
    confidence: float        # 0..1
    topics: list[str] = field(default_factory=list)   # bug/billing/balance/service/content
    escalated_to_llm: bool = False   # ถูกส่งต่อให้ LLM เพราะโมเดลไทยไม่มั่นใจ

    def to_dict(self) -> dict:
        return {
            **self.comment.to_dict(),
            "sentiment": self.sentiment,
            "confidence": round(self.confidence, 3),
            "topics": self.topics,
            "escalated_to_llm": self.escalated_to_llm,
        }


class CommentSource(Protocol):
    """ทุก connector implement เมธอดเดียวนี้.

    วันนี้: SampleFacebookSource / FacebookScraperSource
    วันหน้า: FacebookGraphAPISource (ใช้ page token จริงตอนได้ admin access)
    """

    platform: str

    def fetch(self, since: Optional[datetime] = None) -> list[Comment]:
        ...
