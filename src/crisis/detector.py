"""Crisis detector — แกนของ tool.

ไม่ใช่แค่ 'นับคอมเมนต์ลบ' แต่ตรวจ 'การพุ่งผิดปกติ' เทียบ baseline + ถ่วงน้ำหนักด้วย reach
เพราะ 1 เธรดที่คนแห่มา 200 like ≠ 1 คอมเมนต์ลอย ๆ.

Severity ของช่วงเวลา = ผลรวมของ (1 + reach) เฉพาะคอมเมนต์ 'negative'
Baseline = ค่าเฉลี่ย severity ของช่วงก่อนหน้า (expanding, อย่างน้อย 2 ช่วง)
Alert เมื่อ: severity > baseline * SPIKE_FACTOR  และ  severity >= MIN_SEVERITY
เพิ่ม: viral negative = คอมเมนต์ลบเดี่ยวที่ reach สูงผิดปกติ
"""
from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..models import Classified

SPIKE_FACTOR = 2.5
MIN_SEVERITY = 30
VIRAL_REACH = 150
BUCKET_MINUTES = 60


@dataclass
class BucketStat:
    start: datetime
    total: int
    negative: int
    severity: float
    baseline: float
    is_spike: bool
    top_topics: list[tuple[str, int]] = field(default_factory=list)


@dataclass
class CrisisReport:
    brand: str
    status: str                       # NORMAL | WATCH | CRISIS
    buckets: list[BucketStat]
    alerts: list[str]
    viral_comments: list[Classified]
    topic_breakdown: list[tuple[str, int]]
    sentiment_mix: dict
    escalated_count: int
    total: int


def _bucket_key(ts: datetime) -> datetime:
    m = (ts.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    return ts.replace(minute=m, second=0, microsecond=0)


def detect(items: list[Classified], brand: str = "talesrunner") -> CrisisReport:
    buckets_map: dict[datetime, list[Classified]] = defaultdict(list)
    for it in items:
        buckets_map[_bucket_key(it.comment.created_at)].append(it)

    ordered = sorted(buckets_map.items())
    stats: list[BucketStat] = []
    alerts: list[str] = []
    severities_so_far: list[float] = []

    for start, group in ordered:
        negs = [g for g in group if g.sentiment == "negative"]
        severity = sum(1 + g.comment.reach for g in negs)

        baseline = (sum(severities_so_far) / len(severities_so_far)) if len(severities_so_far) >= 2 else 0.0
        is_spike = baseline > 0 and severity > baseline * SPIKE_FACTOR and severity >= MIN_SEVERITY

        topic_counter: Counter[str] = Counter()
        for g in negs:
            topic_counter.update(g.topics)

        stats.append(BucketStat(
            start=start, total=len(group), negative=len(negs), severity=severity,
            baseline=round(baseline, 1), is_spike=is_spike,
            top_topics=topic_counter.most_common(3),
        ))

        if is_spike:
            top = ", ".join(f"{t}({n})" for t, n in topic_counter.most_common(3)) or "-"
            alerts.append(
                f"🚨 {start:%H:%M} คอมเมนต์ลบพุ่ง (severity {severity:.0f} vs baseline {baseline:.0f}) "
                f"· ประเด็นหลัก: {top}"
            )

        severities_so_far.append(severity)

    # viral negative (ไม่ต้องรอ spike ของช่วงเวลา)
    viral = sorted(
        [it for it in items if it.sentiment == "negative" and it.comment.reach >= VIRAL_REACH],
        key=lambda x: x.comment.reach, reverse=True,
    )
    for v in viral:
        alerts.append(
            f"🔥 คอมเมนต์ลบไวรัล reach {v.comment.reach} ({', '.join(v.topics) or 'ทั่วไป'}): "
            f"\"{v.comment.text[:60]}...\""
        )

    # สรุปภาพรวม
    sentiment_mix = Counter(it.sentiment for it in items)
    topic_counter: Counter[str] = Counter()
    for it in items:
        if it.sentiment == "negative":
            topic_counter.update(it.topics)

    status = "CRISIS" if any(s.is_spike for s in stats) else (
        "WATCH" if viral or sentiment_mix.get("negative", 0) / max(len(items), 1) > 0.4 else "NORMAL"
    )

    return CrisisReport(
        brand=brand,
        status=status,
        buckets=stats,
        alerts=alerts,
        viral_comments=viral,
        topic_breakdown=topic_counter.most_common(),
        sentiment_mix=dict(sentiment_mix),
        escalated_count=sum(1 for it in items if it.escalated_to_llm),
        total=len(items),
    )


def report_to_dict(rep: CrisisReport) -> dict:
    """serialize CrisisReport เป็น JSON สำหรับ web API/frontend."""
    return {
        "brand": rep.brand,
        "status": rep.status,
        "total": rep.total,
        "sentiment_mix": rep.sentiment_mix,
        "escalated_count": rep.escalated_count,
        "alerts": rep.alerts,
        "topic_breakdown": [[t, n] for t, n in rep.topic_breakdown],
        "buckets": [
            {"start": b.start.strftime("%H:%M"), "total": b.total, "negative": b.negative,
             "severity": round(b.severity, 1), "baseline": b.baseline, "is_spike": b.is_spike}
            for b in rep.buckets
        ],
    }


def render_markdown(rep: CrisisReport) -> str:
    icon = {"NORMAL": "🟢", "WATCH": "🟡", "CRISIS": "🔴"}[rep.status]
    lines = [
        f"# Crisis Radar — {rep.brand.title()} (Facebook)",
        "",
        f"**สถานะ: {icon} {rep.status}**  ·  คอมเมนต์ทั้งหมด {rep.total}  ·  "
        f"บวก {rep.sentiment_mix.get('positive',0)} / กลาง {rep.sentiment_mix.get('neutral',0)} / "
        f"ลบ {rep.sentiment_mix.get('negative',0)}  ·  ส่งต่อ LLM {rep.escalated_count} เคส",
        "",
        "## 🔔 Alert",
    ]
    lines += [f"- {a}" for a in rep.alerts] or ["- ไม่มีสัญญาณผิดปกติ"]
    lines += ["", "## ประเด็นลบที่พบ (topic)"]
    lines += [f"- {t}: {n}" for t, n in rep.topic_breakdown] or ["- ไม่มี"]
    lines += ["", "## Timeline (รายชั่วโมง)", "", "| ช่วง | คอมเมนต์ | ลบ | severity | baseline | spike |",
              "|---|---|---|---|---|---|"]
    for s in rep.buckets:
        lines.append(f"| {s.start:%H:%M} | {s.total} | {s.negative} | {s.severity:.0f} | "
                     f"{s.baseline:.0f} | {'🚨' if s.is_spike else ''} |")
    return "\n".join(lines)
