"""เรื่องจุกจิกของ "เครื่องที่รันอยู่" — โหลด .env และหา CA bundle ให้เจอ (stdlib ล้วน).

รวมไว้ที่เดียวเพราะทุกตัวที่ต้องคุยกับ API ข้างนอก (Apify, Anthropic) เจอปัญหาเดียวกันหมด
"""
from __future__ import annotations

import os
import ssl
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def ssl_context() -> ssl.SSLContext:
    """หา CA bundle ให้เจอเอง — Python จาก python.org บน mac มักหา cert ไม่เจอ.

    อาการ: urlopen ล้มด้วย CERTIFICATE_VERIFY_FAILED ทั้งที่เน็ตปกติและ URL ถูก
    (แก้ถาวรได้ด้วยการรัน "Install Certificates.command" ที่มากับ Python แต่ไม่ใช่ทุกเครื่องทำ)

    ⚠️ **ยัง verify certificate ตามปกติ ไม่ได้ปิด** — ปลอดภัยเวลาส่ง API key ออกไป
    """
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        pass
    for p in ("/etc/ssl/cert.pem", "/etc/ssl/certs/ca-certificates.crt",
              "/usr/local/etc/openssl@3/cert.pem"):
        if os.path.exists(p):
            return ssl.create_default_context(cafile=p)
    return ssl.create_default_context()


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
