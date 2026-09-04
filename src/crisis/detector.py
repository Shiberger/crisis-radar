"""Crisis detector — แกนของ tool.

ไม่ใช่แค่ 'นับคอมเมนต์ลบ' แต่ตรวจ 'การพุ่งผิดปกติ' เทียบ baseline + ถ่วงน้ำหนักด้วย reach
เพราะ 1 เธรดที่คนแห่มา 200 like ≠ 1 คอมเมนต์ลอย ๆ.

Severity ของช่วงเวลา = ผลรวมของ (1 + reach) เฉพาะคอมเมนต์ 'negative'
Baseline = ค่าเฉลี่ย severity ของช่วงก่อนหน้า (expanding, อย่างน้อย 2 ช่วง)
Alert เมื่อ: severity > baseline * SPIKE_FACTOR  และ  severity >= MIN_SEVERITY
เพิ่ม: viral negative = คอมเมนต์ลบเดี่ยวที่ reach สูงผิดปกติ
"""
from __future__ import annotations

import os
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from ..classify.lexicon import TOPIC_LABELS
from ..models import Classified

def _env(key: str, default: float) -> float:
    """เกณฑ์ทุกตัวปรับได้จาก env — ปรับจูนตอนพรีเซ้นท์/ตอนเพจแตกได้โดยไม่ต้อง deploy ใหม่."""
    try:
        return float(str(os.environ.get(key, "")).strip() or default)
    except ValueError:
        return default


SPIKE_FACTOR = 2.5
# เกณฑ์เหล่านี้เคยตั้งจาก "ข้อมูลตัวอย่าง" ซึ่งเป็นวันที่เพจแตก (reach หลักร้อย) พอเอามาใช้กับ
# วันปกติของเพจจริงจึงไม่มีวันเข้าเงื่อนไข — วัดจากคอมเมนต์จริง 542 อันของเพจได้ว่า
#   reach: p50=1 · p90=21 · p95=49 · p99=156
# ตั้งที่ 150 = ระดับ p99 → คอมเมนต์ 1 ใน 100 เท่านั้นที่มีสิทธิ์ ซึ่งในรอบตรวจที่ได้มา
# วันละ ~12 คอมเมนต์ แปลว่าไม่มีวันเด้งเลย · ย้ายมาที่ระดับ p95 ให้ระบบเห็นของจริงได้
MIN_SEVERITY = _env("CRISIS_MIN_SEVERITY", 8)      # severity ต่ำสุดที่ยอมเรียกว่า spike
VIRAL_REACH = int(_env("CRISIS_VIRAL_REACH", 50))  # คอมเมนต์ลบเดี่ยวที่ถือว่ากระจายวงกว้าง
MIN_TOPIC_SEVERITY = _env("CRISIS_MIN_TOPIC_SEVERITY", 5)   # ประเด็นย่อยเล็กกว่า → เกณฑ์ต่ำกว่า

# ── ขนาดช่วงเวลา (bucket) ────────────────────────────────────────────────────
# เคยลองให้เลือกขนาดเองตาม "ช่วงเวลาที่ข้อมูลกิน" แล้ววัดกับวิกฤตจริงเดือน ก.พ. (508 คอมเมนต์)
# ได้ผลแย่ลง: ชุดข้อมูลจริงมีคอมเมนต์เก่าติดมาไม่กี่อัน span เลยกลายเป็น 43 วัน → เลือก bucket
# รายวัน → ดราม่าที่ระเบิดภายในไม่กี่ชั่วโมงถูกเกลี่ยจนไม่เหลือ spike (CRISIS กลายเป็น WATCH)
# สรุป: รายชั่วโมงคงที่ทนกับข้อมูลจริงได้ดีกว่า · ปรับได้จาก env ถ้าเจอเพจที่จังหวะต่างไป
BUCKET_MINUTES = int(_env("CRISIS_BUCKET_MIN", 60))

