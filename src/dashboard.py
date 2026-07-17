"""สร้าง dashboard.html แบบ self-contained (ไม่พึ่ง lib ภายนอก) จากผล crisis report.

เดโม่นี้ render เป็น static HTML. เวอร์ชัน production จะย้ายเป็น React (reuse stack
ของ Warz: Vite+React+TS+Tailwind+Recharts) ที่ดึงข้อมูลสดจาก API.
"""
from __future__ import annotations

import html

from .crisis.detector import CrisisReport
from .models import Classified

_STATUS = {
    "NORMAL": ("#16a34a", "🟢", "ปกติ"),
    "WATCH": ("#d97706", "🟡", "เฝ้าระวัง"),
    "CRISIS": ("#dc2626", "🔴", "วิกฤต"),
}
_SENT_COLOR = {"positive": "#16a34a", "neutral": "#94a3b8", "negative": "#dc2626"}


def _bar(label: str, value: int, total: int, color: str) -> str:
    pct = (value / total * 100) if total else 0
    return (
        f'<div class="row"><span class="lbl">{html.escape(label)}</span>'
        f'<span class="track"><span class="fill" style="width:{pct:.1f}%;background:{color}"></span></span>'
        f'<span class="val">{value}</span></div>'
    )


def render_html(rep: CrisisReport, classified: list[Classified]) -> str:
    color, dot, th = _STATUS[rep.status]
    total = rep.total or 1
    max_sev = max((s.severity for s in rep.buckets), default=1) or 1

    alerts_html = "".join(f"<li>{html.escape(a)}</li>" for a in rep.alerts) or "<li>ไม่มีสัญญาณผิดปกติ</li>"

    sent_html = "".join(
        _bar(k, rep.sentiment_mix.get(k, 0), total, _SENT_COLOR[k])
        for k in ("positive", "neutral", "negative")
    )
    topic_html = "".join(
        _bar(t, n, max((n for _, n in rep.topic_breakdown), default=1), "#dc2626")
        for t, n in rep.topic_breakdown
    ) or '<div class="muted">ไม่มีประเด็นลบ</div>'

    timeline = ""
    for s in rep.buckets:
        h = s.severity / max_sev * 100
        spike = " spike" if s.is_spike else ""
        timeline += (
            f'<div class="tl-col"><div class="tl-bar{spike}" style="height:{h:.0f}%" '
            f'title="severity {s.severity:.0f}"></div><div class="tl-x">{s.start:%H:%M}</div></div>'
        )

    top_neg = sorted(
        [c for c in classified if c.sentiment == "negative"],
        key=lambda c: c.comment.reach, reverse=True,
    )[:8]
    rows = "".join(
        f"<tr><td>{c.comment.created_at:%H:%M}</td>"
        f"<td>{html.escape(c.comment.text)}</td>"
        f"<td>{html.escape(', '.join(c.topics) or '-')}</td>"
        f"<td class='r'>{c.comment.reach}</td>"
        f"<td>{'LLM' if c.escalated_to_llm else '—'}</td></tr>"
        for c in top_neg
    )

    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crisis Radar — {html.escape(rep.brand.title())}</title>
<style>
:root{{color-scheme:light dark}}
*{{box-sizing:border-box}}
body{{font-family:-apple-system,'Segoe UI',Roboto,'Noto Sans Thai',sans-serif;margin:0;
background:#0f172a;color:#e2e8f0;padding:24px;line-height:1.5}}
.wrap{{max-width:960px;margin:0 auto}}
h1{{font-size:20px;margin:0 0 4px}} .sub{{color:#94a3b8;font-size:13px;margin-bottom:20px}}
.banner{{background:{color};color:#fff;padding:16px 20px;border-radius:12px;font-size:18px;
font-weight:700;margin-bottom:20px;display:flex;justify-content:space-between;align-items:center}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:16px;margin-bottom:16px}}
@media(max-width:720px){{.grid{{grid-template-columns:1fr}}}}
.card{{background:#1e293b;border:1px solid #334155;border-radius:12px;padding:16px}}
.card h2{{font-size:13px;text-transform:uppercase;letter-spacing:.05em;color:#94a3b8;margin:0 0 12px}}
.row{{display:flex;align-items:center;gap:8px;margin:6px 0;font-size:13px}}
.lbl{{width:120px;color:#cbd5e1}} .track{{flex:1;background:#334155;border-radius:6px;height:12px;overflow:hidden}}
.fill{{display:block;height:100%}} .val{{width:32px;text-align:right;font-variant-numeric:tabular-nums}}
.alerts{{list-style:none;padding:0;margin:0}} .alerts li{{background:#334155;border-left:3px solid {color};
padding:8px 12px;border-radius:6px;margin:6px 0;font-size:13px}}
.tl{{display:flex;align-items:flex-end;gap:10px;height:130px;padding-top:8px}}
.tl-col{{flex:1;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}}
.tl-bar{{width:100%;background:#3b82f6;border-radius:4px 4px 0 0;min-height:3px}}
.tl-bar.spike{{background:#dc2626}} .tl-x{{font-size:11px;color:#94a3b8;margin-top:4px}}
table{{width:100%;border-collapse:collapse;font-size:13px}}
th,td{{text-align:left;padding:8px;border-bottom:1px solid #334155;vertical-align:top}}
th{{color:#94a3b8;font-size:11px;text-transform:uppercase}} td.r,.r{{text-align:right}}
.muted{{color:#64748b;font-size:13px}} .foot{{color:#64748b;font-size:11px;margin-top:20px}}
</style></head><body><div class="wrap">
<h1>📡 Crisis Radar — {html.escape(rep.brand.title())}</h1>
<div class="sub">ช่องทาง Facebook · ข้อมูลเดโม่ (synthetic fixture) · masked PII</div>
<div class="banner"><span>{dot} สถานะ: {th} ({rep.status})</span>
<span style="font-size:13px;font-weight:400">คอมเมนต์ {rep.total} · ส่งต่อ LLM {rep.escalated_count}</span></div>
<div class="card" style="margin-bottom:16px"><h2>🔔 Alert</h2><ul class="alerts">{alerts_html}</ul></div>
<div class="grid">
<div class="card"><h2>Sentiment</h2>{sent_html}</div>
<div class="card"><h2>ประเด็นลบ (topic)</h2>{topic_html}</div>
</div>
<div class="card" style="margin-bottom:16px"><h2>Timeline — severity คอมเมนต์ลบ (แดง = spike)</h2>
<div class="tl">{timeline}</div></div>
<div class="card"><h2>คอมเมนต์ลบ reach สูงสุด</h2>
<table><thead><tr><th>เวลา</th><th>คอมเมนต์</th><th>topic</th><th class="r">reach</th><th>ชั้น AI</th></tr></thead>
<tbody>{rows}</tbody></table></div>
<div class="foot">Crisis Radar demo · Talesrunner · generated offline · ข้อมูลสังเคราะห์เพื่อพิสูจน์ pipeline</div>
</div></body></html>"""
