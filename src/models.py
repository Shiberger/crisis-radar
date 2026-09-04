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


def page_key(url: str = "", name: str = "") -> str:
    """key ประจำเพจ — ใช้จัดกลุ่ม/จับคู่ "คอมเมนต์นี้เป็นของเพจไหน" ทุกที่ในระบบ.

    อยู่ตรงนี้เพราะมีคนใช้ 4 ที่: รายงานฝั่ง server (backend/jobs.py), ข้อความ Discord
    (notify/payload.py + digest.py) และหน้าเว็บ (pkey() ใน index.html) — คิดคนละแบบเมื่อไหร่
    ข้อความแจ้งเตือนจะแปะสถานะของเพจ A ไว้บนคอมเมนต์ของเพจ B ซึ่งแย่กว่าไม่บอกอะไรเลย

    URL มาก่อนชื่อเสมอ เพราะชื่อเพจแก้ทีหลังได้ (ทีมเปลี่ยนใน page_presets) แต่ URL นิ่ง
    """
    u = str(url or "").strip().rstrip("/").lower()
    return u or str(name or "").strip().lower() or "-"


@dataclass
class Comment:
    platform: str            # 'facebook' | 'pantip' | 'google_play' ...
    source_id: str           # page/post id (หรือ thread id)
    comment_id: str
    author: str              # ชื่อผู้คอมเมนต์ (แสดงในหน้าภายในเพื่อให้ทีมตอบ crisis ได้)
    text: str
    created_at: datetime
    url: str = ""
    reach: int = 0           # like + reply — ใช้ถ่วงน้ำหนักความรุนแรงของ crisis
    brand: str = ""          # 'talesrunner' | 'warz' ...
    comment_url: str = ""    # ลิงก์ตรงไปคอมเมนต์นั้น (ให้ทีมคลิกไปตอบได้)
    profile_url: str = ""    # โปรไฟล์ผู้คอมเมนต์
    post_title: str = ""     # โพสต์ที่คอมเมนต์นี้อยู่ใต้ (บริบท)
    # เพจต้นทางของคอมเมนต์นี้ — รอบเดียวกวาดได้หลายเพจ (ดู jobs._fetch_facebook) ถ้าไม่ติดป้าย
    # ไว้ตั้งแต่ตอนดึง รายงานรวมจะเอาคอมเมนต์ 7 เพจมากองรวมกันโดยแยกไม่ออกว่าดราม่าอยู่เพจไหน
    page_name: str = ""      # ชื่อที่เอาไปโชว์ (จาก page_presets ใน targets.json)
    page_url: str = ""       # ลิงก์เพจ — ใช้เป็น key จัดกลุ่ม และให้กดเปิดเพจจริงได้

    def to_dict(self) -> dict:
        d = asdict(self)
        d["created_at"] = self.created_at.isoformat()
        return d

    @classmethod
    def from_dict(cls, d: dict) -> "Comment":
        """กลับจาก dict เป็น object — ใช้ตอนคำนวณรายงานใหม่จากผลที่เก็บไว้ (ไม่ต้อง scrape ซ้ำ)."""
        fields = {f: d.get(f) for f in cls.__dataclass_fields__ if f != "created_at"}
        return cls(created_at=datetime.fromisoformat(d["created_at"]),
                   **{k: v for k, v in fields.items() if v is not None})


@dataclass
class Classified:
    """ผลหลังผ่านชั้น AI: sentiment + topic + confidence.

    label สุดท้ายอาจไม่ได้มาจาก AI — ทีมแก้เองได้เมื่อ AI ทายพลาด (ดู classify/overrides.py)
    จึงเก็บ 'ค่าที่ AI ทายไว้เดิม' คู่กันเสมอ เพื่อให้ตรวจสอบย้อนหลังและเอาไปปรับ lexicon ได้
    """
    comment: Comment
    sentiment: str           # 'positive' | 'neutral' | 'negative'
    confidence: float        # 0..1
    topics: list[str] = field(default_factory=list)   # bug/billing/balance/service/content
    escalated_to_llm: bool = False   # ถูกส่งต่อให้ LLM เพราะโมเดลไทยไม่มั่นใจ
    overridden: bool = False         # ทีมแก้ label นี้เอง
    ai_sentiment: str = ""           # sentiment ที่ AI ทายก่อนถูกแก้
    ai_topics: list[str] = field(default_factory=list)
    archived: bool = False           # ทีมกด 'อ่านแล้ว' → ไม่นับในสถานะ/สถิติ (ดู classify/archive.py)
    alerted_at: str = ""             # เวลาที่คอมเมนต์นี้ถูกแจ้งเข้า Discord (ว่าง = ยังไม่เคยแจ้ง)
                                     # ดู notify/alerts.py — เก็บไว้กันแจ้งซ้ำและให้ทีมเห็นว่าส่งไปแล้ว

    def to_dict(self) -> dict:
        return {
            **self.comment.to_dict(),
            "sentiment": self.sentiment,
            "confidence": round(self.confidence, 3),
            "topics": self.topics,
            "escalated_to_llm": self.escalated_to_llm,
            "overridden": self.overridden,
            "ai_sentiment": self.ai_sentiment,
            "ai_topics": self.ai_topics,
            "archived": self.archived,
            "alerted_at": self.alerted_at,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Classified":
        return cls(
            comment=Comment.from_dict(d),
            sentiment=d["sentiment"],
            confidence=float(d.get("confidence") or 0),
            topics=list(d.get("topics") or []),
            escalated_to_llm=bool(d.get("escalated_to_llm")),
            overridden=bool(d.get("overridden")),
            ai_sentiment=d.get("ai_sentiment") or "",
            ai_topics=list(d.get("ai_topics") or []),
            archived=bool(d.get("archived")),
            alerted_at=d.get("alerted_at") or "",
        )


class CommentSource(Protocol):
    """ทุก connector implement เมธอดเดียวนี้.

    วันนี้: SampleFacebookSource / FacebookScraperSource
    วันหน้า: FacebookGraphAPISource (ใช้ page token จริงตอนได้ admin access)
    """

    platform: str

    def fetch(self, since: Optional[datetime] = None) -> list[Comment]:
        ...
