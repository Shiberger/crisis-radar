"""SampleFacebookSource — connector สำหรับเดโม่: อ่าน fixture JSON ของ Talesrunner.

implement interface CommentSource เดียวกับตัว scraper จริง → สลับได้โดยไม่แก้ pipeline.
mask ชื่อผู้คอมเมนต์ทันทีตั้งแต่ตอนโหลด (ดู security.py).
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Optional

from ..models import Comment
from ..security import scrub_pii_in_text
from ..timeutil import ICT


class SampleFacebookSource:
    platform = "facebook"

    def __init__(self, fixture_path: str | Path, brand: str = "talesrunner"):
        self.fixture_path = Path(fixture_path)
        self.brand = brand

    def fetch(self, since: Optional[datetime] = None) -> list[Comment]:
        raw = json.loads(self.fixture_path.read_text(encoding="utf-8"))
        page_id = raw.get("page_id", "unknown")
        out: list[Comment] = []
        for c in raw["comments"]:
            ts = datetime.fromisoformat(c["created_at"])
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=ICT)   # fixture เขียนเป็นเวลาไทยอยู่แล้ว แค่ไม่ได้ระบุ tz
            if since and ts < since:
                continue
            out.append(
                Comment(
                    platform=self.platform,
                    source_id=f"{page_id}/{c['post_id']}",
                    comment_id=c["comment_id"],
                    author=c["author"],                       # ชื่อจริง (ใช้ภายในเพื่อตอบ crisis)
                    text=scrub_pii_in_text(c["text"]),        # ยัง scrub เบอร์/อีเมลในเนื้อคอมเมนต์
                    created_at=ts,
                    reach=c.get("reach", 0),
                    brand=self.brand,
                    url=c.get("comment_url") or f"https://facebook.com/{page_id}/posts/{c['post_id']}",
                    comment_url=c.get("comment_url", ""),
                    profile_url=c.get("profile_url", ""),
                    post_title=c.get("post_title", ""),
                )
            )
        return out
