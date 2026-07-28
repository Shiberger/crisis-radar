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

from src.classify import archive, lexicon, overrides   # noqa: E402
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
