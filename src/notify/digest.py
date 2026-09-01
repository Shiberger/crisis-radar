"""สรุปประจำวัน 1 ข้อความ — สำหรับกรณีที่ดึงข้อมูลได้วันละรอบเดียว (คุมเครดิต Apify).

ต่างจาก alert รายคอมเมนต์ (alerts.py) ตรงคำถามที่ตอบ:
  alert  → "มีคอมเมนต์นี้ที่ต้องรีบดูตอนนี้"        เกิดเมื่อไหร่ก็ได้ · 1 คอมเมนต์ = 1 ข้อความ
  digest → "เมื่อวานเพจเป็นยังไง วันนี้ต้องสนใจอะไร" วันละครั้ง · ทั้งรอบ = 1 ข้อความ

ทำไมต้องมีทั้งคู่: ที่ interval วันละรอบ คอมเมนต์แรงจะถูก auto-alert ตอนดึงอยู่แล้ว แต่ทีมยัง
ไม่เห็น "ภาพรวม" — วันที่ไม่มีคอมเมนต์ไหนเกินเกณฑ์เลยจะเงียบสนิท ซึ่งอ่านไม่ออกว่าเงียบเพราะ
ปกติดี หรือเงียบเพราะระบบพัง digest จึงส่งทุกวันแม้สถานะ NORMAL — เป็นสัญญาณชีพของระบบด้วย

โหมดส่ง 2 แบบ (เลือกที่ตัวเรียก):
  pull  — /api/digest คืน payload กลับไป ให้ n8n เป็นคนยิงเข้า Discord เอง (ค่าเริ่มต้น
          ของ workflow รายวัน เพราะ n8n เป็นคนเรียกอยู่แล้ว ไม่ต้องวิ่งกลับไปกลับมา)
  push  — ส่ง {"push": true} → Crisis Radar ยิงเข้า N8N_WEBHOOK_URL เองเหมือน alert ปกติ
          (ใช้ตอน cron อยู่ที่อื่น เช่น cron-job.org / GitHub Actions ที่ไม่มีที่ให้ต่อ Discord)

กันส่งซ้ำ: จำไว้ที่ data/alerts_sent.json คีย์ "digest:YYYY-MM-DD" — n8n retry หรือมีคนกดซ้ำ
ในวันเดียวกันจะไม่ได้ข้อความซ้ำ (ยกเว้นสั่ง force)

ตั้งค่าผ่าน env:
  DIGEST_TOP=3        โชว์คอมเมนต์ลบที่คนเห็นเยอะสุดกี่อันในข้อความ
"""
from __future__ import annotations

import os

from ..timeutil import now_ict
from . import alerts
from .payload import COLOR, MAX_FIELD, SENT_TH, STATUS_TH, _cut, owner_of, topic_labels

EVENT = "crisis_radar.daily_digest"
VERSION = 1

# สีตามสถานะเพจ ไม่ใช่ตามความแรงคอมเมนต์ — digest พูดถึงทั้งเพจ
STATUS_COLOR = {"CRISIS": COLOR["high"], "WATCH": COLOR["medium"], "NORMAL": 0x3BA55D}
STATUS_ICON = {"CRISIS": "🚨", "WATCH": "🔔", "NORMAL": "✅"}


def key_for(day: str = "") -> str:
    """คีย์กันส่งซ้ำรายวัน — วันตามเวลาไทย ไม่ใช่ UTC (ไม่งั้นสรุปเช้าตรู่จะข้ามวันผิด)."""
    return f"digest:{day or now_ict().strftime('%Y-%m-%d')}"


def _delta(now: int, prev: int | None) -> str:
    """เขียนส่วนต่างจากรอบก่อนให้อ่านออกใน 1 หน่วยสายตา — ไม่มีของเทียบก็ไม่ต้องเดา."""
    if prev is None:
        return ""
    d = now - prev
    if d == 0:
        return " (เท่าเมื่อวาน)"
    return f" ({'+' if d > 0 else '−'}{abs(d)} จากรอบก่อน)"


def _pct(part: int, total: int) -> str:
    return f"{round(part * 100 / total)}%" if total else "—"


def top_negative(result: dict, limit: int) -> list[dict]:
    """คอมเมนต์ลบที่คนเห็นเยอะสุด — ตัวที่ทีมควรอ่านก่อนถ้ามีเวลาอ่านแค่ 3 อัน."""
    rows = [c for c in (result.get("comments") or [])
            if c.get("sentiment") == "negative" and not c.get("archived")]
    rows.sort(key=lambda c: int(c.get("reach") or 0), reverse=True)
    return rows[:limit]