# คอมเมนต์ไวรัลกี่อันที่ยกขึ้นมาเป็น alert เดี่ยว ๆ — ที่เหลือรวบเป็นบรรทัดเดียว
# ทำไมต้องมีเพดาน: รายการนี้ไม่เคยถูกจำกัด ตอนเกณฑ์อยู่ที่ p99 เลยมีอันเดียวเสมอจนไม่มีใครเห็นปัญหา
# พอลดเกณฑ์มาที่ p95 วันที่เพจแตกจริงจะได้ alert 15 บรรทัดรวด ซึ่งอ่านไม่ไหวและกลบ spike/emerging
# ที่สำคัญกว่า — alert ที่เยอะเกินอ่าน มีค่าเท่ากับไม่มี alert
VIRAL_ALERT_MAX = 3

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
    peak_iso: str = ""    # เวลาเดียวกับ peak แต่เต็มวันที่ — ให้หน้าเว็บกรองข้ามวันได้


@dataclass
class AlertItem:
    """Alert แบบมีโครงสร้าง — หน้าเว็บเอาไปทำการ์ด + ปุ่ม 'ดูคอมเมนต์' ได้.

    ข้อความ string เดิม (CrisisReport.alerts) ยังอยู่ครบสำหรับ CLI/markdown
    ที่นี่แค่แยกส่วนประกอบออกมา ไม่ให้ฝั่ง UI ต้อง regex แกะข้อความเอง.
    """
    kind: str             # 'spike' | 'emerging' | 'viral'
    level: str            # 'high' | 'medium'
    title: str            # พาดหัวภาษาคน
    detail: str           # ตัวเลขประกอบ
    owner: str = ""       # ทีมที่ควรรับเรื่อง
    topic: str = ""       # topic key — ใช้เป็นตัวกรองตอนกดดูคอมเมนต์
    bucket_iso: str = ""  # ช่วงเวลาที่เกี่ยวข้อง — ใช้เป็นตัวกรอง
    comment_id: str = ""  # เฉพาะ viral: คอมเมนต์ต้นเรื่อง


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
    alert_items: list[AlertItem] = field(default_factory=list)
    bucket_minutes: int = BUCKET_MINUTES     # ขนาดที่ "เลือกให้ข้อมูลชุดนี้" ไม่ใช่ค่าคงที่


def _bucket_key(ts: datetime, mins: int = BUCKET_MINUTES) -> datetime:
    """ปัดเวลาลงหาขอบ bucket โดยนับจากเที่ยงคืนของวันนั้น.

    ปัดจากเที่ยงคืน (ไม่ใช่ปัดแค่นาที) เพราะ bucket ใหญ่กว่า 1 ชม. ต้องปัดชั่วโมงด้วย —
    ของเดิมปัดเฉพาะ .minute จึงใช้ได้แค่ bucket ที่เล็กกว่าชั่วโมงเท่านั้น
    """
    day = ts.replace(hour=0, minute=0, second=0, microsecond=0)
    n = int((ts - day).total_seconds() // 60) // mins
    return day + timedelta(minutes=n * mins)


def _topic_trends(items: list[Classified], ordered_keys: list[datetime],
                  mins: int = BUCKET_MINUTES) -> list[TopicStat]:
    """แยก severity รายประเด็นต่อช่วงเวลา → บอกว่าประเด็นไหน 'กำลังมาแรง' ตอนนี้.

    ทำไมต้องมี: spike รวมมองคอมเมนต์ลบทุกประเด็นกองเดียวกัน — เวลาเซิร์ฟล่ม (severity หลักพัน)
    ดราม่าเล็กกว่าอย่าง 'โค้ดใช้ไม่ได้' จะถูกกลบจนไม่มีวันเตือน ทั้งที่คนละทีมต้องแก้.
    """
    negs = [it for it in items if it.sentiment == "negative"]
    total_neg = len(negs) or 1
    per_topic: dict[str, dict[datetime, float]] = defaultdict(lambda: defaultdict(float))
    counts: Counter[str] = Counter()

    for it in negs:
        b = _bucket_key(it.comment.created_at, mins)
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
            peak_iso=peak_b.isoformat(),
        ))
    return sorted(out, key=lambda s: s.severity, reverse=True)


