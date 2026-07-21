"""เวลาไทย (ICT, UTC+7) — จุดเดียวที่ระบบใช้อ้างอิงเวลา.

ทำไมต้องมี: server ที่ deploy จริง (Render ฯลฯ) ตั้งนาฬิกาเป็น UTC และ Apify
ก็ส่ง timestamp มาเป็น UTC → ถ้าปล่อยตามนั้น ทั้ง log, กราฟ timeline และ
"อัปเดตเมื่อ" จะเพี้ยนไป 7 ชั่วโมง ทีมที่อ่าน dashboard อยู่ไทยจะตีความผิดทันที
(เช่น ดราม่าพีคตอน 3 ทุ่ม แต่กราฟขึ้น 14:00)

กติกา: ทุก datetime ที่ไหลในระบบเป็น aware และอยู่ ICT เสมอ
— ไม่ปน naive/aware เพราะเอามาเทียบกันจะ raise TypeError
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

ICT = timezone(timedelta(hours=7), "ICT")


def now_ict() -> datetime:
    """เวลาปัจจุบันตามเวลาไทย (ไม่ขึ้นกับ timezone ของเครื่อง/container)."""
    return datetime.now(ICT)


def to_ict(dt: datetime) -> datetime:
    """แปลงเป็นเวลาไทย. ถ้าเป็น naive ถือว่าเป็น UTC (ต้นทาง Apify/FB ส่งมาแบบนั้น)."""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(ICT)
