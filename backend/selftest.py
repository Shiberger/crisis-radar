#!/usr/bin/env python3
"""ทดสอบ web backend แบบ end-to-end: สตาร์ท server จริง → ยิง HTTP → เช็กผล (โหมด demo, offline)."""
from __future__ import annotations

import json
import sys
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

import server  # noqa: E402

PORT = 8971
BASE = f"http://127.0.0.1:{PORT}"


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=10).read())


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    return json.loads(urllib.request.urlopen(req, timeout=10).read())


def main() -> int:
    httpd = ThreadingHTTPServer(("127.0.0.1", PORT), server.Handler)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    time.sleep(0.4)

    ok = 0
    fail = 0

    def check(name, cond, detail=""):
        nonlocal ok, fail
        print(("[PASS] " if cond else "[FAIL] ") + name + (f" — {detail}" if detail else ""))
        ok += cond; fail += (not cond)

    # 1) health
    check("health endpoint", get("/api/health").get("ok") is True)

    # 2) หน้าเว็บ index โหลดได้
    html = urllib.request.urlopen(BASE + "/", timeout=10).read().decode()
    # เช็ค id ของ element ที่ JS ผูกไว้ ไม่เช็คข้อความบนปุ่ม — ข้อความปรับถ้อยคำได้เรื่อย ๆ
    check("หน้าเว็บ index โหลดได้ + มี element หลักครบ",
          all(f'id="{i}"' in html for i in ("runBtn", "results", "verdict", "kpis", "alerts",
                                            "plot", "rows", "prog")))

    # 3) กดปุ่ม (โหมด demo) → poll จนเสร็จ
    job_id = post("/api/run", {"source": "sample"})["job_id"]
    check("POST /api/run คืน job_id", bool(job_id), job_id)

    result = None
    for _ in range(30):
        j = get("/api/jobs/" + job_id)
        if j["status"] in ("done", "error"):
            result = j
            break
        time.sleep(0.3)

    check("job เสร็จสถานะ done", result and result["status"] == "done",
          result["status"] if result else "timeout")
    if result and result["result"]:
        r = result["result"]
        check("ผลลัพธ์เป็น CRISIS (ตรงกับ sample)", r["status"] == "CRISIS", r["status"])
        check("มี alert", len(r["alerts"]) >= 1, f"{len(r['alerts'])} alert")
        check("มีรายการคอมเมนต์ (comments)", len(r.get("comments", [])) >= 1, f"{len(r.get('comments',[]))}")
        check("comment มี field author/text/sentiment", all(k in (r["comments"][0]) for k in ("author", "text", "sentiment")))
        check("มี timeline buckets", len(r.get("buckets", [])) >= 1, f"{len(r.get('buckets',[]))}")

    # 4) job ไม่มีจริง → 404
    try:
        urllib.request.urlopen(BASE + "/api/jobs/nope", timeout=5)
        check("job มั่ว → 404", False)
    except urllib.error.HTTPError as e:
        check("job มั่ว → 404", e.code == 404, str(e.code))

    print("-" * 50)
    print(f"สรุป: {ok} passed, {fail} failed")
    httpd.shutdown()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
