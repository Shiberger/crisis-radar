"""สร้าง dashboard.html แบบ static (ไม่พึ่ง lib ภายนอก) จากผล crisis report.

ใช้ตอน CLI (run_demo / scrape --run). เวอร์ชัน interactive เต็ม (ค้นหา/กรอง) อยู่ที่
backend/static/index.html. ธีม + โทนสีตรงกัน (formal minimal, light).
"""
from __future__ import annotations

import html

from .crisis.detector import CrisisReport
from .models import Classified

_STATUS = {"NORMAL": ("#0ca30c", "ปกติ"), "WATCH": ("#fab219", "เฝ้าระวัง"), "CRISIS": ("#d03b3b", "วิกฤต")}
_SENT = {"positive": ("#0ca30c", "บวก"), "neutral": ("#898781", "กลาง"), "negative": ("#d03b3b", "ลบ")}


def _bar(label: str, value: int, total: int, color: str) -> str:
    pct = (value / total * 100) if total else 0
    return (f'<div class="row"><span class="k">{html.escape(label)}</span>'
            f'<span class="track"><span class="fill" style="width:{pct:.1f}%;background:{color}"></span></span>'
            f'<span class="n">{value}</span></div>')


def render_html(rep: CrisisReport, classified: list[Classified]) -> str:
    color, th = _STATUS[rep.status]
    total = rep.total or 1
    sm = rep.sentiment_mix
    negP = round(sm.get("negative", 0) / total * 100)
    max_sev = max((s.severity for s in rep.buckets), default=1) or 1
    reaches = [c.comment.reach for c in classified]
    avg_reach = round(sum(reaches) / len(reaches), 1) if reaches else 0
    uniq = len({c.comment.author for c in classified})

    kpis = [("คอมเมนต์ทั้งหมด", rep.total), ("เชิงลบ", f"{negP}%"), ("จำนวนลบ", sm.get("negative", 0)),
            ("ผู้คอมเมนต์", uniq), ("reach เฉลี่ย", avg_reach), ("ส่งต่อ LLM", rep.escalated_count)]
    kpi_html = "".join(f'<div class="kpi"><div class="v">{v}</div><div class="l">{k}</div></div>' for k, v in kpis)

    sent_html = "".join(_bar(_SENT[k][1], sm.get(k, 0), total, _SENT[k][0]) for k in ("negative", "neutral", "positive"))
    tmax = max((n for _, n in rep.topic_breakdown), default=1)
    topic_html = "".join(_bar(t, n, tmax, "#2a78d6") for t, n in rep.topic_breakdown) or '<div class="muted">ไม่มีประเด็นเชิงลบ</div>'

    timeline = "".join(
        f'<div class="col"><div class="bar {"sp" if s.is_spike else ""}" style="height:{s.severity/max_sev*100:.0f}%" '
        f'title="{s.start:%H:%M} · severity {s.severity:.0f}"></div><div class="x">{s.start:%H:%M}</div></div>'
        for s in rep.buckets)

    alerts = "".join(f'<div class="alert">{html.escape(a)}</div>' for a in rep.alerts) \
        or '<div class="alert" style="border-left-color:#0ca30c">ไม่มีสัญญาณผิดปกติ</div>'

    top = sorted([c for c in classified if c.sentiment == "negative"], key=lambda c: c.comment.reach, reverse=True)[:15]
    rows = ""
    for c in top:
        cm = c.comment
        s_c, s_t = _SENT[c.sentiment]
        who = f'<a href="{html.escape(cm.profile_url)}" target="_blank" rel="noopener">{html.escape(cm.author)}</a>' if cm.profile_url else html.escape(cm.author)
        link = f'<a href="{html.escape(cm.comment_url)}" target="_blank" rel="noopener">↗</a>' if cm.comment_url else ""
        topics = "".join(f'<span class="topic">{html.escape(t)}</span>' for t in c.topics) or "—"
        rows += (f'<tr><td class="when">{cm.created_at:%d/%m %H:%M}</td><td class="who">{who}</td>'
                 f'<td class="txt">{html.escape(cm.text)}</td>'
                 f'<td><span class="tag" style="color:{s_c}">● {s_t}</span></td>'
                 f'<td>{topics}</td><td class="rch">{cm.reach}</td><td>{link}</td></tr>')

    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crisis Radar — {html.escape(rep.brand.title())}</title>
