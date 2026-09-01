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
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent))

# ต้องตั้งก่อน import server — ไม่งั้นถ้าเครื่อง dev มี APIFY_TOKEN ใน .env
# ตัวเฝ้าเพจจะยิง Apify จริงตอนรันเทส (เสียเครดิตฟรี ๆ และเทสช้า/ไม่ deterministic)
os.environ["MONITOR_SOURCE"] = "sample"
os.environ["MONITOR_INTERVAL_MIN"] = "60"
# ห้ามยิง Anthropic จริงตอนรันเทส (เครื่อง dev อาจมี ANTHROPIC_API_KEY ใน .env)
# — เสียเงินฟรีและผลไม่ deterministic · ชั้น Claude มีเทสของตัวเองใน tests/run_tests.py (T13)
os.environ["LLM"] = "off"

# ปลายทางแจ้งเตือนต้องไม่ชี้ไป n8n/Discord จริงตอนรันเทส — เดี๋ยวจะยิงเข้าห้องทีมจริง
# (เทสจะตั้ง N8N_WEBHOOK_URL ชี้มา stub ในเครื่องเองตอนถึงหัวข้อ Discord alert)
# RUN_PASSCODE ก็เช่นกัน — ถ้าเครื่อง dev ตั้งรหัสจริงไว้ใน .env (ให้ตรงกับ production) เทสทั้งชุด
# ที่สมมติว่า "ไม่ตั้งรหัส" จะโดน 401 ผิดที่ผิดทาง
#
# ตั้งเป็นสตริงว่าง ไม่ใช่ pop — import server ด้านล่างเรียก load_dotenv() ซึ่งใช้ setdefault()
# เติมค่าจาก .env กลับให้ทุกคีย์ที่ "หายไป" ทันที (pop ทำให้หายไปพอดี) ต้องให้คีย์ยังอยู่ (กัน
# setdefault เติม) แต่ค่าว่าง (falsy เท่ากับไม่ได้ตั้ง ตามจุดที่โค้ดเช็ก `if RUN_PASSCODE:` ฯลฯ)
for _k in ("N8N_WEBHOOK_URL", "DISCORD_WEBHOOK_URL", "N8N_WEBHOOK_SECRET", "DISCORD_ROLE_MAP",
          "RUN_PASSCODE"):
    os.environ[_k] = ""

import monitor  # noqa: E402
import server   # noqa: E402

from src import notify                        # noqa: E402
from src.classify import archive, overrides   # noqa: E402

# เขียน state ลง temp — ห้ามทับผลตรวจจริง/คำตัดสินที่ทีมแก้ไว้บนเครื่องที่รันเทส
_TMP = Path(tempfile.mkdtemp(prefix="crisis-radar-selftest-"))
monitor.STATE_FILE = _TMP / "monitor_latest.json"
monitor.HISTORY_FILE = _TMP / "monitor_history.json"
overrides.STORE = _TMP / "overrides.json"
archive.STORE = _TMP / "archive.json"
notify.alerts.STORE = _TMP / "alerts_sent.json"
# monitor โหลด state เก่าตอน import ไปแล้ว — เคลียร์ให้เทสเริ่มจากศูนย์เสมอ
monitor._STATE.update(result=None, updated_ts=0.0, updated_at="", error=None, error_ts=0.0, history=[])

PORT = 8971
BASE = f"http://127.0.0.1:{PORT}"

HOOK_PORT = 8972
HOOK_HITS: list[dict] = []