def _line(row: dict) -> str:
    reach = int(row.get("reach") or 0)
    text = _cut(row.get("text"), 150)
    url = row.get("comment_url") or ""
    head = f"[{text}]({url})" if url else text
    # ติ๊กถูกให้ตัวที่เด้งไปแล้ว — ทีมจะได้ไม่ต้องเดาว่านี่ของใหม่หรือของที่เพิ่งคุยกันไป
    seen = " ✅ แจ้งแล้ว" if row.get("alerted_at") else ""
    topics = " · ".join(topic_labels(row.get("topics"))[:2])
    return f"**{reach:,}** ไลก์+ตอบกลับ · {topics or 'ไม่ระบุประเด็น'}{seen}\n{head}"


def build_discord(result: dict, *, page: dict, prev: dict | None, top: list[dict],
                  dashboard_url: str, role_id: str = "") -> dict:
    status = result.get("status", "NORMAL")
    total = int(result.get("total") or 0)
    mix = result.get("sentiment_mix") or {}
    neg = int(mix.get("negative") or 0)
    prev_neg = int(prev.get("negative")) if prev and prev.get("negative") is not None else None

    fields = [
        {"name": "คอมเมนต์ที่อ่านรอบนี้", "value": f"{total:,}", "inline": True},
        {"name": "เชิงลบ", "value": f"{neg:,} · {_pct(neg, total)}{_delta(neg, prev_neg)}",
         "inline": True},
        {"name": "คนคอมเมนต์", "value": f"{int(result.get('unique_authors') or 0):,}", "inline": True},
    ]

    trends = [t for t in (result.get("topic_trends") or []) if t.get("negative")][:3]
    if trends:
        fields.append({"name": "ประเด็นที่ถูกบ่นมากสุด", "inline": False,
                       "value": _cut("\n".join(
                           f"• **{t.get('label') or t.get('topic')}** {t.get('negative')} คอมเมนต์"
                           f" → {t.get('owner') or 'Community'}"
                           + ("  🆕 เพิ่งโผล่" if t.get("is_emerging") else "")
                           for t in trends), MAX_FIELD)})

    if top:
        fields.append({"name": f"คอมเมนต์ลบที่คนเห็นเยอะสุด ({len(top)} อันดับแรก)", "inline": False,
                       "value": _cut("\n\n".join(_line(r) for r in top), MAX_FIELD)})
    else:
        fields.append({"name": "คอมเมนต์ลบที่ต้องดู", "value": "ไม่มีเลยรอบนี้ — เพจปกติ",
                       "inline": False})

    alert_items = result.get("alert_items") or []
    if alert_items:
        fields.append({"name": "สัญญาณที่ระบบจับได้", "inline": False,
                       "value": _cut("\n".join(f"• {a.get('title', '')}" for a in alert_items[:4]),
                                     MAX_FIELD)})
    if dashboard_url:
        fields.append({"name": "ดูทั้งหมด", "value": f"[เปิด Dashboard]({dashboard_url})",
                       "inline": False})

    page_name = page.get("page_name") or result.get("brand", "")
    embed = {
        "title": f"{STATUS_ICON.get(status, '📊')} สรุปประจำวัน — {page_name} · "
                 f"สถานะ {STATUS_TH.get(status, status)}",
        "description": _summary_line(status, neg, total, len(top)),
        "color": STATUS_COLOR.get(status, STATUS_COLOR["NORMAL"]),
        "fields": fields,
        "footer": {"text": f"Crisis Radar · ข้อมูลดึงเมื่อ {result.get('generated_at', '—')}"
                           f" · ที่มา {result.get('source', '')}"},
        "timestamp": now_ict().isoformat(timespec="seconds"),
    }
    if page.get("page_url"):
        embed["url"] = page["page_url"]
    # ping เฉพาะวันที่สถานะไม่ปกติ — สรุปวันที่ทุกอย่างเรียบร้อยไม่ควรเด้งใส่ใคร
    content = f"<@&{role_id}>" if role_id and status != "NORMAL" else ""
    return {"content": content, "embeds": [embed]}


def _summary_line(status: str, neg: int, total: int, n_top: int) -> str:
    """หัวข้อความต้องตอบได้ทันทีว่า 'วันนี้ต้องลงมือทำอะไรไหม' — ไม่ใช่แค่รายงานตัวเลข."""
    if status == "CRISIS":
        return f"**ต้องจัดการวันนี้** — เชิงลบ {neg:,} จาก {total:,} คอมเมนต์ และกระจุกตัวผิดปกติ"
    if status == "WATCH":
        return f"**เฝ้าระวัง** — เชิงลบ {neg:,} จาก {total:,} คอมเมนต์ ยังไม่ถึงขั้นวิกฤต แต่ขยับขึ้น"
    if n_top:
        return f"ปกติ — เชิงลบ {neg:,} จาก {total:,} คอมเมนต์ มีที่ควรอ่าน {n_top} อัน"
    return f"ปกติ — เชิงลบ {neg:,} จาก {total:,} คอมเมนต์ ไม่มีอะไรต้องรีบ"


