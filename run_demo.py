#!/usr/bin/env python3
"""Crisis Radar — รัน end-to-end บน sample data ของ Talesrunner.

flow:  SampleFacebookSource → HybridClassifier → crisis.detect → report (md + json + html)

รัน:   python run_demo.py
ผลลัพธ์อยู่ใน output/
"""
from __future__ import annotations

import json
from pathlib import Path

from src.classify.pipeline import HybridClassifier
from src.crisis import detector
from src.dashboard import render_html
from src.sources.sample import SampleFacebookSource

ROOT = Path(__file__).parent
FIXTURE = ROOT / "data" / "sample_talesrunner_fb_comments.json"
OUT = ROOT / "output"


def main() -> None:
    OUT.mkdir(exist_ok=True)

    # 1) ingest (masked PII แล้วในตัว source)
    source = SampleFacebookSource(FIXTURE, brand="talesrunner")
    comments = source.fetch()
    print(f"[ingest] ดึง {len(comments)} คอมเมนต์จาก {source.platform}")

    # 2) hybrid classify (lexicon → LLM เฉพาะเคสไม่มั่นใจ)
    clf = HybridClassifier()
    classified = clf.classify_all(comments)
    escalated = sum(1 for c in classified if c.escalated_to_llm)
    print(f"[classify] เสร็จ {len(classified)} · ส่งต่อ LLM {escalated} เคส")

    # 3) crisis detection
    report = detector.detect(classified, brand="talesrunner")
    print(f"[crisis] สถานะ = {report.status} · alert {len(report.alerts)} รายการ")

    # 4) outputs
    (OUT / "crisis_report.md").write_text(detector.render_markdown(report), encoding="utf-8")
    (OUT / "classified.json").write_text(
        json.dumps([c.to_dict() for c in classified], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (OUT / "dashboard.html").write_text(render_html(report, classified), encoding="utf-8")
    print(f"[output] เขียน crisis_report.md / classified.json / dashboard.html ไปที่ {OUT}")

    print("\n" + detector.render_markdown(report))


if __name__ == "__main__":
    main()
