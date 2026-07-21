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

from ..classify.lexicon import TOPIC_LABELS
from ..models import Classified

SPIKE_FACTOR = 2.5
MIN_SEVERITY = 30
VIRAL_REACH = 150
BUCKET_MINUTES = 60
MIN_TOPIC_SEVERITY = 20     # ประเด็นย่อยเล็กกว่า → เกณฑ์ต่ำกว่า spike รวม

# ประเด็น → ทีมที่เป็นเจ้าของเรื่อง (ใช้ route alert ให้ถึงคนแก้จริง ไม่ใช่แค่ทีม Community)
TOPIC_OWNER = {
    "bug/technical": "Dev / QA",
    "billing/price": "Marketing / Monetization",
    "balance/fairness": "Game Design",
    "service/support": "Community / CS",
    "content/event": "Content / Event",
    "rewards/redeem": "Marketing (แคมเปญ/โค้ด) + CS",
}


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
class TopicStat:
    """สถิติรายประเด็น — ตอบว่า 'เรื่องอะไร ใครต้องแก้ กำลังมาแรงไหม'."""
    topic: str
    label: str
    negative: int
    severity: float
    share: float          # % ของคอมเมนต์ลบทั้งหมด
    owner: str
    peak: str             # ช่วงเวลาที่ประเด็นนี้หนักสุด
    is_emerging: bool     # เพิ่งพุ่งในช่วงล่าสุด (ประเด็นใหม่ / โตเกิน baseline ของตัวเอง)


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
    topic_trends: list[TopicStat] = field(default_factory=list)


def _bucket_key(ts: datetime) -> datetime:
    m = (ts.minute // BUCKET_MINUTES) * BUCKET_MINUTES
    return ts.replace(minute=m, second=0, microsecond=0)


def _topic_trends(items: list[Classified], ordered_keys: list[datetime]) -> list[TopicStat]:
    """แยก severity รายประเด็นต่อช่วงเวลา → บอกว่าประเด็นไหน 'กำลังมาแรง' ตอนนี้.

    ทำไมต้องมี: spike รวมมองคอมเมนต์ลบทุกประเด็นกองเดียวกัน — เวลาเซิร์ฟล่ม (severity หลักพัน)
    ดราม่าเล็กกว่าอย่าง 'โค้ดใช้ไม่ได้' จะถูกกลบจนไม่มีวันเตือน ทั้งที่คนละทีมต้องแก้.
    """
    negs = [it for it in items if it.sentiment == "negative"]
    total_neg = len(negs) or 1
    per_topic: dict[str, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    counts: Counter[str] = Counter()

    for it in negs:
        b = _bucket_key(it.comment.created_at)
        for t in it.topics:
            per_topic[t][b] += 1 + it.comment.reach
            counts[t] += 1

    last = ordered_keys[-1] if ordered_keys else None
    out: list[TopicStat] = []
    for topic, by_bucket in per_topic.items():
        sev = sum(by_bucket.values())
        peak_b = max(by_bucket, key=lambda k: by_bucket[k])
        prior = [by_bucket.get(k, 0.0) for k in ordered_keys[:-1]]
        latest = by_bucket.get(last, 0.0) if last else 0.0
        seen_before = any(p > 0 for p in prior)
        base = (sum(prior) / len(prior)) if prior else 0.0
        # มาแรง = ช่วงล่าสุดหนักพอ และ (เป็นประเด็นใหม่ หรือ โตเกิน baseline ของประเด็นตัวเอง)
        emerging = latest >= MIN_TOPIC_SEVERITY and (not seen_before or latest > base * SPIKE_FACTOR)

        out.append(TopicStat(
            topic=topic,
            label=TOPIC_LABELS.get(topic, topic),
            negative=counts[topic],
            severity=round(sev, 1),
            share=round(counts[topic] / total_neg * 100, 1),
            owner=TOPIC_OWNER.get(topic, "Community"),
            peak=f"{peak_b:%H:%M}",
            is_emerging=emerging,
        ))
    return sorted(out, key=lambda s: s.severity, reverse=True)


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

    # ประเด็นที่กำลังมาแรง (แยกต่อ topic — ไม่ให้ดราม่าเล็กถูกกลบด้วยดราม่าใหญ่)
    trends = _topic_trends(items, [k for k, _ in ordered])
    for t in trends:
        if t.is_emerging:
            alerts.append(
                f"📈 ประเด็น '{t.label}' กำลังมาแรง ({t.negative} คอมเมนต์ลบ · severity {t.severity:.0f}) "
                f"· ส่งต่อ: {t.owner}"
            )

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
        "WATCH" if viral or any(t.is_emerging for t in trends)
        or sentiment_mix.get("negative", 0) / max(len(items), 1) > 0.4 else "NORMAL"
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
        topic_trends=trends,
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
        "topic_trends": [
            {"topic": t.topic, "label": t.label, "negative": t.negative, "severity": t.severity,
             "share": t.share, "owner": t.owner, "peak": t.peak, "is_emerging": t.is_emerging}
            for t in rep.topic_trends
        ],
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
    lines += ["", "## ประเด็นลบที่พบ (topic) + ทีมที่ต้องรับเรื่อง", "",
              "| ประเด็น | คอมเมนต์ลบ | สัดส่วน | severity | หนักสุด | มาแรง | ส่งต่อทีม |",
              "|---|---|---|---|---|---|---|"]
    for t in rep.topic_trends:
        lines.append(f"| {t.label} | {t.negative} | {t.share:.0f}% | {t.severity:.0f} | "
                     f"{t.peak} | {'📈' if t.is_emerging else ''} | {t.owner} |")
    if not rep.topic_trends:
        lines.append("| — | | | | | | |")
    lines += ["", "## Timeline (รายชั่วโมง)", "", "| ช่วง | คอมเมนต์ | ลบ | severity | baseline | spike |",
              "|---|---|---|---|---|---|"]
    for s in rep.buckets:
        lines.append(f"| {s.start:%H:%M} | {s.total} | {s.negative} | {s.severity:.0f} | "
                     f"{s.baseline:.0f} | {'🚨' if s.is_spike else ''} |")
    return "\n".join(lines)
