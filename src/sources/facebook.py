"""FacebookScraperSource — โครงตัวดึง Facebook จริง (รัน local เท่านั้น).

⚠️ สถานะ: prototype path. Facebook เป็นช่องทางที่ scrape ยากและ fragile ที่สุด
   (ต้องล็อกอิน, มี anti-bot, อยู่ใน ToS gray area). โค้ดนี้ "ไม่ถูกเรียกในเดโม่/CI"
   — มีไว้เพื่อแสดง migration path เท่านั้น.

3 ทางที่เป็นไปได้ เรียงตามความถูกต้อง/ยั่งยืน:
  1) Meta Graph API + Page access token  ← ปลายทางจริง (ต้องได้ admin ของเพจก่อน)
     GET /{page_id}/posts?fields=comments{{message,created_time,like_count,from}}
  2) Apify 'Facebook Comments Scraper' actor  ← ทีมเคยใช้ Apify มาก่อน (restaurant project)
  3) Playwright headless + login  ← เปราะสุด ใช้เฉพาะ prototype

เมื่อได้ Graph API แล้วให้สร้าง FacebookGraphAPISource ที่ implement fetch() แบบเดียวกัน
แล้วสลับใน registry — pipeline ที่เหลือไม่ต้องแก้.
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from ..models import Comment
from ..security import mask_author, scrub_pii_in_text


class FacebookScraperSource:
    platform = "facebook"

    def __init__(self, page_id: str, brand: str, mode: str = "apify"):
        self.page_id = page_id
        self.brand = brand
        self.mode = mode   # 'apify' | 'graph_api' | 'playwright'

    def fetch(self, since: Optional[datetime] = None) -> list[Comment]:
        raw_items = self._fetch_raw(since)   # ← จุดเดียวที่ต่างกันตามช่องทาง
        return [
            Comment(
                platform=self.platform,
                source_id=f"{self.page_id}/{it['post_id']}",
                comment_id=it["comment_id"],
                author=mask_author(it["author"]),
                text=scrub_pii_in_text(it["text"]),
                created_at=it["created_at"],
                reach=it.get("reach", 0),
                brand=self.brand,
                url=it.get("url", ""),
            )
            for it in raw_items
        ]

    def _fetch_raw(self, since):
        raise NotImplementedError(
            "ต่อ Graph API / Apify / Playwright ตอนรัน local — ดู docstring ด้านบน. "
            "เดโม่ใช้ SampleFacebookSource แทน."
        )
