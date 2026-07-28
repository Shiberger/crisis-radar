"""ประกอบ "คอมเมนต์ 1 อัน" ให้เป็นข้อความ alert ที่พร้อมเด้งเข้า Discord.

แยกจากตัวส่ง (alerts.py) เพราะสองเรื่องนี้เปลี่ยนคนละจังหวะ — หน้าตาข้อความปรับบ่อยตามที่
ทีมอยากเห็น ส่วนกติกา "ส่งเมื่อไหร่ / ส่งซ้ำได้ไหม" แทบไม่เปลี่ยนเลย

payload ที่ได้มี 2 ชั้นในก้อนเดียว:
  - ชั้นข้อมูลดิบ (comment/routing/report) — n8n เอาไป route เข้า channel, mention role,
    เปิดการ์ด Jira หรือเก็บ log ต่อได้เอง โดยไม่ต้องมาแกะข้อความที่จัดรูปแล้ว
  - ชั้น discord (content + embeds) — สำเร็จรูปตามรูปแบบ Discord webhook API
    n8n จึงเหลือแค่ HTTP Request ยิง {{$json.body.discord}} ไปที่ channel ที่ต้องการ
    (และถ้ายังไม่มี n8n ก็ยิงชั้นนี้เข้า Discord webhook ตรง ๆ ได้เลย)

ทำไมต้องส่ง "ทำไมถึงเด้ง" ไปด้วยเสมอ: alert ที่บอกแค่ว่า "มีคอมเมนต์ลบ" ทำให้คนอ่านต้อง
กลับไปเปิด dashboard ทุกครั้งเพื่อตัดสินว่าควรสนใจไหม — สุดท้ายคือ alert ที่ถูกเมิน
"""
from __future__ import annotations

from ..classify.lexicon import TOPIC_LABELS
from ..crisis.detector import TOPIC_OWNER
from ..timeutil import now_ict

EVENT = "crisis_radar.comment_alert"
VERSION = 1

SENT_TH = {"positive": "บวก", "neutral": "กลาง", "negative": "ลบ"}
STATUS_TH = {"NORMAL": "ปกติ", "WATCH": "เฝ้าระวัง", "CRISIS": "วิกฤต"}
# สีเดียวกับแถบสถานะบน dashboard — ทีมจะได้จำสีได้ว่าระดับไหนโดยไม่ต้องอ่านข้อความ
COLOR = {"high": 0xD03B3B, "medium": 0xFAB219}
ICON = {"high": "🚨", "medium": "🔔"}

MAX_QUOTE = 500     # Discord ตัด description ที่ 4096 — แต่ยาวเกินนี้คนก็ไม่อ่านบนมือถืออยู่ดี
MAX_FIELD = 900     # Discord จำกัด field value ที่ 1024


def _cut(text: str, limit: int) -> str:
    text = str(text or "").strip()
    return text if len(text) <= limit else text[:limit - 1] + "…"


def topic_labels(topics) -> list[str]:
    return [TOPIC_LABELS.get(t, t) for t in (topics or [])]


def owner_of(topics) -> str:
    """ทีมที่เป็นเจ้าของเรื่อง — ใช้ประเด็นแรกเป็นตัวตัดสิน (เรียงตามที่ classifier ให้มา)."""
    for t in topics or []:
        if t in TOPIC_OWNER:
            return TOPIC_OWNER[t]
    return "Community"


def _headline(row: dict, trigger: str, severity: str) -> str:
    """พาดหัวต้องบอกได้ใน 1 บรรทัดว่า 'ใครเป็นคนบอกว่าเรื่องนี้สำคัญ' — ระบบ (🚨) หรือคน (🔔)."""
    if trigger == "manual":
        ai = SENT_TH.get(row.get("ai_sentiment") if row.get("overridden") else row.get("sentiment"), "—")
        return f"🔔 ทีมส่งเรื่องนี้เข้ามาเอง — ระบบอ่านเป็น “{ai}”"
    return f"{ICON.get(severity, '🚨')} คอมเมนต์เชิงลบแรง — คนกดไลก์/ตอบกลับ {int(row.get('reach') or 0):,} ครั้ง"


