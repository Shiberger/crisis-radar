#!/usr/bin/env python3
"""Crisis Radar — web server (Python stdlib ล้วน, ไม่ต้อง pip install).

รัน:   python3 backend/server.py         แล้วเปิด http://127.0.0.1:8000
แชร์ใน LAN:  python3 backend/server.py --host 0.0.0.0

team ใช้งานผ่านหน้าเว็บ (กดปุ่ม) — ไม่ต้องรันคำสั่งเอง

ตอน deploy (Render ฯลฯ): ตั้ง env var HOST=0.0.0.0 และ PORT ตามที่ platform กำหนด
"""
from __future__ import annotations

import argparse
import hmac
import json
import os
import sys
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from src.env import load_dotenv  # noqa: E402
load_dotenv()   # อ่าน APIFY_TOKEN / FB_COOKIES_JSON จากไฟล์ .env (ถ้ามี)

import jobs  # noqa: E402  (อยู่โฟลเดอร์เดียวกัน)

STATIC = HERE / "static"

# ตั้ง RUN_PASSCODE ไว้ตอน deploy → โหมด "Facebook จริง" จะต้องกรอกรหัสก่อน
# (กันคนที่ได้ลิงก์กดยิง Apify เล่นจนเครดิตหมด) — โหมดตัวอย่างยังเปิดให้ทุกคน
# ถ้าไม่ตั้ง (เช่นรันบนเครื่องตัวเอง) จะไม่ถามรหัส
RUN_PASSCODE = os.environ.get("RUN_PASSCODE", "")


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):  # เงียบ log
        pass

    def _send(self, code: int, body, ctype: str = "application/json") -> None:
        if isinstance(body, (dict, list)):
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = str(body).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", f"{ctype}; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path in ("/", "/index.html"):
            self._send(200, (STATIC / "index.html").read_text(encoding="utf-8"), "text/html")
        elif self.path == "/api/health":
            # passcode_required → หน้าเว็บใช้ตัดสินว่าต้องถามรหัสก่อนดึง Facebook จริงไหม
            self._send(200, {"ok": True, "passcode_required": bool(RUN_PASSCODE)})
        elif self.path.startswith("/api/jobs/"):
            job = jobs.get_job(self.path.rsplit("/", 1)[-1])
            if not job:
                self._send(404, {"error": "job not found"})
            else:
                self._send(200, {"status": job["status"], "logs": job["logs"],
                                 "result": job["result"], "error": job["error"]})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if self.path == "/api/run":
            n = int(self.headers.get("Content-Length", 0) or 0)
            try:
                body = json.loads(self.rfile.read(n) or b"{}")
            except json.JSONDecodeError:
                body = {}
            if body.get("source") == "facebook" and RUN_PASSCODE:
                given = self.headers.get("X-Run-Passcode", "")
                if not hmac.compare_digest(given, RUN_PASSCODE):
                    self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                    return
            self._send(200, {"job_id": jobs.start_job(body)})
        else:
            self._send(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser()
    # ค่า default อ่านจาก env ก่อน — platform อย่าง Render กำหนด PORT ให้เอง
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = ap.parse_args()
    print(f"📡 Crisis Radar → http://{args.host}:{args.port}  (Ctrl+C เพื่อหยุด)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
