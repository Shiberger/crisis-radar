#!/usr/bin/env python3
"""ทดสอบ web backend แบบ end-to-end: สตาร์ท server จริง → ยิง HTTP → เช็กผล (โหมด demo, offline)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# ต้องตั้งก่อน import server — ไม่งั้นถ้าเครื่อง dev มี APIFY_TOKEN ใน .env
# ตัวเฝ้าเพจจะยิง Apify จริงตอนรันเทส (เสียเครดิตฟรี ๆ และเทสช้า/ไม่ deterministic)
os.environ["MONITOR_SOURCE"] = "sample"
os.environ["MONITOR_INTERVAL_MIN"] = "60"

import monitor  # noqa: E402
import server   # noqa: E402

from src.classify import archive, overrides  # noqa: E402

# เขียน state ลง temp — ห้ามทับผลตรวจจริง/คำตัดสินที่ทีมแก้ไว้บนเครื่องที่รันเทส
_TMP = Path(tempfile.mkdtemp(prefix="crisis-radar-selftest-"))
monitor.STATE_FILE = _TMP / "monitor_latest.json"
monitor.HISTORY_FILE = _TMP / "monitor_history.json"
overrides.STORE = _TMP / "overrides.json"
archive.STORE = _TMP / "archive.json"
# monitor โหลด state เก่าตอน import ไปแล้ว — เคลียร์ให้เทสเริ่มจากศูนย์เสมอ
monitor._STATE.update(result=None, updated_ts=0.0, updated_at="", error=None, error_ts=0.0, history=[])

PORT = 8971
BASE = f"http://127.0.0.1:{PORT}"


def get(path):
    return json.loads(urllib.request.urlopen(BASE + path, timeout=10).read())


def post(path, body, expect_error=False):
    """expect_error=True → คืน (status, body) แทนที่จะ raise (ใช้เทสเคสที่ต้องถูกปฏิเสธ)."""
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        r = urllib.request.urlopen(req, timeout=30)
        out = json.loads(r.read())
        return (r.status, out) if expect_error else out
    except urllib.error.HTTPError as e:
        if not expect_error:
            raise
        return e.code, json.loads(e.read())


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
                                            "plot", "rows", "prog",
                                            "histStrip", "staleFlag", "monBtn", "wTitle",
                                            "fixDlg", "viewSeg", "readAllBtn", "toast")))

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

    # 5) monitor — เปิดหน้าเว็บแล้วต้องได้ผลเอง โดยไม่มีใครกดปุ่ม
    m = get("/api/monitor")
    check("GET /api/monitor เปิดใช้งานอยู่", m["enabled"] is True and m["source"] == "sample")
    check("เปิดหน้าเว็บ = สั่งตรวจให้เอง", m["refreshing"] is True or m["has_result"] is True)

    for _ in range(60):
        m = get("/api/monitor")
        if not m["refreshing"] and m["has_result"]:
            break
        time.sleep(0.3)
    check("ตรวจอัตโนมัติจนได้ผล", m["has_result"] is True and m["status"] == "CRISIS",
          f"status={m['status']} err={m['error']}")
    check("มีผลตรวจย้อนหลังเก็บไว้", len(m["history"]) >= 1, f"{len(m['history'])} รายการ")
    check("บอกได้ว่าจะตรวจใหม่เมื่อไหร่", m["next_in_sec"] > 0, f"อีก {m['next_in_sec']} วินาที")

    mr = get("/api/monitor/result")
    check("GET /api/monitor/result คืนผลเต็ม",
          mr["result"] and len(mr["result"].get("comments", [])) >= 1)

    # ยังไม่ถึงรอบ → poll ซ้ำต้องไม่ยิงตรวจใหม่ (นี่คือตัวกันเครดิต Apify บาน)
    ts = m["updated_ts"]
    again = get("/api/monitor")
    check("poll ซ้ำก่อนถึงรอบ = ไม่ตรวจใหม่",
          again["refreshing"] is False and again["updated_ts"] == ts)

    # กด "ตรวจใหม่ตอนนี้" = ข้ามรอบได้
    check("POST /api/monitor/refresh สั่งตรวจนอกรอบได้",
          post("/api/monitor/refresh", {})["started"] is True)
    for _ in range(60):
        if not get("/api/monitor")["refreshing"]:
            break
        time.sleep(0.3)

    # 6) ทีมแก้ label ที่ AI ทายพลาด → รายงานต้องคิดใหม่ทันที
    base = get("/api/monitor/result")["result"]
    worst = max((c for c in base["comments"] if c["sentiment"] == "negative"),
                key=lambda c: c["reach"])
    neg_before = base["sentiment_mix"]["negative"]

    fixed = post("/api/override", {"comment_id": worst["comment_id"], "sentiment": "positive",
                                   "topics": ["content/event"], "note": "มุกตลก",
                                   "target": "monitor"})["result"]
    row = next(c for c in fixed["comments"] if c["comment_id"] == worst["comment_id"])
    check("แก้อารมณ์แล้วรายงานคิดใหม่ทันที",
          fixed["sentiment_mix"]["negative"] == neg_before - 1 and fixed["override_count"] == 1,
          f"ลบ {neg_before} → {fixed['sentiment_mix']['negative']}")
    check("แถวที่แก้ถูกทำเครื่องหมาย + เก็บค่าที่ AI ทายไว้",
          row["overridden"] is True and row["sentiment"] == "positive"
          and row["ai_sentiment"] == "negative" and row["topics"] == ["content/event"],
          f"{row['sentiment']} (AI: {row['ai_sentiment']})")
    check("snapshot ของ monitor อัปเดตตาม (โหลดหน้าใหม่ต้องเห็นค่าที่แก้)",
          get("/api/monitor/result")["result"]["override_count"] == 1)
    check("GET /api/overrides คืนรายการที่แก้ไว้",
          worst["comment_id"] in get("/api/overrides")["overrides"])

    reverted = post("/api/override", {"comment_id": worst["comment_id"], "clear": True,
                                      "target": "monitor"})["result"]
    row = next(c for c in reverted["comments"] if c["comment_id"] == worst["comment_id"])
    check("คืนค่าที่ AI ทาย → กลับเป็นเหมือนเดิมทุกอย่าง",
          row["sentiment"] == worst["sentiment"] and row["topics"] == worst["topics"]
          and row["overridden"] is False
          and reverted["sentiment_mix"]["negative"] == neg_before)

    bad = post("/api/override", {"comment_id": worst["comment_id"], "sentiment": "บวก",
                                 "target": "monitor"}, expect_error=True)
    check("อารมณ์ค่ามั่ว → 400 ไม่ใช่พังทั้ง server", bad[0] == 400, str(bad[1].get("error"))[:40])
    ghost = post("/api/override", {"comment_id": "ไม่มีจริง", "sentiment": "positive",
                                   "target": "monitor"}, expect_error=True)
    check("comment_id ที่ไม่มีในรายงาน → 400 (กันขยะลงไฟล์)", ghost[0] == 400)

    # 7) คลัง "อ่านแล้ว" — ออกจากหน้า Monitor, ไม่ถูกนับในสถานะ, และรอบหน้าไม่ส่งเข้า AI ซ้ำ
    base = get("/api/monitor/result")["result"]
    read_ids = [c["comment_id"] for c in base["comments"] if c["sentiment"] == "negative"][:5]
    total_before, neg_before = base["total"], base["sentiment_mix"]["negative"]

    arch = post("/api/archive", {"comment_ids": read_ids, "target": "monitor"})["result"]
    check("กด 'อ่านแล้ว' → ไม่ถูกนับในสถานะ/สถิติ",
          arch["archived_count"] == 5 and arch["total"] == total_before - 5
          and arch["sentiment_mix"]["negative"] == neg_before - 5,
          f"total {total_before} → {arch['total']} · ลบ {neg_before} → {arch['sentiment_mix']['negative']}")
    check("แต่ยังส่งคอมเมนต์ครบให้หน้าเว็บ (เปิดดูคลังย้อนหลังได้)",
          len(arch["comments"]) == len(base["comments"])
          and all(c["archived"] for c in arch["comments"] if c["comment_id"] in read_ids))

    # จุดที่ประหยัด token จริง — รอบ scrape ถัดไปต้องข้ามตัวที่อยู่ในคลัง
    post("/api/monitor/refresh", {})
    for _ in range(60):
        m = get("/api/monitor")
        if not m["refreshing"]:
            break
        time.sleep(0.3)
    logs = "\n".join(m["logs"])
    after = get("/api/monitor/result")["result"]
    check("scrape รอบใหม่ข้ามคอมเมนต์ที่อ่านแล้ว (ไม่เรียก AI ซ้ำ)",
          "ข้าม 5 คอมเมนต์ที่ทีมอ่านแล้ว" in logs and after["archived_count"] == 5,
          next((line for line in m["logs"] if "ข้าม" in line), "ไม่เจอ log"))

    back = post("/api/archive", {"comment_ids": read_ids, "unarchive": True,
                                 "target": "monitor"})["result"]
    check("เอากลับจากคลัง → กลับมานับตามเดิม",
          back["archived_count"] == 0 and back["total"] == total_before
          and back["sentiment_mix"]["negative"] == neg_before,
          f"total={back['total']} ลบ={back['sentiment_mix']['negative']}")

    empty = post("/api/archive", {"comment_ids": [], "target": "monitor"}, expect_error=True)
    check("ไม่ได้เลือกคอมเมนต์ → 400", empty[0] == 400)
    junk = post("/api/archive", {"comment_ids": ["ไม่มีจริง"], "target": "monitor"},
                expect_error=True)
    check("comment_id มั่ว → 400 (กันขยะลงคลัง)", junk[0] == 400)

    print("-" * 50)
    print(f"สรุป: {ok} passed, {fail} failed")
    httpd.shutdown()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