def build_discord(row: dict, *, severity: str, reason: str, note: str, report: dict,
                  page: dict, trigger: str, role_id: str = "",
                  dashboard_url: str = "") -> dict:
    """ก้อนที่ยิงเข้า Discord webhook ได้ตรง ๆ (content + embeds)."""
    topics = topic_labels(row.get("topics"))
    owner = owner_of(row.get("topics"))
    status = report.get("status", "NORMAL")
    links = []
    if row.get("comment_url"):
        links.append(f"[เปิดคอมเมนต์บน Facebook]({row['comment_url']})")
    if dashboard_url:
        links.append(f"[เปิด Dashboard]({dashboard_url})")

    fields = [
        {"name": "อารมณ์ที่ระบบให้", "value": SENT_TH.get(row.get("sentiment"), "—")
                                              + (" · ทีมแก้เอง" if row.get("overridden") else ""),
         "inline": True},
        {"name": "ไลก์+ตอบกลับ", "value": f"{int(row.get('reach') or 0):,}", "inline": True},
        {"name": "ประเด็น", "value": " · ".join(topics) or "—", "inline": True},
        {"name": "ทำไมถึงเด้ง", "value": _cut(reason, MAX_FIELD), "inline": False},
    ]
    if note:
        fields.append({"name": "หมายเหตุจากคนที่กดแจ้ง", "value": _cut(note, MAX_FIELD), "inline": False})
    if row.get("post_title"):
        fields.append({"name": "อยู่ใต้โพสต์", "value": _cut(row["post_title"], MAX_FIELD), "inline": False})
    if links:
        fields.append({"name": "ลิงก์", "value": " · ".join(links), "inline": False})

    embed = {
        "title": _cut(_headline(row, trigger, severity), 250),
        "description": f"> {_cut(row.get('text'), MAX_QUOTE)}\n— โดย **{_cut(row.get('author') or '—', 80)}**",
        "color": COLOR.get(severity, COLOR["medium"]),
        "fields": fields,
        "footer": {"text": f"Crisis Radar · {page.get('page_name') or report.get('brand', '')}"
                           f" · สถานะเพจตอนนี้: {STATUS_TH.get(status, status)}"
                           f" · ส่งต่อ: {owner}"},
    }
    if row.get("created_at"):
        embed["timestamp"] = row["created_at"]      # เวลาของคอมเมนต์ ไม่ใช่เวลาที่ส่ง
    if row.get("comment_url"):
        embed["url"] = row["comment_url"]

    # mention เฉพาะเรื่องที่มี role map ไว้ — ไม่มีก็ไม่ ping ใคร (ping มั่วคือทางลัดสู่การถูก mute)
    content = f"<@&{role_id}>" if role_id else ""
    return {"content": content, "embeds": [embed]}


def build_event(row: dict, *, trigger: str, severity: str, reason: str, report: dict,
                note: str = "", page: dict | None = None, role_id: str = "",
                dashboard_url: str = "") -> dict:
    """ก้อนเต็มที่ส่งให้ n8n — ข้อมูลดิบ + ข้อความ Discord สำเร็จรูปในก้อนเดียว."""
    page = page or {}
    topics = list(row.get("topics") or [])
    return {
        "event": EVENT,
        "version": VERSION,
        "trigger": trigger,                 # 'auto' = ระบบเห็นเอง · 'manual' = คนกดแจ้ง
        "severity": severity,               # 'high' | 'medium' — n8n ใช้เลือก channel/ping
        "reason": reason,
        "sent_at": now_ict().isoformat(timespec="seconds"),
        "brand": report.get("brand", ""),
        "page": {"name": page.get("page_name", ""), "url": page.get("page_url", "")},
        "report": {
            "status": report.get("status", ""),
            "total": report.get("total", 0),
            "negative": (report.get("sentiment_mix") or {}).get("negative", 0),
            "generated_at": report.get("generated_at", ""),
            "dashboard_url": dashboard_url,
        },
        "comment": {
            "comment_id": row.get("comment_id", ""),
            "author": row.get("author", ""),
            "text": row.get("text", ""),
            "created_at": row.get("created_at", ""),
            "reach": int(row.get("reach") or 0),
            "url": row.get("comment_url", ""),
            "profile_url": row.get("profile_url", ""),
            "post_title": row.get("post_title", ""),
            "sentiment": row.get("sentiment", ""),
            "ai_sentiment": row.get("ai_sentiment", "") or row.get("sentiment", ""),
            "overridden": bool(row.get("overridden")),
            "confidence": row.get("confidence", 0),
            "topics": topics,
            "topic_labels": topic_labels(topics),
        },
        "routing": {
            "owner": owner_of(topics),
            "topic": topics[0] if topics else "",
            "role_id": role_id,
        },
        "note": note,
        "discord": build_discord(row, severity=severity, reason=reason, note=note,
                                 report=report, page=page, trigger=trigger,
                                 role_id=role_id, dashboard_url=dashboard_url),
    }
