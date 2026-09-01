"""ช่องทางแจ้งเตือนออกนอกระบบ — วันนี้คือ Discord ผ่าน n8n.

แยกเป็นแพ็กเกจของตัวเองเพราะ "ตรวจเจอ" กับ "บอกใคร" เป็นคนละหน้าที่:
detector ตัดสินว่าอะไรผิดปกติ · ที่นี่ตัดสินว่าเรื่องไหนคุ้มที่จะไปรบกวนคน และส่งอย่างไร
วันหน้าเพิ่ม LINE/Slack/อีเมล ก็มาต่อที่นี่ โดย pipeline ส่วนอื่นไม่ต้องรู้เรื่องด้วย
"""
from . import digest  # noqa: F401  (สรุปประจำวัน — ใช้ผ่าน notify.digest.send())
from .alerts import (  # noqa: F401
    apply,
    config,
    dispatch_auto,
    load,
    send,
    send_manual,
    sent_record,
    status,
)