class HookHandler(BaseHTTPRequestHandler):
    """n8n ปลอมสำหรับเทส — เก็บ payload ที่ Crisis Radar ยิงมาไว้ตรวจ.

    path '/down' = จำลองปลายทางล่ม (ตอบ 500) เพื่อเช็กว่าเราไม่ไปบันทึกว่า 'ส่งแล้ว'
    """

    def log_message(self, *_):
        pass

    def do_POST(self) -> None:
        n = int(self.headers.get("Content-Length", 0) or 0)
        try:
            body = json.loads(self.rfile.read(n) or b"{}")
        except json.JSONDecodeError:
            body = {}
        HOOK_HITS.append({"path": self.path, "body": body,
                          "token": self.headers.get("X-Crisis-Radar-Token", "")})
        code = 500 if self.path == "/down" else 200
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", "11")
        self.end_headers()
        self.wfile.write(b'{"ok":true}')


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
                                            "fixDlg", "viewSeg", "readAllBtn", "toast",
                                            "alertDlg", "alertSend", "alertHint")))

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

    # 8) แจ้งเตือนเข้า Discord ผ่าน n8n — ทั้งปุ่มที่คนกดเอง และตัวส่งอัตโนมัติ
    hook = ThreadingHTTPServer(("127.0.0.1", HOOK_PORT), HookHandler)
    threading.Thread(target=hook.serve_forever, daemon=True).start()
    time.sleep(0.3)

    base = get("/api/monitor/result")["result"]
    # เคสหลักของปุ่มนี้: AI ให้เป็น "กลาง/บวก" แต่คนอ่านออกว่าเป็นเรื่อง
    calm = next(c for c in base["comments"] if c["sentiment"] != "negative")

    off = post("/api/alert", {"comment_id": calm["comment_id"], "target": "monitor"},
               expect_error=True)
    check("ยังไม่ตั้งปลายทาง → 400 พร้อมบอกว่าต้องตั้ง env ตัวไหน",
          off[0] == 400 and "N8N_WEBHOOK_URL" in off[1].get("error", ""),
          str(off[1].get("error"))[:60])

    os.environ["N8N_WEBHOOK_URL"] = f"http://127.0.0.1:{HOOK_PORT}/hook"
    os.environ["N8N_WEBHOOK_SECRET"] = "s3cr3t"
    os.environ["ALERT_MAX_PER_RUN"] = "2"
    check("health บอกหน้าเว็บว่าปุ่มแจ้ง Discord ใช้ได้แล้ว",
          get("/api/health")["alert"] == {"configured": True, "via": "n8n", "auto": True,
                                          "min_reach": 150},
          json.dumps(get("/api/health")["alert"], ensure_ascii=False))

    sent = post("/api/alert", {"comment_id": calm["comment_id"], "note": "คนอ่านแล้วว่าเป็นเรื่อง",
                               "target": "monitor"})
    hit = HOOK_HITS[-1]
    check("กดปุ่มแจ้ง → ยิงเข้า n8n จริง พร้อม secret ใน header",
          len(HOOK_HITS) == 1 and hit["token"] == "s3cr3t", f"{len(HOOK_HITS)} ครั้ง")
    body = hit["body"]
    check("payload มีข้อมูลดิบให้ n8n route ต่อได้",
          body["trigger"] == "manual" and body["severity"] == "high"
          and body["comment"]["comment_id"] == calm["comment_id"]
          and body["note"] == "คนอ่านแล้วว่าเป็นเรื่อง" and bool(body["routing"]["owner"]),
          f"{body['trigger']}/{body['severity']} · ส่งต่อ {body['routing']['owner']}")
    check("payload มีข้อความ Discord สำเร็จรูป (n8n ยิงต่อได้เลย)",
          bool(body["discord"]["embeds"][0]["title"])
          and calm["text"][:20] in body["discord"]["embeds"][0]["description"]
          and body["discord"]["embeds"][0]["color"] > 0,
          body["discord"]["embeds"][0]["title"][:48])

    row = next(c for c in sent["result"]["comments"] if c["comment_id"] == calm["comment_id"])
    check("ส่งแล้วรายงานจำไว้ (หน้าเว็บขึ้น 'แจ้งแล้ว')",
          bool(row["alerted_at"]) and sent["result"]["alert_sent_count"] == 1
          and sent["alert"]["trigger"] == "manual", row["alerted_at"])

    dup = post("/api/alert", {"comment_id": calm["comment_id"], "target": "monitor"},
               expect_error=True)
    check("กดซ้ำคอมเมนต์เดิม → 400 ไม่เด้งซ้ำใน Discord",
          dup[0] == 400 and len(HOOK_HITS) == 1, str(dup[1].get("error"))[:50])
    post("/api/alert", {"comment_id": calm["comment_id"], "force": True, "target": "monitor"})
    check("แต่ถ้าคนตั้งใจกดส่งซ้ำเอง (force) ต้องส่งได้", len(HOOK_HITS) == 2)

    # ปลายทางล่ม → ต้องไม่บันทึกว่าส่งแล้ว ไม่งั้นเรื่องนี้จะไม่มีใครแจ้งอีกเลย
    os.environ["N8N_WEBHOOK_URL"] = f"http://127.0.0.1:{HOOK_PORT}/down"
    other = next(c for c in base["comments"]
                 if c["sentiment"] != "negative" and c["comment_id"] != calm["comment_id"])
    dead = post("/api/alert", {"comment_id": other["comment_id"], "target": "monitor"},
                expect_error=True)
    check("ปลายทางล่ม → 502 และไม่ถูกทำเครื่องหมายว่าส่งแล้ว",
          dead[0] == 502 and get("/api/monitor/result")["result"]["alert_sent_count"] == 1,
          str(dead[1].get("error"))[:50])

    # ตัวส่งอัตโนมัติ: คอมเมนต์ "ลบและแรง" ต้องเด้งเองตั้งแต่รอบตรวจ ไม่ต้องรอคนเปิดเว็บ
    os.environ["N8N_WEBHOOK_URL"] = f"http://127.0.0.1:{HOOK_PORT}/hook"
    HOOK_HITS.clear()
    post("/api/monitor/refresh", {})
    for _ in range(60):
        if not get("/api/monitor")["refreshing"]:
            break
        time.sleep(0.3)
    autos = [h["body"] for h in HOOK_HITS]
    check("รอบตรวจใหม่แจ้งคอมเมนต์ลบแรงเข้า Discord เอง",
          len(autos) == 2 and all(a["trigger"] == "auto" for a in autos),
          f"{len(autos)} ข้อความ")
    check("เรียงจากคอมเมนต์ที่คนเห็นเยอะสุดก่อน + ไม่เกินโควตาต่อรอบ",
          autos and autos[0]["comment"]["reach"] == max(
              c["reach"] for c in base["comments"] if c["sentiment"] == "negative"),
          f"reach {autos[0]['comment']['reach'] if autos else '-'}")

    after = get("/api/monitor/result")["result"]
    check("คอมเมนต์ที่แจ้งไปแล้วถูกทำเครื่องหมายไว้ครบ",
          after["alert_sent_count"] == 3,
          f"{after['alert_sent_count']} คอมเมนต์")

    HOOK_HITS.clear()
    post("/api/monitor/refresh", {})
    for _ in range(60):
        if not get("/api/monitor")["refreshing"]:
            break
        time.sleep(0.3)
    check("รอบถัดไปไม่แจ้งซ้ำเรื่องเดิม แต่แจ้งตัวใหม่ที่ยังไม่เคยส่ง",
          all(h["body"]["comment"]["comment_id"] not in
              {a["comment"]["comment_id"] for a in autos} for h in HOOK_HITS),
          f"{len(HOOK_HITS)} ข้อความใหม่")

    os.environ["ALERT_AUTO"] = "off"
    HOOK_HITS.clear()
    post("/api/monitor/refresh", {})
    for _ in range(60):
        if not get("/api/monitor")["refreshing"]:
            break
        time.sleep(0.3)
    check("ปิด ALERT_AUTO → ไม่แจ้งอัตโนมัติอีก (เหลือแต่ปุ่มที่คนกด)", len(HOOK_HITS) == 0,
          f"{len(HOOK_HITS)} ข้อความ")

    # 9) สรุปประจำวัน — ปลายทางที่ n8n Schedule Trigger เรียกวันละครั้ง (โหมดดึงวันละรอบ)
    dg = post("/api/digest", {"refresh": True, "wait_sec": 30})
    check("/api/digest คืนสรุปพร้อมยิงเข้า Discord (n8n ไม่ต้องประกอบข้อความเอง)",
          dg["skipped"] is False and dg["event"] == "crisis_radar.daily_digest"
          and len(dg["discord"]["embeds"]) == 1 and bool(dg["report"]["status"]),
          f'สถานะ {dg["report"]["status"]} · top {len(dg["top_negative"])} คอมเมนต์')
    check("สรุปดึงจากผลตรวจล่าสุดจริง ไม่ได้คิดเลขใหม่คนละชุดกับหน้าเว็บ",
          dg["report"]["total"] == get("/api/monitor/result")["result"]["total"],
          f'{dg["report"]["total"]} คอมเมนต์')

    HOOK_HITS.clear()
    dup = post("/api/digest", {"refresh": True})
    check("n8n retry / กด Execute ซ้ำ → ไม่ได้สรุปซ้ำสองใบในวันเดียว (และไม่ยิง webhook)",
          dup["skipped"] is True and not HOOK_HITS and "ส่งไปแล้ว" in dup.get("reason", ""),
          dup.get("reason", ""))

    pushed = post("/api/digest", {"force": True, "push": True})
    check("push:true → Crisis Radar ยิงเข้า n8n เอง (สำหรับ cron ที่อยู่นอก n8n)",
          pushed["pushed"] is True and len(HOOK_HITS) == 1
          and HOOK_HITS[-1]["body"]["event"] == "crisis_radar.daily_digest"
          and HOOK_HITS[-1]["token"] == "s3cr3t",
          f'{len(HOOK_HITS)} ครั้ง · {HOOK_HITS[-1]["body"]["severity"] if HOOK_HITS else "-"}')
    hook.shutdown()

    print("-" * 50)
    print(f"สรุป: {ok} passed, {fail} failed")
    httpd.shutdown()
    return 0 if fail == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
