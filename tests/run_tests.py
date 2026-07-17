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
"""
from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.classify import lexicon                       # noqa: E402
from src.classify.pipeline import HybridClassifier     # noqa: E402
from src.crisis import detector                        # noqa: E402
from src.models import Classified, Comment             # noqa: E402
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
