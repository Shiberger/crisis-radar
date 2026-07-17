#!/usr/bin/env python3
"""Crisis Radar — รัน pipeline end-to-end.

flow:  SampleFacebookSource → HybridClassifier → crisis.detect → report (md + json + html)

รัน:
  python run_demo.py                       # ใช้ sample fixture (Talesrunner)
  python run_demo.py --fixture data/facebook_live_talesrunner.json   # ใช้ data จริงที่ scrape มา
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.classify.pipeline import HybridClassifier
from src.crisis import detector
from src.dashboard import render_html
from src.sources.sample import SampleFacebookSource

ROOT = Path(__file__).parent
DEFAULT_FIXTURE = ROOT / "data" / "sample_talesrunner_fb_comments.json"
OUT = ROOT / "output"


def run_pipeline(fixture_path: Path, brand: str = "talesrunner") -> detector.CrisisReport:
    OUT.mkdir(exist_ok=True)

    # 1) ingest (masked PII แล้วในตัว source)
    source = SampleFacebookSource(fixture_path, brand=brand)
    comments = source.fetch()
    print(f"[ingest] ดึง {len(comments)} คอมเมนต์จาก {source.platform} ({fixture_path.name})")

    # 2) hybrid classify (lexicon → LLM เฉพาะเคสไม่มั่นใจ)
    clf = HybridClassifier()
    classified = clf.classify_all(comments)
    escalated = sum(1 for c in classified if c.escalated_to_llm)
    print(f"[classify] เสร็จ {len(classified)} · ส่งต่อ LLM {escalated} เคส")

    # 3) crisis detection
    report = detector.detect(classified, brand=brand)
    print(f"[crisis] สถานะ = {report.status} · alert {len(report.alerts)} รายการ")

    # 4) outputs
    (OUT / "crisis_report.md").write_text(detector.render_markdown(report), encoding="utf-8")
    (OUT / "classified.json").write_text(
        json.dumps([c.to_dict() for c in classified], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "dashboard.html").write_text(render_html(report, classified), encoding="utf-8")
    print(f"[output] เขียน crisis_report.md / classified.json / dashboard.html → {OUT}")
    print("\n" + detector.render_markdown(report))
    return report


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE,
                    help="ไฟล์ comments (fixture schema). default = sample")
    ap.add_argument("--brand", default="talesrunner")
    args = ap.parse_args()
    run_pipeline(args.fixture, args.brand)


if __name__ == "__main__":
    main()
