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
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(HERE))

from src.env import load_dotenv  # noqa: E402
load_dotenv()   # อ่าน APIFY_TOKEN / FB_COOKIES_JSON จากไฟล์ .env (ถ้ามี)

import jobs      # noqa: E402  (อยู่โฟลเดอร์เดียวกัน)
import monitor   # noqa: E402

from src.classify import archive, lexicon, overrides  # noqa: E402
from src import notify                                # noqa: E402

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
            # alert → หน้าเว็บใช้บอกผู้ใช้ว่าปุ่ม "แจ้ง Discord" พร้อมใช้ไหม + เกณฑ์อัตโนมัติเท่าไร
            self._send(200, {"ok": True, "passcode_required": bool(RUN_PASSCODE),
                             "alert": notify.status()})
        elif self.path == "/api/targets":
            # ค่าตั้งต้นให้ฟอร์ม (URL เพจ/โพสต์จาก data/targets.json) — ไม่มีอะไรลับ
            self._send(200, jobs.get_targets())
        elif self.path == "/api/monitor":
            # เปิดหน้าเว็บ = ทริกเกอร์ตรวจใหม่ถ้าผลล่าสุดเก่าเกินรอบ (monitor กรองเองว่าถึงเวลาไหม)
            # ไม่ต้องมีรหัส: คนเปิดกี่คนก็ตรวจได้แค่รอบละครั้ง → เครดิต Apify คาดเดาได้
            monitor.request_refresh()
            self._send(200, monitor.snapshot())
        elif self.path == "/api/monitor/result":
            # ก้อนผลเต็ม — หน้าเว็บดึงเฉพาะตอน updated_ts เปลี่ยน (ไม่ดึงทุกครั้งที่ poll)
            self._send(200, monitor.latest_result())
        elif self.path == "/api/overrides":
            self._send(200, {"overrides": overrides.load(),
                             "topic_labels": lexicon.TOPIC_LABELS})
        elif self.path.startswith("/api/jobs/"):
            job = jobs.get_job(self.path.rsplit("/", 1)[-1])
            if not job:
                self._send(404, {"error": "job not found"})
            else:
                self._send(200, {"status": job["status"], "logs": job["logs"],
                                 "result": job["result"], "error": job["error"]})
        else:
            self._send(404, {"error": "not found"})

    def _passcode_ok(self) -> bool:
        return hmac.compare_digest(self.headers.get("X-Run-Passcode", ""), RUN_PASSCODE)

    def _json_body(self) -> dict:
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            return {}
        return body if isinstance(body, dict) else {}

    def _base_result(self, body: dict) -> tuple[str, dict]:
        """หารายงานที่หน้าเว็บเปิดอยู่ — โหมดเฝ้าอัตโนมัติ หรืองานที่ผู้ใช้กดตรวจเอง."""
        target = str(body.get("target") or "monitor")
        base = (monitor.latest_result().get("result") if target == "monitor"
                else (jobs.get_job(target) or {}).get("result"))
        if not base:
            raise ValueError("ไม่พบรายงานที่จะแก้ — ลองตรวจใหม่อีกครั้ง")
        return target, base

    def _store_result(self, target: str, result: dict) -> dict:
        if target == "monitor":
            monitor.replace_result(result)
        else:
            jobs.set_job_result(target, result)
        return {"result": result}

    def _apply_archive(self, body: dict) -> dict:
        """กด 'อ่านแล้ว' → เข้าคลัง (ไม่นับในสถานะ และรอบหน้าไม่ต้องส่งเข้า AI ซ้ำ)."""
        target, base = self._base_result(body)
        wanted = {str(c) for c in (body.get("comment_ids") or []) if str(c).strip()}
        if not wanted:
            raise ValueError("ไม่ได้เลือกคอมเมนต์")

        rows = [c for c in base.get("comments", []) if c.get("comment_id") in wanted]
        if not rows:
            raise ValueError("ไม่พบคอมเมนต์ที่เลือกในรายงานที่เปิดอยู่")

        if body.get("unarchive"):
            archive.remove(c["comment_id"] for c in rows)
        else:
            archive.add(rows)
        return self._store_result(target, jobs.recompute(base))

    def _apply_override(self, body: dict) -> dict:
        """บันทึกคำตัดสินของคน แล้วคืนรายงานที่คิดใหม่ให้หน้าเว็บวาดทับได้เลย."""
        comment_id = str(body.get("comment_id") or "").strip()
        if not comment_id:
            raise ValueError("ไม่มี comment_id")

        target, base = self._base_result(body)
        row = next((c for c in base.get("comments", []) if c.get("comment_id") == comment_id), None)
        if row is None:
            raise ValueError("ไม่พบคอมเมนต์นี้ในรายงานที่เปิดอยู่")

        if body.get("clear"):
            overrides.clear(comment_id)
        else:
            # "AI ทายว่าอะไร" อ่านจากรายงานฝั่ง server เอง — ไม่เชื่อค่าที่หน้าเว็บส่งมา
            # (ถ้าแถวนี้เคยถูกแก้แล้ว ค่าของ AI จะอยู่ใน ai_* ไม่ใช่ sentiment/topics)
            overrides.set_override(
                comment_id,
                sentiment=body.get("sentiment"),
                topics=body.get("topics"),
                note=body.get("note", ""),
                ai_sentiment=row.get("ai_sentiment") or row.get("sentiment", ""),
                ai_topics=(row.get("ai_topics") if row.get("overridden") else row.get("topics")) or [],
            )

        return self._store_result(target, jobs.recompute(base))

    def _apply_alert(self, body: dict) -> dict:
        """กด "แจ้ง Discord" ที่คอมเมนต์จริง — ทางออกของเคสที่ AI อ่านพลาด.

        คอมเมนต์ที่ระบบให้เป็น "กลาง/บวก" จะไม่ถูกแจ้งอัตโนมัติเลย (ตามนิยามคือไม่ใช่เรื่อง)
        คนที่นั่งดูจึงต้องมีปุ่มดันเข้า Discord เองได้ — ไม่งั้นเจอแล้วก็ได้แต่ก็อปไปแปะเอง
        """
        comment_id = str(body.get("comment_id") or "").strip()
        if not comment_id:
            raise ValueError("ไม่มี comment_id")

        target, base = self._base_result(body)
        row = next((c for c in base.get("comments", []) if c.get("comment_id") == comment_id), None)
        if row is None:
            raise ValueError("ไม่พบคอมเมนต์นี้ในรายงานที่เปิดอยู่")

        # ส่งก่อน แล้วค่อยคิดรายงานใหม่ — ป้าย "แจ้งแล้ว" ต้องขึ้นเฉพาะตอนยิงสำเร็จจริง
        rec = notify.send_manual(row, base, note=str(body.get("note") or "")[:300],
                                 page=jobs.get_targets(), force=bool(body.get("force")))
        return {**self._store_result(target, jobs.recompute(base)), "alert": rec}

    def _apply_digest(self, body: dict) -> dict:
        """สรุปประจำวัน 1 ข้อความ — ปลายทางของ n8n Schedule Trigger (ดู n8n/README.md).

        ที่ interval วันละรอบ auto-alert จะเด้งเฉพาะคอมเมนต์ที่เกินเกณฑ์เท่านั้น วันที่ไม่มีเลย
        ทีมจะไม่ได้ยินอะไรจากระบบ — ซึ่งแยกไม่ออกจาก "ระบบตาย" digest จึงส่งทุกวันเสมอ

        refresh=true  → สั่งดึงรอบใหม่ก่อน **ถ้าถึงรอบแล้วเท่านั้น** (monitor เป็นคนตัดสิน)
                        จึงยิงซ้ำกี่ครั้งก็ไม่เกิน 1 scrape ต่อ MONITOR_INTERVAL_MIN — เพดานเครดิต
                        Apify ยังอยู่ที่ค่า interval ไม่ใช่ที่จำนวนครั้งที่ n8n เรียก
        push=true     → Crisis Radar ยิงเข้า n8n webhook เอง (ใช้ตอน cron อยู่ที่อื่นที่ต่อ Discord ไม่ได้)
                        ไม่ใส่ = คืน payload กลับไปให้ผู้เรียกยิงเข้า Discord เอง (ทางหลักของ n8n)
        """
        wait_sec = min(max(int(body.get("wait_sec") or 0), 0), 540)   # cap ใต้ timeout ปกติของ n8n
        if body.get("refresh"):
            monitor.request_refresh()
            deadline = time.time() + wait_sec
            while monitor.snapshot()["refreshing"] and time.time() < deadline:
                time.sleep(3)

        snap = monitor.snapshot()
        if snap["refreshing"]:
            # ยังดึงไม่เสร็จ → บอกให้ผู้เรียกมาใหม่ ไม่ส่งสรุปจากข้อมูลเก่าเงียบ ๆ
            raise TimeoutError(f"ยังดึงข้อมูลไม่เสร็จ ({snap['running_sec']} วิ) — เรียกใหม่อีกครั้ง")

        latest = monitor.latest_result()
        result = latest.get("result")
        if not result:
            raise ValueError("ยังไม่มีผลตรวจให้สรุป — สั่ง refresh ก่อน (หรือรอรอบแรก)")

        # เทียบกับรอบก่อนหน้าเพื่อบอก "ขึ้นหรือลง" — ไม่มีของเทียบก็ไม่ต้องเดาให้
        hist = snap.get("history") or []
        prev = hist[-2] if len(hist) >= 2 else None
        out = notify.digest.send(result, page=jobs.get_targets(), prev=prev,
                                 push=bool(body.get("push")), force=bool(body.get("force")))
        out["data_age_sec"] = snap.get("age_sec")
        out["monitor_error"] = snap.get("error")
        return out

    def do_POST(self) -> None:
        if self.path == "/api/run":
            body = self._json_body()
            if body.get("source") == "facebook" and RUN_PASSCODE and not self._passcode_ok():
                self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                return
            self._send(200, {"job_id": jobs.start_job(body)})
        elif self.path == "/api/override":
            # ทีมแก้ label ที่ AI ทายพลาด → บันทึก แล้วคิดรายงานใหม่ทันทีจากคอมเมนต์ชุดเดิม
            # (ไม่ scrape ซ้ำ ไม่เสียเครดิต) จะได้เห็นเลยว่าสถานะ crisis เปลี่ยนไหม
            # กันด้วยรหัสเดียวกับโหมด Facebook จริง — ลิงก์สาธารณะไม่ควรแก้ label ของทีมได้
            if RUN_PASSCODE and not self._passcode_ok():
                self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                return
            try:
                self._send(200, self._apply_override(self._json_body()))
            except (ValueError, KeyError) as e:
                self._send(400, {"error": str(e)})
        elif self.path == "/api/archive":
            # กด "อ่านแล้ว" — เปลี่ยนตัวเลขบนรายงานเหมือนกัน จึงล็อกด้วยรหัสเดียวกับ override
            if RUN_PASSCODE and not self._passcode_ok():
                self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                return
            try:
                self._send(200, self._apply_archive(self._json_body()))
            except (ValueError, KeyError) as e:
                self._send(400, {"error": str(e)})
        elif self.path == "/api/alert":
            # ยิงข้อความออกนอกระบบ (เข้า Discord ของทีมจริง) → ล็อกด้วยรหัสเดียวกับการแก้ label
            if RUN_PASSCODE and not self._passcode_ok():
                self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                return
            try:
                self._send(200, self._apply_alert(self._json_body()))
            except (ValueError, KeyError) as e:
                self._send(400, {"error": str(e)})
            except RuntimeError as e:
                # ปลายทางล่ม/URL ผิด — แยกจาก 400 เพราะคนกดไม่ได้ทำอะไรผิด ให้ลองใหม่ได้
                self._send(502, {"error": str(e)})
        elif self.path == "/api/digest":
            # ยิงข้อความออกนอกระบบเหมือน /api/alert → ล็อกด้วยรหัสเดียวกัน (n8n ส่ง header มาได้)
            if RUN_PASSCODE and not self._passcode_ok():
                self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                return
            try:
                self._send(200, self._apply_digest(self._json_body()))
            except (ValueError, KeyError) as e:
                self._send(400, {"error": str(e)})
            except TimeoutError as e:
                # 202 = รับเรื่องแล้วแต่ยังไม่พร้อม — n8n ตั้ง retry ทับตรงนี้ได้โดยไม่ต้องมองว่าพัง
                self._send(202, {"pending": True, "error": str(e)})
            except RuntimeError as e:
                self._send(502, {"error": str(e)})
        elif self.path == "/api/monitor/refresh":
            # กด "ตรวจใหม่ตอนนี้" = ข้ามรอบ → ยิง Apify นอกคิว จึงต้องมีรหัสเหมือนโหมด Facebook จริง
            cfg = monitor.config()
            if cfg["source"] == "facebook" and RUN_PASSCODE and not self._passcode_ok():
                self._send(401, {"error": "รหัสผ่านไม่ถูกต้อง"})
                return
            self._send(200, {"started": monitor.request_refresh(force=True)})
        else:
            self._send(404, {"error": "not found"})


def main() -> None:
    ap = argparse.ArgumentParser()
    # ค่า default อ่านจาก env ก่อน — platform อย่าง Render กำหนด PORT ให้เอง
    ap.add_argument("--host", default=os.environ.get("HOST", "127.0.0.1"))
    ap.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)))
    args = ap.parse_args()
    cfg = monitor.config()
    if cfg["enabled"]:
        print(f"👁  เฝ้าเพจอัตโนมัติ: {cfg['page_name'] or cfg['page_url']} "
              f"· แหล่งข้อมูล {cfg['source']} · ตรวจใหม่ทุก {cfg['interval_min']} นาที"
              + ("" if cfg["always"] else " (ตรวจเมื่อมีคนเปิดหน้าเว็บ)"))
    monitor.start_background()
    print(f"📡 Crisis Radar → http://{args.host}:{args.port}  (Ctrl+C เพื่อหยุด)")
    ThreadingHTTPServer((args.host, args.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