def build_event(result: dict, *, page: dict | None = None, prev: dict | None = None,
                cfg: dict | None = None) -> dict:
    """ก้อนเต็ม: ข้อมูลดิบให้ n8n route ต่อ + ข้อความ Discord สำเร็จรูป (โครงเดียวกับ alert)."""
    cfg = cfg or alerts.config()
    page = page or {}
    try:
        limit = max(0, int(str(os.environ.get("DIGEST_TOP", "")).strip() or 3))
    except ValueError:
        limit = 3
    top = top_negative(result, limit)
    mix = result.get("sentiment_mix") or {}
    status = result.get("status", "NORMAL")
    role_id = alerts._role_for([t.get("topic") for t in (result.get("topic_trends") or [])], cfg)

    return {
        "event": EVENT,
        "version": VERSION,
        "trigger": "schedule",
        "severity": "high" if status == "CRISIS" else ("medium" if status == "WATCH" else "low"),
        "date": f"{now_ict():%Y-%m-%d}",
        "sent_at": now_ict().isoformat(timespec="seconds"),
        "brand": result.get("brand", ""),
        "page": {"name": page.get("page_name", ""), "url": page.get("page_url", "")},
        "report": {
            "status": status,
            "total": int(result.get("total") or 0),
            "negative": int(mix.get("negative") or 0),
            "neutral": int(mix.get("neutral") or 0),
            "positive": int(mix.get("positive") or 0),
            "unique_authors": int(result.get("unique_authors") or 0),
            "max_reach": int(result.get("max_reach") or 0),
            "escalated_count": int(result.get("escalated_count") or 0),
            "alert_sent_count": int(result.get("alert_sent_count") or 0),
            "generated_at": result.get("generated_at", ""),
            "source": result.get("source", ""),
            "dashboard_url": cfg["dashboard_url"],
        },
        "previous": prev or {},
        "topics": [{"topic": t.get("topic"), "label": t.get("label"), "negative": t.get("negative"),
                    "owner": t.get("owner"), "is_emerging": bool(t.get("is_emerging"))}
                   for t in (result.get("topic_trends") or [])[:5]],
        "alerts": [{"title": a.get("title"), "level": a.get("level"), "owner": a.get("owner"),
                    "topic": a.get("topic")} for a in (result.get("alert_items") or [])],
        "top_negative": [{"comment_id": r.get("comment_id"), "author": r.get("author"),
                          "text": r.get("text"), "reach": int(r.get("reach") or 0),
                          "url": r.get("comment_url"), "topics": r.get("topics") or [],
                          "sentiment": SENT_TH.get(r.get("sentiment"), ""),
                          "owner": owner_of(r.get("topics")),
                          "alerted_at": r.get("alerted_at", "")} for r in top],
        "routing": {"owner": owner_of([t.get("topic") for t in (result.get("topic_trends") or [])]),
                    "role_id": role_id},
        "discord": build_discord(result, page=page, prev=prev, top=top,
                                 dashboard_url=cfg["dashboard_url"], role_id=role_id),
    }


def send(result: dict, *, page: dict | None = None, prev: dict | None = None,
         push: bool = False, force: bool = False) -> dict:
    """ประกอบสรุปประจำวัน · กันซ้ำรายวัน · (push=True) ยิงออกเอง.

    คืน {"skipped": True, ...} ถ้าวันนี้ส่งไปแล้ว — ไม่ raise เพราะ n8n retry ไม่ใช่ความผิดพลาด
    ที่คนต้องมาแก้ workflow ล้มเหลวจริง ๆ (ปลายทางล่ม) ยังคง raise RuntimeError เหมือนเดิม
    """
    cfg = alerts.config()
    if push and not cfg["url"]:
        raise ValueError("ยังไม่ได้ตั้ง N8N_WEBHOOK_URL (หรือ DISCORD_WEBHOOK_URL) — ส่งเองไม่ได้")

    k = key_for()
    prev_rec = alerts.sent_record(k)
    if prev_rec and not force:
        return {"skipped": True, "reason": f"สรุปของวันนี้ส่งไปแล้วเมื่อ {prev_rec.get('at', '')}",
                "sent_at": prev_rec.get("at", "")}

    event = build_event(result, page=page, prev=prev, cfg=cfg)
    if push:
        alerts._post(cfg, event)
    rec = alerts._mark(k, {"at": now_ict().isoformat(timespec="minutes"), "trigger": "schedule",
                           "severity": event["severity"], "via": cfg["via"] if push else "pull",
                           "status": event["report"]["status"]})
    return {"skipped": False, "pushed": push, "at": rec["at"], **event}
