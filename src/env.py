"""โหลดค่าจากไฟล์ .env (stdlib ล้วน — ไม่ต้องลง python-dotenv).

ให้ผู้ใช้แค่แปะ token ลงไฟล์ .env แล้วระบบอ่านเอง (ง่ายกว่าพิมพ์ export ทุกครั้ง).
ค่าที่ตั้งใน environment อยู่แล้วจะไม่ถูกทับ (setdefault).
"""
from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def load_dotenv(path: str | Path | None = None) -> None:
    p = Path(path) if path else ROOT / ".env"
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))