<style>
body{{margin:0;background:#f9f9f7;color:#0b0b0b;font-family:system-ui,-apple-system,"Noto Sans Thai",sans-serif;font-size:14px}}
.wrap{{max-width:1100px;margin:0 auto;padding:22px}}
a{{color:#2a78d6;text-decoration:none}} .muted{{color:#898781;font-size:13px}}
h1{{font-size:18px;margin:0}} .sub{{color:#898781;font-size:12px;margin:2px 0 16px}}
.pill{{display:inline-block;padding:5px 12px;border-radius:999px;font-weight:600;font-size:13px;color:#fff;background:{color}}}
.card{{background:#fcfcfb;border:1px solid rgba(11,11,11,.1);border-radius:10px;padding:16px;margin-bottom:14px}}
.card h2{{font-size:11px;text-transform:uppercase;letter-spacing:.05em;color:#898781;margin:0 0 12px}}
.kpis{{display:grid;grid-template-columns:repeat(6,1fr);gap:10px;margin-bottom:14px}}
@media(max-width:820px){{.kpis{{grid-template-columns:repeat(3,1fr)}}}}
.kpi{{background:#fcfcfb;border:1px solid rgba(11,11,11,.1);border-radius:10px;padding:13px}}
.kpi .v{{font-size:22px;font-weight:680;font-variant-numeric:tabular-nums}} .kpi .l{{font-size:11px;color:#898781;margin-top:3px}}
.grid{{display:grid;grid-template-columns:1fr 1fr;gap:14px}} @media(max-width:820px){{.grid{{grid-template-columns:1fr}}}}
.row{{display:flex;align-items:center;gap:10px;margin:7px 0;font-size:13px}} .row .k{{width:150px;color:#52514e}}
.track{{flex:1;background:#e1e0d9;border-radius:4px;height:10px;overflow:hidden}} .fill{{display:block;height:100%}}
.row .n{{width:50px;text-align:right;font-variant-numeric:tabular-nums}}
.tl{{display:flex;align-items:flex-end;gap:6px;height:110px;overflow-x:auto}}
.col{{flex:1;min-width:24px;display:flex;flex-direction:column;align-items:center;height:100%;justify-content:flex-end}}
.bar{{width:100%;background:#2a78d6;border-radius:4px 4px 0 0;min-height:2px}} .bar.sp{{background:#d03b3b}}
.x{{font-size:10px;color:#898781;margin-top:4px}}
.alert{{border:1px solid rgba(11,11,11,.1);border-left:3px solid #d03b3b;background:#f9f9f7;border-radius:8px;padding:9px 12px;font-size:13px;margin:7px 0}}
table{{width:100%;border-collapse:collapse;font-size:13px}} th,td{{text-align:left;padding:9px 10px;border-bottom:1px solid rgba(11,11,11,.1);vertical-align:top}}
th{{font-size:11px;text-transform:uppercase;color:#898781}} td.when,td.rch{{white-space:nowrap;color:#52514e}} td.rch{{text-align:right;font-variant-numeric:tabular-nums}}
.tag{{font-weight:600;white-space:nowrap}} .topic{{display:inline-block;font-size:11px;color:#52514e;background:#f9f9f7;border:1px solid rgba(11,11,11,.1);border-radius:5px;padding:1px 7px;margin:1px}}
.tbl{{overflow-x:auto}}
</style></head><body><div class="wrap">
<h1>Crisis Radar — {html.escape(rep.brand.title())}</h1>
<div class="sub">Facebook · <span class="pill">{th} ({rep.status})</span></div>
<div class="kpis">{kpi_html}</div>
<div class="card"><h2>การแจ้งเตือน</h2>{alerts}</div>
<div class="grid" style="margin-bottom:14px">
<div class="card"><h2>อารมณ์คอมเมนต์</h2>{sent_html}</div>
<div class="card"><h2>ประเด็นเชิงลบ</h2>{topic_html}</div>
</div>
<div class="card"><h2>ไทม์ไลน์ความรุนแรง (แดง = พุ่งผิดปกติ)</h2><div class="tl">{timeline}</div></div>
<div class="card"><h2>คอมเมนต์เชิงลบ reach สูงสุด</h2><div class="tbl">
<table><thead><tr><th>เวลา</th><th>ผู้คอมเมนต์</th><th>คอมเมนต์</th><th>อารมณ์</th><th>ประเด็น</th><th>reach</th><th></th></tr></thead>
<tbody>{rows}</tbody></table></div></div>
<div class="muted">Crisis Radar · หน้าเว็บแบบโต้ตอบเต็ม (ค้นหา/กรอง) ที่ backend/server.py</div>
</div></body></html>"""