def detect(items: list[Classified], brand: str = "talesrunner") -> CrisisReport:
    mins = BUCKET_MINUTES
    buckets_map: dict[datetime, list[Classified]] = defaultdict(list)
    for it in items:
        buckets_map[_bucket_key(it.comment.created_at, mins)].append(it)

    ordered = sorted(buckets_map.items())
    stats: list[BucketStat] = []
    alerts: list[str] = []
    items_out: list[AlertItem] = []
    severities_so_far: list[float] = []

    for start, group in ordered:
        negs = [g for g in group if g.sentiment == "negative"]
        severity = sum(1 + g.comment.reach for g in negs)

        # ต้องมีอย่างน้อย 2 ช่วงก่อนหน้า ถึงจะรู้ว่า "ปกติ" ของเพจนี้หน้าตายังไง
        have_history = len(severities_so_far) >= 2
        baseline = (sum(severities_so_far) / len(severities_so_far)) if have_history else 0.0
        # baseline = 0 (เพจที่ปกติไม่มีคอมเมนต์ลบเลย) ต้องนับเป็น spike ได้ด้วย —
        # ของเดิมบังคับ baseline > 0 ทำให้เพจเงียบ ๆ ที่อยู่ดี ๆ มีคนบ่นรัวกัน "ไม่มีวัน" เตือน
        # ทั้งที่ 0 → หลายคอมเมนต์ในชั่วโมงเดียว คือสัญญาณที่ชัดที่สุดเท่าที่จะมีได้
        # MIN_SEVERITY เป็นตัวกันไม่ให้คอมเมนต์ลบลอย ๆ อันเดียวกลายเป็น CRISIS
        is_spike = (have_history and severity >= MIN_SEVERITY
                    and (severity > baseline * SPIKE_FACTOR if baseline > 0 else True))

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
            lead = topic_counter.most_common(1)
            lead_topic = lead[0][0] if lead else ""
            times = severity / baseline if baseline else 0
            items_out.append(AlertItem(
                kind="spike", level="high",
                title=f"คอมเมนต์ลบพุ่งผิดปกติช่วง {start:%H:%M} น. — แรงกว่าปกติ {times:.0f} เท่า",
                detail=f"ชั่วโมงนี้มีคอมเมนต์ลบ {len(negs)} จาก {len(group)} คอมเมนต์ · "
                       f"เรื่องที่คนบ่นมากสุดคือ "
                       f"{TOPIC_LABELS.get(lead_topic, lead_topic) or 'ทั่วไป'}",
                owner=TOPIC_OWNER.get(lead_topic, "Community"),
                topic=lead_topic, bucket_iso=start.isoformat(),
            ))

        severities_so_far.append(severity)

    # ประเด็นที่กำลังมาแรง (แยกต่อ topic — ไม่ให้ดราม่าเล็กถูกกลบด้วยดราม่าใหญ่)
    trends = _topic_trends(items, [k for k, _ in ordered], mins)
    for t in trends:
        if t.is_emerging:
            alerts.append(
                f"📈 ประเด็น '{t.label}' กำลังมาแรง ({t.negative} คอมเมนต์ลบ · severity {t.severity:.0f}) "
                f"· ส่งต่อ: {t.owner}"
            )
            items_out.append(AlertItem(
                kind="emerging", level="medium",
                title=f"เรื่อง “{t.label}” กำลังมาแรงในชั่วโมงล่าสุด",
                detail=f"มีคอมเมนต์ลบเรื่องนี้ {t.negative} รายการ "
                       f"({t.share:.0f}% ของคอมเมนต์ลบทั้งหมด) · หนักสุดช่วง {t.peak} น.",
                owner=t.owner, topic=t.topic, bucket_iso=t.peak_iso,
            ))

    # viral negative (ไม่ต้องรอ spike ของช่วงเวลา)
    viral = sorted(
        [it for it in items if it.sentiment == "negative" and it.comment.reach >= VIRAL_REACH],
        key=lambda x: x.comment.reach, reverse=True,
    )
    for v in viral[:VIRAL_ALERT_MAX]:
        alerts.append(
            f"🔥 คอมเมนต์ลบไวรัล reach {v.comment.reach} ({', '.join(v.topics) or 'ทั่วไป'}): "
            f"\"{v.comment.text[:60]}...\""
        )
        vt = v.topics[0] if v.topics else ""
        items_out.append(AlertItem(
            kind="viral", level="medium",
            title=f"คอมเมนต์ลบ 1 อันกำลังกระจายวงกว้าง (คนกดไลก์/ตอบกลับ {v.comment.reach} ครั้ง)",
            detail=f"“{v.comment.text[:90]}{'…' if len(v.comment.text) > 90 else ''}” — โดย {v.comment.author}",
            owner=TOPIC_OWNER.get(vt, "Community"),
            topic=vt, bucket_iso=_bucket_key(v.comment.created_at, mins).isoformat(),
            comment_id=v.comment.comment_id,
        ))

    # ที่เหลือรวบเป็นบรรทัดเดียว — ยังบอกว่ามีอีกเท่าไร (ตัวเลขคือสิ่งที่บอกว่า "หนักแค่ไหน")
    # แต่ไม่กินพื้นที่จนกลบ alert ประเภทอื่น · รายตัวยังกดดูครบบนหน้าเว็บได้เหมือนเดิม
    rest = viral[VIRAL_ALERT_MAX:]
    if rest:
        top_rest = ", ".join(str(v.comment.reach) for v in rest[:5])
        alerts.append(f"🔥 มีคอมเมนต์ลบไวรัลอีก {len(rest)} อัน (reach {top_rest}"
                      f"{'…' if len(rest) > 5 else ''}) — ดูทั้งหมดบนหน้าเว็บ")
        items_out.append(AlertItem(
            kind="viral", level="medium",
            title=f"มีคอมเมนต์ลบที่กระจายวงกว้างอีก {len(rest)} อัน",
            detail=f"เกินเกณฑ์ไวรัล (reach ≥ {VIRAL_REACH}) รวมทั้งหมด {len(viral)} อันในรอบนี้ "
                   f"· ยกมาแสดงแยก {VIRAL_ALERT_MAX} อันที่แรงสุด",
            owner="Community",
        ))

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
        bucket_minutes=mins,
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
        alert_items=items_out,
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
        # alerts แบบแยกส่วน — หน้าเว็บใช้ทำการ์ด + ปุ่มกรองคอมเมนต์ที่เกี่ยวข้อง
        "alert_items": [
            {"kind": a.kind, "level": a.level, "title": a.title, "detail": a.detail,
             "owner": a.owner, "topic": a.topic, "bucket_iso": a.bucket_iso,
             "comment_id": a.comment_id}
            for a in rep.alert_items
        ],
        "topic_breakdown": [[t, n] for t, n in rep.topic_breakdown],
        "topic_trends": [
            {"topic": t.topic, "label": t.label, "negative": t.negative, "severity": t.severity,
             "share": t.share, "owner": t.owner, "peak": t.peak, "is_emerging": t.is_emerging,
             "peak_iso": t.peak_iso}
            for t in rep.topic_trends
        ],
        # start_iso ต้องมีคู่กับ start เพราะข้อมูลจริงกินหลายวัน — %H:%M อย่างเดียวซ้ำกันข้ามวัน
        "buckets": [
            {"start": b.start.strftime("%H:%M"), "start_iso": b.start.isoformat(),
             "total": b.total, "negative": b.negative,
             "severity": round(b.severity, 1), "baseline": b.baseline, "is_spike": b.is_spike}
            for b in rep.buckets
        ],
        "bucket_minutes": rep.bucket_minutes,
        "thresholds": {"spike_factor": SPIKE_FACTOR, "min_severity": MIN_SEVERITY,
                       "viral_reach": VIRAL_REACH},
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
