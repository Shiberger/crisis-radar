#!/usr/bin/env python3
"""Test runner ของ Crisis Radar — รันได้ offline ทั้งหมด, พิมพ์ผลจริง.

รัน:  python tests/run_tests.py
ครอบคลุม:
  T1  sentiment accuracy (lexicon-only vs hybrid) บน labeled set
  T2  ชั้น LLM แก้เคสประชดได้จริง (hybrid > lexicon)
  T3  crisis detection: sample จริงต้องได้สถานะ CRISIS + เจอ spike
  T4  calm scenario: ไม่มี spike → ต้องไม่ alert
  T5  PII masking: ชื่อจริงต้องไม่หลุดใน output
  T6  connector interface: sample source คืน field ครบ
  T8  topic tagging: 'ของรางวัล/โค้ด' ต้องไม่หลงคำว่า 'โค้ด' ที่แปลว่า program code
  T9  per-topic trend: ดราม่าเล็กไม่ถูก spike ใหญ่กลบ + route ให้ทีมถูก
  T10 คนตัดสินทับ AI: แก้ label ที่ AI อ่านผิดแล้ว crisis ต้องคิดใหม่ตามจริง
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "backend"))   # jobs.build_result — ก้อนผลจริงที่หน้าเว็บ/สรุปรายวันใช้

# เทสต้องออฟไลน์ 100% และผลต้องเหมือนเดิมทุกครั้ง — ห้ามยิง Anthropic จริงแม้เครื่องจะมีคีย์อยู่
# (T13 ทดสอบชั้น Claude ด้วยการสลับตัวส่ง ไม่ใช่ด้วยการต่อเน็ตจริง)
os.environ["LLM"] = "off"

import jobs                                          # noqa: E402  (backend/jobs.py)
from src.classify import archive, lexicon, overrides   # noqa: E402
from src.classify.llm import ResultCache               # noqa: E402
from src.classify.pipeline import HybridClassifier     # noqa: E402
from src.crisis import detector                        # noqa: E402
from src.models import Classified, Comment             # noqa: E402
from src.notify import alerts as notify                # noqa: E402
from src.security import mask_author                    # noqa: E402
from src.sources.sample import SampleFacebookSource    # noqa: E402

FIXTURE = ROOT / "data" / "sample_talesrunner_fb_comments.json"
LABELED = json.loads((ROOT / "tests" / "labeled_test_set.json").read_text(encoding="utf-8"))

passed, failed = 0, 0
results: list[str] = []


def check(name: str, cond: bool, detail: str = "") -> None:
    global passed, failed
    mark = "PASS" if cond else "FAIL"
    if cond:
        passed += 1
    else:
        failed += 1
    results.append(f"[{mark}] {name}" + (f" — {detail}" if detail else ""))


def _mk_comment(text: str) -> Comment:
    return Comment("facebook", "p/x", "x", "user", text, datetime(2026, 7, 15, 14, 0))


# ---- T1 & T2: sentiment accuracy + LLM lift ----
cases = LABELED["cases"]
clf = HybridClassifier()

lex_correct = hybrid_correct = 0
confusion = {"positive": {}, "neutral": {}, "negative": {}}
for c in cases:
    gold = c["gold"]
    lex = lexicon.classify(c["text"])["sentiment"]
    hyb = clf.classify_one(_mk_comment(c["text"])).sentiment
    lex_correct += (lex == gold)
    hybrid_correct += (hyb == gold)
    confusion[gold][hyb] = confusion[gold].get(hyb, 0) + 1

n = len(cases)
lex_acc = lex_correct / n
hyb_acc = hybrid_correct / n
check("T1 hybrid sentiment accuracy ≥ 0.8", hyb_acc >= 0.8, f"{hyb_acc:.0%} ({hybrid_correct}/{n})")
check("T2 ชั้น LLM ยกระดับ accuracy (hybrid ≥ lexicon-only)", hyb_acc >= lex_acc,
      f"lexicon {lex_acc:.0%} → hybrid {hyb_acc:.0%}")

# sarcasm subset
sar = [c for c in cases if c.get("hard") == "sarcasm"]
sar_hyb = sum(clf.classify_one(_mk_comment(c["text"])).sentiment == c["gold"] for c in sar)
check("T2b เคสประชด hybrid จับถูก ≥ ครึ่ง", sar_hyb >= len(sar) / 2, f"{sar_hyb}/{len(sar)}")

# ---- T3: crisis detection บน sample จริง ----
comments = SampleFacebookSource(FIXTURE).fetch()
classified = clf.classify_all(comments)
rep = detector.detect(classified, brand="talesrunner")
check("T3 sample → สถานะ CRISIS", rep.status == "CRISIS", f"status={rep.status}")
check("T3b เจอ spike อย่างน้อย 1 ช่วง", any(b.is_spike for b in rep.buckets),
      f"{sum(b.is_spike for b in rep.buckets)} ช่วง")
check("T3c มี alert อย่างน้อย 1", len(rep.alerts) >= 1, f"{len(rep.alerts)} alert")

# ---- T4: calm scenario ไม่ควร alert ----
calm = [Classified(_mk_comment("เกมสนุกดีชอบมาก"), "positive", 0.9) for _ in range(20)]
calm_rep = detector.detect(calm, brand="test")
check("T4 calm → ไม่มี spike", not any(b.is_spike for b in calm_rep.buckets), f"status={calm_rep.status}")

# ---- T5: mask util (ยังใช้ตอน export/แชร์ภายนอก) ----
m1, m2 = mask_author("Somchai R"), mask_author("Somchai R")
check("T5 mask_author util (stable + non-reversible)",
      m1 == m2 and m1.startswith("user_") and "Somchai" not in m1, m1)

# ---- T6: connector interface ----
sample_c = comments[0]
has_fields = all(getattr(sample_c, f, None) is not None
                 for f in ("platform", "comment_id", "author", "text", "created_at"))
check("T6 connector คืน field ครบตาม interface", has_fields and len(comments) > 0, f"{len(comments)} comments")

# ---- T7: กรอง admin / โฆษณา (IDRLAB) / เพจ ออก ----
from src.sources.facebook_apify import filter_noise   # noqa: E402
noise = [
    {"author": "Player X", "text": "เกมสนุกดีชอบมาก", "profile_url": "https://facebook.com/playerx"},
    {"author": "IDRLAB", "text": "บริการกู้ข้อมูล ปรึกษาฟรี LINE : @idrlab โทร 094-692-8080",
     "profile_url": "https://facebook.com/idrlab"},
    {"author": "Tales Runner", "text": "ประกาศจากทีมงาน", "profile_url": "https://facebook.com/thehof.talesrunner"},
]
kept, dropped = filter_noise(noise, page_id="thehof.talesrunner", exclude_authors=["Tales Runner", "IDRLAB"])
check("T7 กรอง admin/โฆษณา (IDRLAB/เพจ) ออก เหลือแต่ผู้เล่น", len(kept) == 1 and dropped == 2,
      f"kept={len(kept)} dropped={dropped}")

# ---- T8: category rewards/redeem จับถูก + ไม่หลงคำว่า 'โค้ด' ที่แปลว่า program code ----
topic_cases = [c for c in cases if "topic" in c]
t8_ok = 0
t8_miss: list[str] = []
for c in topic_cases:
    want = c["topic"]
    tags = lexicon.tag_topics(c["text"])
    ok = (want[1:] not in tags) if want.startswith("!") else (want in tags)
    t8_ok += ok
    if not ok:
        t8_miss.append(c["text"][:30])
check("T8 category rewards/redeem ถูกต้อง (รวมเคสหลอก 'เขียนโค้ด')",
      t8_ok == len(topic_cases), f"{t8_ok}/{len(topic_cases)}" + (f" · พลาด: {t8_miss}" if t8_miss else ""))

# ---- T9: per-topic trend — ดราม่าเล็กต้องไม่ถูกกลบ + route ให้ทีมถูก ----
rewards = next((t for t in rep.topic_trends if t.topic == "rewards/redeem"), None)
check("T9 จับประเด็น 'ของรางวัล/โค้ด' ที่มาทีหลังได้ (ไม่ถูก spike ใหญ่กลบ)",
      rewards is not None and rewards.is_emerging,
      f"emerging={getattr(rewards, 'is_emerging', None)} · severity={getattr(rewards, 'severity', 0)}")
check("T9b alert ระบุทีมที่ต้องรับเรื่อง", bool(rewards) and "Marketing" in rewards.owner,
      getattr(rewards, "owner", "-"))

# ---- T10: คนตัดสินทับ AI — AI อ่านมุกตลกเป็นคำบ่น ทีมต้องแก้ได้ แล้ว crisis คิดใหม่ตาม ----
# เคสจริงจากเพจ: "รำคาญหัวเด้งสุดละ…👋" — lexicon เจอ 'รำคาญ'+'เด้ง' → ตัดสินเป็นลบ
# ทั้งที่คนอ่านออกว่าหยอกเล่น ถ้าไม่มีทางแก้ ตัวเลขคอมเมนต์ลบจะเฟ้อและ crisis เตือนผิด
JOKE = "รำคาญหัวเด้งสุดละไม่มีไรแก้ทางเลยนอกจากไปเล่นร้านเกมแล้วมันนั่งอยู่ข้างๆ 👋"
joke_item = Classified(comment=_mk_comment(JOKE), sentiment="negative", confidence=0.8,
                       topics=["bug/technical"])
check("T10 AI ตัดสินมุกตลกนี้เป็นลบ (คือปัญหาที่ต้องมีทางแก้)",
      clf.classify_one(_mk_comment(JOKE)).sentiment == "negative",
      f"AI → {clf.classify_one(_mk_comment(JOKE)).sentiment}")

store = {joke_item.comment.comment_id: {"sentiment": "positive", "topics": [],
                                        "ai_sentiment": "negative", "ai_topics": ["bug/technical"]}}
n = overrides.apply([joke_item], store)
check("T10b override ทับ label ของ AI ได้",
      n == 1 and joke_item.sentiment == "positive" and joke_item.topics == [] and joke_item.overridden,
      f"{joke_item.sentiment} · topics={joke_item.topics}")
check("T10c เก็บค่าที่ AI ทายไว้เดิมด้วย (ตรวจย้อนหลัง/เอาไปปรับ lexicon ได้)",
      joke_item.ai_sentiment == "negative" and joke_item.ai_topics == ["bug/technical"],
      f"{joke_item.ai_sentiment} · {joke_item.ai_topics}")

# กรณีที่พลาดง่ายสุด: AI ไม่ได้จัดประเด็นไว้เลย (ลิสต์ว่าง) แล้วคนเพิ่มประเด็นเอง
# ถ้าโค้ดเช็ก "ค่าว่าง = ไม่มีข้อมูล" ค่าเดิมของ AI จะกู้กลับไม่ได้ตอนกดคืนค่า
blank = Classified(comment=_mk_comment("เกมเด้งอีกแล้ว"), sentiment="neutral", confidence=0.4, topics=[])
overrides.apply([blank], {blank.comment.comment_id: {"topics": ["bug/technical"],
                                                     "ai_sentiment": "neutral", "ai_topics": []}})
check("T10d AI ไม่ได้จัดประเด็นไว้เลย → ยังคืนค่าเดิมได้ถูก",
      blank.topics == ["bug/technical"] and blank.ai_topics == [],
      f"topics={blank.topics} · ai_topics={blank.ai_topics}")

# override ต้องเปลี่ยนผลตรวจ crisis จริง ไม่ใช่แค่เปลี่ยนสีในตาราง
worst = max((c for c in classified if c.sentiment == "negative"), key=lambda c: c.comment.reach)
calmed = [Classified.from_dict(c.to_dict()) for c in classified]
overrides.apply(calmed, {c.comment.comment_id: {"sentiment": "neutral", "ai_sentiment": "negative"}
                         for c in classified if c.sentiment == "negative"})
after = detector.detect(calmed, brand="talesrunner")
check("T10e ทีมแก้คอมเมนต์ลบทั้งหมด → crisis หายจริง (ไม่ใช่แค่หน้าจอ)",
      rep.status == "CRISIS" and after.status == "NORMAL" and not after.alerts,
      f"{rep.status} → {after.status} · alert {len(after.alerts)}")
check("T10f round-trip dict ไม่ทำข้อมูลหาย (ใช้ตอนคิดรายงานใหม่โดยไม่ scrape ซ้ำ)",
      Classified.from_dict(worst.to_dict()).to_dict() == worst.to_dict())

# ---- T11: คลัง "อ่านแล้ว" — เอาออกจากหน้า Monitor + ไม่ส่งเข้า AI ซ้ำรอบหน้า ----
# (ทดสอบด้วย store dict ตรง ๆ ไม่แตะไฟล์จริงของเครื่องที่รันเทส)
read_ids = [c.comment.comment_id for c in classified if c.sentiment == "negative"]
arch_store = {cid: {"at": "2026-07-27T18:00+07:00",
                    "item": next(c.to_dict() for c in classified if c.comment.comment_id == cid)}
              for cid in read_ids}

marked = [Classified.from_dict(c.to_dict()) for c in classified]
n_arch = archive.apply(marked, arch_store)
unread = [c for c in marked if not c.archived]
rep_read = detector.detect(unread, brand="talesrunner")
check("T11 คอมเมนต์ในคลังไม่ถูกนับในสถานะ/spike",
      n_arch == len(read_ids) and rep.status == "CRISIS" and rep_read.status == "NORMAL",
      f"อ่านแล้ว {n_arch} → {rep.status} กลายเป็น {rep_read.status}")
check("T11b คอมเมนต์ที่ยังไม่ได้อ่านยังอยู่ครบ (ไม่ได้ลบทิ้ง)",
      len(marked) == len(classified) and len(unread) == len(classified) - len(read_ids),
      f"ทั้งหมด {len(marked)} · ยังไม่อ่าน {len(unread)}")

# จุดที่ประหยัด token: ตัวที่อยู่ในคลังต้องไม่ถูกส่งเข้า classifier รอบถัดไป
raw = SampleFacebookSource(FIXTURE).fetch()
fresh_c, known_c = archive.partition(raw, arch_store)
check("T11c รอบ scrape ถัดไปแยกตัวที่อ่านแล้วออกก่อนเรียก AI",
      len(known_c) == len(read_ids) and len(fresh_c) == len(raw) - len(read_ids),
      f"ส่งเข้า AI {len(fresh_c)} · ข้าม {len(known_c)} จาก {len(raw)}")

# ยอดไลก์ต้องอัปเดตตามข้อมูลสด แต่ label ต้องเป็นของเดิม (ไม่เรียก AI ใหม่)
bumped = [c for c in known_c]
bumped[0].reach += 999
revived = archive.rehydrate(bumped, arch_store)
old = arch_store[bumped[0].comment_id]["item"]
check("T11d ใช้ label เดิม แต่ยอดไลก์เป็นข้อมูลสด",
      revived[0].sentiment == old["sentiment"] and revived[0].topics == old["topics"]
      and revived[0].comment.reach == old["reach"] + 999 and revived[0].archived,
      f"{revived[0].sentiment} · reach {old['reach']} → {revived[0].comment.reach}")

# ---- T12: แจ้งเตือน Discord — เกณฑ์ "เรื่องไหนคุ้มที่จะไปรบกวนคน" ----
# ไม่ยิงเน็ตจริง: สลับตัวส่งเป็นตัวเก็บ payload แล้วตรวจว่าเลือกคอมเมนต์ถูกตัวไหม
notify.STORE = Path(tempfile.mkdtemp(prefix="crisis-radar-tests-")) / "alerts_sent.json"
os.environ.update(N8N_WEBHOOK_URL="http://127.0.0.1:1/stub", ALERT_MIN_REACH="150",
                  ALERT_MAX_PER_RUN="2")
os.environ.pop("ALERT_AUTO", None)
os.environ.pop("DISCORD_ROLE_MAP", None)

fired: list[dict] = []
notify._post = lambda cfg, event: fired.append(event)

report = detector.report_to_dict(rep)
round1 = [Classified.from_dict(c.to_dict()) for c in classified]
recs = notify.dispatch_auto(round1, report)
picked = [e["comment"] for e in fired]
worst_neg = max(c.comment.reach for c in classified if c.sentiment == "negative")
check("T12 แจ้งเองเฉพาะคอมเมนต์ลบ เรียงจากคนเห็นเยอะสุด และไม่เกินโควตาต่อรอบ",
      len(recs) == 2 and picked[0]["reach"] == worst_neg
      and all(p["sentiment"] == "negative" for p in picked)
      and all(e["trigger"] == "auto" for e in fired),
      f"{len(recs)} ข้อความ · reach {[p['reach'] for p in picked]}")
check("T12b คอมเมนต์ที่แจ้งไปแล้วถูกทำเครื่องหมายไว้ (หน้าเว็บขึ้น 'แจ้งแล้ว')",
      sum(1 for c in round1 if c.alerted_at) == 2)

# รอบตรวจถัดไปได้คอมเมนต์เดิมกลับมาทั้งชุด — ห้ามเด้งเรื่องเดิมซ้ำ
fired.clear()
round2 = [Classified.from_dict(c.to_dict()) for c in classified]
notify.dispatch_auto(round2, report)
check("T12c รอบถัดไปไม่แจ้งเรื่องเดิมซ้ำ (ไล่ลงไปที่ตัวใหม่แทน)",
      {e["comment"]["comment_id"] for e in fired}.isdisjoint({p["comment_id"] for p in picked}),
      f"ชุดใหม่ {[e['comment']['reach'] for e in fired]}")

# หัวใจของปุ่มบนหน้าเว็บ: เคสที่ AI ให้เป็น "กลาง/บวก" ระบบจะไม่มีวันแจ้งเอง — คนต้องดันเข้าไปเอง
calm = next(c for c in classified if c.sentiment != "negative")
fired.clear()
notify.dispatch_auto([Classified.from_dict(calm.to_dict())], report)
check("T12d คอมเมนต์ที่ AI ให้เป็นกลาง/บวก ไม่ถูกแจ้งอัตโนมัติเลย", not fired)

rec = notify.send_manual(calm.to_dict(), report, note="คนอ่านแล้วว่าเป็นเรื่อง")
ev = fired[-1]
check("T12e คนกดปุ่มแจ้งเองได้ และข้อความบอกชัดว่ามาจากคน ไม่ใช่ระบบ",
      rec["trigger"] == "manual" and ev["severity"] == "high"
      and ev["note"] == "คนอ่านแล้วว่าเป็นเรื่อง"
      and "ทีมส่งเรื่องนี้เข้ามาเอง" in ev["discord"]["embeds"][0]["title"],
      ev["discord"]["embeds"][0]["title"][:46])
check("T12f payload พร้อมให้ n8n ส่งต่อ (ข้อความ Discord + ทีมเจ้าของเรื่อง)",
      bool(ev["routing"]["owner"]) and ev["discord"]["embeds"][0]["color"] > 0
      and calm.comment.text[:20] in ev["discord"]["embeds"][0]["description"],
      f"ส่งต่อ {ev['routing']['owner']}")

# ---- T12g–T12k: สรุปประจำวัน (โหมดดึงวันละรอบ) ----
# ต่างจาก alert รายคอมเมนต์: ต้องส่ง "ทุกวัน" แม้วันที่ไม่มีอะไรเลย ไม่งั้นทีมแยกไม่ออกว่า
# เงียบเพราะปกติดี หรือเงียบเพราะ scraper ตาย
from src.notify import digest as digest_mod             # noqa: E402

full = jobs.build_result([Classified.from_dict(c.to_dict()) for c in classified], source="sample")
page = {"page_name": "TalesRunner TH", "page_url": "https://facebook.com/x"}

fired.clear()
d1 = digest_mod.send(full, page=page, prev={"negative": 5, "total": 40}, push=True)
dev = fired[-1]
embed = dev["discord"]["embeds"][0]
body = json.dumps(embed, ensure_ascii=False)
check("T12g สรุปรวมทั้งรอบเป็นข้อความเดียว (ไม่ใช่คอมเมนต์ละใบ)",
      len(fired) == 1 and dev["event"] == "crisis_radar.daily_digest"
      and len(dev["discord"]["embeds"]) == 1,
      f'{len(fired)} ข้อความ · {dev["event"]}')
check("T12h บอกส่วนต่างจากรอบก่อน — ตัวเลขเดี่ยว ๆ อ่านไม่ออกว่าดีขึ้นหรือแย่ลง",
      f'+{full["sentiment_mix"]["negative"] - 5} จากรอบก่อน' in body,
      f'ลบ {full["sentiment_mix"]["negative"]} · รอบก่อน 5')
top_reach = [t["reach"] for t in dev["top_negative"]]
check("T12i ชูคอมเมนต์ลบที่คนเห็นเยอะสุดขึ้นมาให้อ่านก่อน",
      top_reach == sorted(top_reach, reverse=True) and len(top_reach) == 3
      and all(t["sentiment"] == "ลบ" for t in dev["top_negative"]),
      f"reach {top_reach}")

# n8n retry / มีคนกด Execute เอง ต้องไม่ทำให้ทีมได้สรุปซ้ำสองใบในวันเดียว
fired.clear()
again = digest_mod.send(full, page=page, push=True)
check("T12j เรียกซ้ำในวันเดียวกันไม่ส่งซ้ำ (n8n retry ได้โดยไม่ต้องกลัว)",
      again["skipped"] and not fired, again.get("reason", ""))

# วันที่เพจปกติดี: ยังต้องส่ง และต้องไม่ ping ใครให้รำคาญ
os.environ["DISCORD_ROLE_MAP"] = json.dumps({"bug/technical": "999"})
calm_items = [Classified(_mk_comment("เกมสนุกดีชอบมาก"), "positive", 0.9) for _ in range(20)]
calm_result = jobs.build_result(calm_items, source="sample")
fired.clear()
digest_mod.send(calm_result, page=page, push=True, force=True)
calm_ev = fired[-1]
check("T12k วันที่ปกติก็ยังส่ง (เป็นสัญญาณชีพของระบบ) แต่ไม่ ping ใคร",
      calm_ev["report"]["status"] == "NORMAL" and calm_ev["discord"]["content"] == ""
      and calm_ev["severity"] == "low",
      f'สถานะ {calm_ev["report"]["status"]} · content ว่าง = ไม่ ping')
os.environ.pop("DISCORD_ROLE_MAP", None)

# ---- T13: ชั้น LLM จริง (Claude) — ประกอบ request / แกะคำตอบ / กันพัง ----
# ไม่ยิงเน็ต: สลับเฉพาะตัวส่ง HTTP (_post) เป็นตัวปลอม แล้วตรวจว่าที่เหลือทำงานถูก
from src.classify import llm as llm_mod                 # noqa: E402

llm_cache = ResultCache(Path(tempfile.mkdtemp(prefix="crisis-radar-llm-")) / "cache.json")


def fake_api(results, stop_reason="end_turn"):
    """สร้าง response แบบที่ Anthropic Messages API ตอบกลับจริง (รูปย่อ i/s/c/t)."""
    return {"stop_reason": stop_reason,
            "content": [{"type": "text", "text": json.dumps({"r": results})}],
            "usage": {"input_tokens": 900, "output_tokens": 120}}


sarcasm = "ดีจริง ๆ นะคะที่ล่มตอนคนกำลังจะเล่น ขอบคุณมากค่า"
joke = "รำคาญหัวเด้งสุดละไม่มีไรแก้ทางเลย 😂"
sent_bodies: list[dict] = []
claude = llm_mod.ClaudeLLM("sk-ant-test", batch_size=10, cache=llm_cache)
claude._post = lambda body: (sent_bodies.append(body), fake_api([
    {"i": 1, "s": "neg", "c": 1.7, "t": ["b", "zz"]},     # conf เกิน 1 + รหัส topic มั่ว
    {"i": 2, "s": "neu", "c": 0.6, "t": []},
]))[1]

got = claude.analyze_batch([(sarcasm, []), (joke, [])])
body = sent_bodies[0]
check("T13 ส่งหลายคอมเมนต์ใน request เดียว (จุดที่ทำให้ค่า API ไม่บาน)",
      len(sent_bodies) == 1 and body["messages"][0]["content"].startswith("[1] ")
      and "[2] " in body["messages"][0]["content"],
      f"{len(sent_bodies)} request ต่อ 2 คอมเมนต์")
schema = body["output_config"]["format"]["schema"]["properties"]["r"]["items"]["properties"]
check("T13b บังคับรูปคำตอบด้วย structured outputs (รูปย่อ) + ใช้ model ที่ตั้งใจ",
      body["output_config"]["format"]["type"] == "json_schema"
      and sorted(schema) == ["c", "i", "s", "t"]          # ชื่อ field สั้น = ประหยัด output token
      and body["model"] == "claude-haiku-4-5" and "effort" not in body.get("output_config", {}),
      f"{body['model']} · field: {sorted(schema)}")
check("T13c แปลรหัสย่อกลับเป็นชื่อเต็มถูกตัว + กันค่าเพี้ยน",
      got[0]["sentiment"] == "negative" and got[0]["confidence"] == 1.0
      and got[0]["topics"] == ["bug/technical"] and got[1]["sentiment"] == "neutral",
      f"neg→{got[0]['sentiment']} · b→{got[0]['topics']} · conf 1.7 → {got[0]['confidence']}")

before = len(sent_bodies)
again = claude.analyze_batch([(sarcasm, [])])
check("T13d ถามซ้ำข้อความเดิมไม่เสียเงินอีก (รอบตรวจหน้าได้คอมเมนต์เดิมกลับมา)",
      len(sent_bodies) == before and again[0]["sentiment"] == "negative"
      and claude.usage["cached_hits"] == 1)
check("T13e นับ token + ประเมินค่าใช้จ่ายได้",
      claude.usage["input_tokens"] == 900 and claude.cost_usd() > 0,
      claude.usage_line())

# ตอบมาไม่ครบ / โดนปฏิเสธ / API ล่ม — ทั้ง 3 เคสต้องไม่ทำให้รอบตรวจพัง
partial = llm_mod.ClaudeLLM("sk-ant-test", cache=ResultCache(llm_cache.path.with_name("b.json")))
partial._post = lambda body: fake_api([{"i": 1, "s": "neg", "c": 0.8, "t": []}])
res = partial.analyze_batch([(sarcasm, []), (joke, [])])
check("T13f ตอบมาไม่ครบทุกหมายเลข → ช่องที่ขาดเป็น None (ไม่เดาว่าเป็นกลาง)",
      res[0] is not None and res[1] is None)

refused = llm_mod.ClaudeLLM("sk-ant-test", cache=ResultCache(llm_cache.path.with_name("c.json")))
refused._post = lambda body: fake_api([], stop_reason="refusal")
check("T13g โดนปฏิเสธ (stop_reason=refusal) → ไม่พัง คืน None", refused.analyze_batch(
    [(sarcasm, [])]) == [None])

dead = llm_mod.ClaudeLLM("sk-ant-test", cache=ResultCache(llm_cache.path.with_name("d.json")))


def _boom(_body):
    raise RuntimeError("HTTP 500")


dead._post = _boom
# ต้องใช้คอมเมนต์ที่กฎชั้น 2 ตัดสินไม่ได้ ถึงจะไปถึงชั้น AI แล้วเจอ API ล่ม
AMBIG = "เกมโหลดช้านิดนึงตอนเข้า แต่พอเข้าได้ก็โอเค"
hybrid = HybridClassifier(llm=dead, log=lambda _m: None)
fallback_out = hybrid.classify_all([_mk_comment(AMBIG), _mk_comment("แผนที่ใหม่สวยดีนะ")])
check("T13h API ล่มทั้งชุด → ตกไปใช้ตัวสำรอง รอบตรวจยังได้ผลครบ",
      len(fallback_out) == 2 and fallback_out[0].sentiment in ("negative", "neutral")
      and dead.usage["failed"] == 1 and hybrid.stats["to_llm"] == 1,
      f"{fallback_out[0].sentiment} (จากตัวสำรอง)")

capped_bodies: list[dict] = []
capped = llm_mod.ClaudeLLM("sk-ant-test", cache=ResultCache(llm_cache.path.with_name("e.json")))
capped._post = lambda body: (capped_bodies.append(body), fake_api(
    [{"i": i + 1, "s": "neg", "c": 0.8, "t": []}
     for i in range(len(body["messages"][0]["content"].splitlines()))]))[1]
ambiguous = [_mk_comment("คิดถึงเพื่อนเก่าในเกมจัง กลับมาเล่นกันเถอะ"),
             _mk_comment("อยากได้ตัวละครใหม่ ๆ บ้างอะ เล่นตัวเดิมนานแล้ว"),
             _mk_comment("ตอนนี้เข้าได้แล้วนะ ลองรีสตาร์ทเราเตอร์ดู")]
capped_out = HybridClassifier(llm=capped, max_llm_items=1, log=lambda _m: None).classify_all(ambiguous)
sent_lines = capped_bodies[0]["messages"][0]["content"].splitlines() if capped_bodies else []
check("T13i เพดานต่อรอบคุมค่าใช้จ่ายได้จริง (ส่วนเกินใช้ผลชั้นแรก ไม่เข้า AI)",
      len(sent_lines) == 1 and sum(1 for c in capped_out if c.escalated_to_llm) == 1
      and len(capped_out) == 3,
      f"ส่งเข้า Claude {len(sent_lines)} จาก {len(ambiguous)} คอมเมนต์")

check("T13j ไม่มีคีย์ → ใช้ตัวสำรองอัตโนมัติ ไม่ใช่พัง",
      llm_mod.from_env().name == "offline-heuristic")

# เจอจริงตอนต่อ API ครั้งแรก: Python บน mac หา CA bundle ไม่เจอ → CERTIFICATE_VERIFY_FAILED
# ทั้งที่คีย์และเน็ตปกติ · ต้องส่ง context เอง แต่ห้ามปิด verification (ส่ง API key ออกไปกับ request)
from src.env import ssl_context   # noqa: E402
import ssl as _ssl                # noqa: E402

_ctx = ssl_context()
check("T13k ตั้ง SSL context เองได้ แต่ยัง verify certificate ตามปกติ (ไม่ปิดเพื่อความสะดวก)",
      _ctx.verify_mode == _ssl.CERT_REQUIRED and _ctx.check_hostname is True,
      f"verify={_ctx.verify_mode.name} · check_hostname={_ctx.check_hostname}")

check("T13l แปลง error ของ API เป็นภาษาคนพร้อมวิธีแก้",
      "เครดิต" in llm_mod._explain(400, '{"message":"Your credit balance is too low"}')
      and "ANTHROPIC_API_KEY" in llm_mod._explain(401, '{"type":"authentication_error"}')
      and "HTTP 418" in llm_mod._explain(418, "teapot"),   # ที่ไม่รู้จักต้องโชว์ของดิบไว้ debug
      llm_mod._explain(400, '{"message":"Your credit balance is too low"}')[:46])

# ---- T15: ชั้น 2 (กฎ deterministic) — ลดคอมเมนต์ที่ต้องจ่ายเงินโดยความแม่นต้องไม่ตก ----
# นี่คือเทสที่ "อนุญาต" ให้กฎอยู่ในระบบ: ถ้ากฎไหนทำให้ accuracy ตก ต้องเอาออก ไม่ใช่ปล่อยผ่าน
from src.classify.llm import OfflineHeuristicLLM as _Heur, prefilter   # noqa: E402


def run_labeled(use_gate: bool):
    """เดินชุด labeled ด้วย/ไม่ด้วยกฎชั้น 2 → (จำนวนถูก, จำนวนที่ต้องเข้า AI)."""
    ok = to_llm = 0
    for c in cases:
        b = lexicon.classify(c["text"])
        got = None
        if b["needs_llm"] or b["confidence"] < 0.5:
            got = prefilter(c["text"], b) if use_gate else None
            if got is None:
                to_llm += 1
                got = _Heur().analyze(c["text"], b["topics"])
        ok += (got or b)["sentiment"] == c["gold"]
    return ok, to_llm


plain_ok, plain_llm = run_labeled(False)
gate_ok, gate_llm = run_labeled(True)
check("T15 กฎชั้น 2 ต้องไม่ทำให้ความแม่นตกแม้แต่เคสเดียว",
      gate_ok >= plain_ok, f"{plain_ok}/{len(cases)} → {gate_ok}/{len(cases)}")
check("T15b กฎชั้น 2 ลดจำนวนคอมเมนต์ที่ต้องจ่ายเงินให้ AI ได้จริง",
      gate_llm < plain_llm, f"เข้า AI {plain_llm} → {gate_llm} (−{(plain_llm-gate_llm)/plain_llm:.0%})")

gate_cases = [
    ("วันนี้มีกิจกรรมอะไรพิเศษไหมครับ", "neutral", "คำถามขอข้อมูล"),
    ("😂😂😂", "neutral", "อีโมจิล้วน"),
    ("ดีจริง ๆ นะคะที่ล่มตอนคนกำลังจะเล่น ขอบคุณมากค่า", "negative", "ประชด"),
]
hits = [(t, prefilter(t, lexicon.classify(t)), want, why) for t, want, why in gate_cases]
check("T15c กฎชั้น 2 ตัดสิน 3 แบบนี้เองได้ (คำถาม / อีโมจิ / ประชด)",
      all(g and g["sentiment"] == want for _t, g, want, _w in hits),
      " · ".join(f"{why}→{(g or {}).get('sentiment')}" for _t, g, _wa, why in hits))

# ที่ต้องไม่โดนกฎแตะ: บ่นในรูปคำถาม + คอมเมนต์กำกวมจริง ต้องไปถึง AI
keep_cases = ["ทำไมเซิร์ฟล่มอีกแล้วครับ", "เกมโหลดช้านิดนึงตอนเข้า แต่พอเข้าได้ก็โอเค"]
check("T15d กฎชั้น 2 ไม่แตะของที่ต้องให้ AI อ่านจริง (บ่นในรูปคำถาม / กำกวม)",
      all(prefilter(t, lexicon.classify(t)) is None for t in keep_cases),
      "ปล่อยผ่านไปชั้น AI ทั้ง 2 เคส")

# ---- T16: คอมเมนต์เชิงบวก — เจอตอนรันข้อมูลจริงว่าระบบแทบไม่เคยให้ positive เลย ----
# ต้นเหตุ (วัดจากคอมเมนต์จริง 540 รายการ): 89% ของคอมเมนต์ไหลผ่านชั้น 2/3 ซึ่ง **คืนได้แค่
# negative/neutral เชิงโครงสร้าง** → ต่อให้เป็นโพสต์ที่คนชมเต็ม ก็ได้ positive = 0
def resolve(t: str) -> str:
    """เดินครบ 3 ชั้นแบบไม่ต่อเน็ต (ชั้น 3 = ตัวสำรอง) — เหมือนตอนรันจริงที่ยังไม่ใส่คีย์."""
    b = lexicon.classify(t)
    if not (b["needs_llm"] or b["confidence"] < 0.5):
        return b["sentiment"]
    return (prefilter(t, b) or _Heur().analyze(t, b["topics"]))["sentiment"]


praise = [
    ("ขอบคุณครับ ทีมงานทำได้ดีมาก", "คำขอบคุณ"),
    ("เป็นกำลังใจให้ทีมงานนะคะ รอเลยจ้า", "ให้กำลังใจ"),
    ("❤️❤️❤️", "อีโมจิล้วน"),
    ("โคตรดีเลยครับ 💓", "ชมตรง ๆ"),
]
check("T16 คอมเมนต์ชมต้องได้ positive (ก่อนแก้ได้ neutral ทั้งหมด)",
      all(resolve(t) == "positive" for t, _w in praise),
      " · ".join(f"{w}={resolve(t)}" for t, w in praise))

check("T16b ตัวปฏิเสธต้องดูระยะใกล้ ไม่ใช่ทั้งข้อความ",
      resolve("เกมสนุกมาก เล่นไม่เบื่อเลย") == "positive"
      and resolve("ไม่สนุกเลยครับ") == "negative",
      "“สนุกมาก…ไม่เบื่อ”=positive · “ไม่สนุกเลย”=negative")

check("T16c อีโมจิ: ชื่นชม→บวก · หัวเราะเยาะ/ไหว้ ไม่นับเป็นบวก",
      resolve("👍👍") == "positive" and resolve("🤣🤣") != "positive",
      f"👍={resolve('👍👍')} · 🤣={resolve('🤣🤣')}")

# กับดัก substring ที่เจอในข้อมูลจริง — ถ้าเผลอเติมคำเดี่ยวลง POSITIVE จะพังทั้งชุด
traps = [("บริษัทควรต้องรับผิดชอบ กู้ไฟล์ที่หายไป", "'ชอบ' ใน 'รับผิดชอบ'"),
         ("เป็นการแถลงการณ์เท่านั้นครับ", "'เท่' ใน 'เท่านั้น'"),
         ("ก็ไม่ไว้ใจทีมงานเดิมอีกต่อไป", "'ไว้ใจ' ที่ถูกปฏิเสธ")]
check("T16d ไม่นับคำชมที่จริง ๆ เป็นส่วนของคำอื่น (บทเรียนเดียวกับกับดัก 'โค้ด')",
      all(resolve(t) != "positive" for t, _w in traps),
      " · ".join(f"{w}→{resolve(t)}" for t, w in traps))

insults = ["มีหน้าไปด่าคนอื่นพ่อแม่ไม่สั่งสอน", "พี่ได้เป็นหัวแถวคนโง่ประจำเม้นท์"]
check("T16e คอมเมนต์ด่าทอต้องเป็นลบ ไม่ใช่บวก (เคสจริงที่เคยหลุดเป็นบวก)",
      all(resolve(t) == "negative" for t in insults),
      " · ".join(resolve(t) for t in insults))

# ---- T14: cache รายการ URL โพสต์ — ตัด actor ที่แพงสุดออกจากรอบส่วนใหญ่ ----
# posts scraper ≈ $0.026/run · comments scraper ≈ $0.008/run (จากบิลจริง)
# → รอบหนึ่ง 5 โพสต์ = $0.065 ซึ่ง 40% คือ posts scraper ตัวเดียว
from src.sources.facebook_apify import ApifyFacebookScraper, PostUrlCache   # noqa: E402

cache_dir = Path(tempfile.mkdtemp(prefix="crisis-radar-posts-"))
PAGE = "https://www.facebook.com/thehof.talesrunner"
FOUND = [f"{PAGE}/posts/{i}" for i in range(1, 6)]

actor_calls: list[str] = []


def mk_scraper(ttl=360, path_name="c.json", comments_per_post=4):
    s = ApifyFacebookScraper(token="apify_api_test",
                             post_cache=PostUrlCache(cache_dir / path_name, ttl_min=ttl))
    def fake_run(actor, run_input):
        actor_calls.append(actor)
        if "posts-scraper" in actor:
            return [{"url": u} for u in FOUND]
        return [{"text": f"คอมเมนต์ {i}", "date": "2026-07-15T14:00:00.000Z"}
                for i in range(comments_per_post)]
    s._run = fake_run
    return s


target = {"type": "page", "name": "TalesRunner", "url": PAGE}
first = mk_scraper()
got1 = first.scrape_target(target, 5, 30, log=lambda _m: None)
run1 = list(actor_calls)
check("T14 รอบแรกยังต้องยิง posts scraper ตามปกติ (1 + 5 runs)",
      sum("posts-scraper" in a for a in run1) == 1
      and sum("comments-scraper" in a for a in run1) == 5 and len(got1) == 20,
      f"{len(run1)} actor run · {len(got1)} คอมเมนต์")

actor_calls.clear()
second = mk_scraper()          # cache file เดิม → รอบถัดไปต้องข้าม posts scraper
got2 = second.scrape_target(target, 5, 30, log=lambda _m: None)
saved = sum("posts-scraper" in a for a in actor_calls)
check("T14b รอบถัดไปข้าม posts scraper (ประหยัด ~40% ของค่าใช้จ่ายต่อรอบ)",
      saved == 0 and sum("comments-scraper" in a for a in actor_calls) == 5 and len(got2) == 20,
      f"posts scraper {saved} run · ยังได้ {len(got2)} คอมเมนต์เท่าเดิม")

actor_calls.clear()
expired = ApifyFacebookScraper(token="apify_api_test",
                               post_cache=PostUrlCache(cache_dir / "c.json", ttl_min=0))
expired._run = mk_scraper()._run
expired.get_post_urls(PAGE, 5, log=lambda _m: None)
check("T14c ตั้ง POST_URLS_TTL_MIN=0 = ปิด cache หาโพสต์ใหม่ทุกรอบ (เผื่ออยากได้สดจริง ๆ)",
      sum("posts-scraper" in a for a in actor_calls) == 1)

actor_calls.clear()
other = mk_scraper(path_name="c.json")
other.get_post_urls(PAGE, 10, log=lambda _m: None)     # ขอ 10 โพสต์ = คนละ key กับที่จำไว้ (5)
check("T14d ขอจำนวนโพสต์ต่างจากเดิม → ไม่เอา cache ของเก่ามาใช้ผิด ๆ",
      sum("posts-scraper" in a for a in actor_calls) == 1)

actor_calls.clear()
dead = mk_scraper(path_name="d.json", comments_per_post=0)
dead.post_cache.put(PAGE, 5, FOUND)                    # จำไว้แล้ว แต่โพสต์ถูกลบไปหมด
dead.scrape_target(target, 5, 30, log=lambda _m: None)
check("T14e URL ที่จำไว้ใช้ไม่ได้แล้ว → ล้าง cache ให้รอบหน้าหาใหม่ (ไม่ค้างอยู่กับโพสต์ที่ตายแล้ว)",
      dead.post_cache.get(PAGE, 5)[0] is None
      and sum("posts-scraper" in a for a in actor_calls) == 0,
      "ล้างแล้ว และไม่ยิง posts scraper ซ้ำในรอบเดียวกัน")

# ---- output ----
print("=" * 64)
print("CRISIS RADAR — TEST RESULTS")
print("=" * 64)
for r in results:
    print(r)
print("-" * 64)
print(f"sentiment: lexicon-only {lex_acc:.0%} → hybrid {hyb_acc:.0%}  (+{(hyb_acc-lex_acc)*100:.0f} จุด)")
print(f"confusion (gold→hybrid): {json.dumps(confusion, ensure_ascii=False)}")
print(f"crisis sample: status={rep.status}, alerts={len(rep.alerts)}, escalated={rep.escalated_count}/{rep.total}")
print("-" * 64)
print(f"สรุป: {passed} passed, {failed} failed")
sys.exit(0 if failed == 0 else 1)
