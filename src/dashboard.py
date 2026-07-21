"""สร้าง dashboard.html แบบ static (ไม่พึ่ง lib ภายนอก) จากผล crisis report.

ใช้ตอน CLI (run_demo / scrape --run) และตอนส่งไฟล์ให้คนอื่นเปิดดูเอง
เวอร์ชัน interactive เต็ม (ค้นหา/กรอง/เจาะดูรายคอมเมนต์) อยู่ที่ backend/static/index.html
— หน้านี้ใช้ภาษาและลำดับการเล่าเรื่องชุดเดียวกัน เพื่อให้คนที่เห็นทั้งสองที่ไม่สับสน:
     สถานะ → ควรทำอะไรต่อ → ตัวเลขสำคัญ → เรื่องที่คนบ่น → เกิดตอนไหน → คอมเมนต์จริง
"""
from __future__ import annotations

import html

from .crisis.detector import CrisisReport
from .models import Classified

# หัวเรื่องพูดแบบคน ไม่ใช่ศัพท์ระบบ — คนอ่านต้องรู้ทันทีว่าต้องรีบไหม
_STATUS = {
    "NORMAL": ("#0f8a4a", "ปกติ", "ปกติดี — ยังไม่มีอะไรต้องรีบ"),
    "WATCH": ("#dd9b09", "เฝ้าระวัง", "ควรเฝ้าระวัง"),
    "CRISIS": ("#d33b34", "วิกฤต", "วิกฤต — ต้องรีบจัดการ"),
}
_SENT = {"positive": ("#0f8a4a", "บวก"), "neutral": ("#9c9a91", "กลาง"), "negative": ("#d33b34", "ลบ")}
_ALERT_ICON = {"spike": ("🚨", "#d33b34"), "emerging": ("📈", "#dd9b09"), "viral": ("🔥", "#dd9b09")}

E = html.escape


def _verdict(rep: CrisisReport) -> tuple[str, str]:
    """ประโยคสรุป + สิ่งที่ควรทำต่อ (ตรรกะเดียวกับหน้าเว็บ backend/static/index.html)."""
    total = rep.total or 1
    neg_p = round(rep.sentiment_mix.get("negative", 0) / total * 100)
    spike = next((b for b in rep.buckets if b.is_spike), None)
    emerging = [t for t in rep.topic_trends if t.is_emerging]
    viral = [a for a in rep.alert_items if a.kind == "viral"]
    top = rep.topic_trends[0] if rep.topic_trends else None

    if spike:
        times = round(spike.severity / spike.baseline) if spike.baseline else 0
        lead = next((a for a in rep.alert_items if a.kind == "spike"), None)
        owner = (lead.owner if lead else None) or (top.owner if top else "ทีมที่เกี่ยวข้อง")
        summary = (f"คอมเมนต์ลบ<b>พุ่งผิดปกติ</b>ช่วง <b>{spike.start:%H:%M} น.</b> — ชั่วโมงนั้นมีคอมเมนต์ลบ "
                   f"{spike.negative} จาก {spike.total} คอมเมนต์"
                   + (f" แรงกว่าช่วงปกติราว {times:,} เท่า" if times > 1 else "")
                   + (f" · เรื่องที่คนบ่นมากสุดคือ “{E(top.label)}”" if top else ""))
        action = (f"แจ้ง <b>{E(owner)}</b> ให้ตรวจสอบทันที · เตรียมข้อความชี้แจงในเพจ · "
                  f"กลับมาตรวจซ้ำอีกครั้งใน 1 ชั่วโมง")
    elif emerging:
        e = emerging[0]
        summary = (f"ยังไม่ถึงขั้นวิกฤต แต่เรื่อง <b>“{E(e.label)}”</b> ถูกพูดถึงในแง่ลบมากขึ้นในช่วงล่าสุด "
                   f"({e.negative} คอมเมนต์ · {e.share:.0f}% ของคอมเมนต์ลบทั้งหมด)")
        action = f"ให้ <b>{E(e.owner)}</b> รับทราบไว้ก่อน · ตรวจซ้ำอีกครั้งใน 1–2 ชั่วโมงเพื่อดูว่าโตต่อไหม"
    elif viral:
        summary = f"มีคอมเมนต์เชิงลบที่<b>คนเห็นเยอะผิดปกติ</b> {len(viral)} รายการ แม้ภาพรวมยังไม่พุ่ง"
        action = "เข้าไปตอบคอมเมนต์นั้นก่อนที่คนจะแชร์ต่อ · ดูรายการด้านล่าง"
    elif neg_p > 40:
        summary = f"คอมเมนต์ส่วนใหญ่เป็นเชิงลบ (<b>{neg_p}%</b>) แม้ยังไม่มีช่วงเวลาไหนที่พุ่งผิดปกติ"
        action = "ยังไม่ต้องประกาศอะไร แต่ควรดูว่าเป็นความไม่พอใจสะสมเรื่องอะไร (ดูตาราง “เรื่องที่คนบ่น”)"
    else:
        summary = f"ไม่พบช่วงเวลาที่คอมเมนต์ลบพุ่งผิดปกติ · อารมณ์โดยรวมอยู่ในเกณฑ์ปกติ (ลบ {neg_p}%)"
        action = "ยังไม่ต้องทำอะไรเป็นพิเศษ · ตรวจซ้ำอีกครั้งในอีก 2–3 ชั่วโมงก็พอ"
    return summary, action


def render_html(rep: CrisisReport, classified: list[Classified]) -> str:
    color, short, head = _STATUS[rep.status]
    total = rep.total or 1
    sm = rep.sentiment_mix
    neg_p = round(sm.get("negative", 0) / total * 100)
    uniq = len({c.comment.author for c in classified})
    times = [c.comment.created_at for c in classified]
    window = (f"{min(times):%d/%m %H:%M}–{max(times):%H:%M} น." if times else "—")
    summary, action = _verdict(rep)

    negatives = sorted([c for c in classified if c.sentiment == "negative"],
                       key=lambda c: c.comment.reach, reverse=True)
    loud = negatives[0] if negatives else None
    worst = max(rep.buckets, key=lambda b: b.severity, default=None)

    # ── KPI: 4 ตัวที่ตอบคำถามคนอ่านจริง ๆ (ไม่ใช่ตัวเลขดิบที่ตีความไม่ได้)
    kpis = [
        ("คอมเมนต์ที่อ่านทั้งหมด", f"{rep.total:,}", f"ในช่วง {window}", ""),
        ("สัดส่วนคอมเมนต์เชิงลบ", f"{neg_p}<small>%</small>",
         f"{sm.get('negative', 0):,} จาก {rep.total:,} คอมเมนต์",
         color if neg_p >= 40 else ""),
        # ไม่มีคอมเมนต์ลบเลย = ไม่มี "ชั่วโมงที่หนักสุด" จริง ๆ — โชว์เวลาไปก็ทำให้เข้าใจผิด
        ("ชั่วโมงที่หนักสุด", f"{worst.start:%H:%M}" if worst and worst.negative else "–",
         (f"คอมเมนต์ลบ {worst.negative} จาก {worst.total} รายการ"
          + (" · พุ่งผิดปกติ" if worst.is_spike else "")) if worst and worst.negative
         else "ยังไม่มีคอมเมนต์เชิงลบเลย",
         color if worst and worst.is_spike else ""),
        ("คอมเมนต์ลบที่คนเห็นมากสุด", f"{loud.comment.reach:,}" if loud else "–",
         f"โดย {E(loud.comment.author)}" if loud else "ไม่มีคอมเมนต์เชิงลบ", ""),
    ]
    kpi_html = "".join(
        f'<div class="kpi"><div class="l">{E(l)}</div>'
        f'<div class="v"{f" style=color:{c}" if c else ""}>{v}</div><div class="d">{d}</div></div>'
        for l, v, d, c in kpis)

    # ── สิ่งที่ควรจัดการ
    if rep.alert_items:
        order = {"spike": 0, "emerging": 1, "viral": 2}
        alerts = "".join(
            f'<div class="alert" style="border-left-color:{_ALERT_ICON.get(a.kind, ("", "#9c9a91"))[1]}">'
            f'<span class="ic">{_ALERT_ICON.get(a.kind, ("•", ""))[0]}</span>'
            f'<div><div class="t">{E(a.title)}</div><div class="d">{E(a.detail)}</div>'
            + (f'<span class="owner">ส่งต่อ: {E(a.owner)}</span>' if a.owner else "")
            + "</div></div>"
            for a in sorted(rep.alert_items, key=lambda a: order.get(a.kind, 9)))
    else:
        alerts = ('<div class="alert" style="border-left-color:#0f8a4a"><span class="ic">✅</span>'
                  '<div><div class="t">ยังไม่พบสัญญาณผิดปกติ</div>'
                  '<div class="d">ไม่มีช่วงเวลาที่คอมเมนต์ลบพุ่ง ไม่มีประเด็นใหม่มาแรง '
                  'และไม่มีคอมเมนต์ลบที่กระจายวงกว้าง</div></div></div>')

    # ── อารมณ์: แถบเดียวรวม 100% + รายการย่อย
    stack = "".join(
        f'<i style="width:{sm.get(k, 0) / total * 100:.1f}%;background:{_SENT[k][0]}"></i>'
        for k in ("negative", "neutral", "positive"))
    sent_rows = "".join(
        f'<div class="srow"><span class="sw" style="background:{_SENT[k][0]}"></span>'
        f'<span class="nm">{_SENT[k][1]}</span>'
        f'<span class="pc" style="color:{_SENT[k][0]}">{round(sm.get(k, 0) / total * 100)}%</span>'
        f'<span class="ct">{sm.get(k, 0):,} รายการ</span></div>'
        for k in ("negative", "neutral", "positive"))

    # ── เรื่องที่คนบ่น: แท่งวัดด้วย severity ให้ตรงกับลำดับที่เรียง
    max_sev_topic = max((t.severity for t in rep.topic_trends), default=1) or 1
    topic_html = "".join(
        f'<div class="trow"><span class="rk">{i}</span><div>'
        f'<div class="nm">{E(t.label)}'
        + ('<span class="hot">📈 กำลังมาแรง</span>' if t.is_emerging else "")
        + f'</div><div class="meta">{t.share:.0f}% ของคอมเมนต์ลบ · หนักสุด {E(t.peak)} น. · ทีม {E(t.owner)}</div>'
        f'<div class="tbar"><i style="width:{t.severity / max_sev_topic * 100:.0f}%"></i></div></div>'
        f'<div class="rt"><span class="n">{t.negative}</span><span class="u">คอมเมนต์ลบ</span></div></div>'
        for i, t in enumerate(rep.topic_trends, 1)
    ) or '<div class="muted" style="padding:20px;text-align:center">ไม่พบคอมเมนต์เชิงลบ — ยังไม่มีเรื่องที่ต้องแก้ 🎉</div>'

    # ── ไทม์ไลน์: สูง = คอมเมนต์ทั้งหมดในชั่วโมงนั้น, ส่วนแดงล่าง = เชิงลบ (หน่วยเดียวกับแกน)
    max_total = max((b.total for b in rep.buckets), default=1) or 1
    avg_neg = (sum(b.negative for b in rep.buckets) / len(rep.buckets)) if rep.buckets else 0
    timeline = "".join(
        f'<div class="col" title="{b.start:%H:%M} น. · ทั้งหมด {b.total} · เชิงลบ {b.negative} · ความแรง {b.severity:.0f}">'
        + (f'<span class="flag" style="bottom:calc({b.total / max_total * 100:.1f}% + 6px)">🚨 พุ่ง</span>'
           if b.is_spike else "")
        + f'<span class="stk" style="height:{max(b.total / max_total * 100, 1.2):.1f}%">'
        f'<span class="rest" style="flex:{100 - (b.negative / b.total * 100 if b.total else 0):.1f}"></span>'
        f'<span class="neg" style="flex:{(b.negative / b.total * 100 if b.total else 0):.1f}"></span>'
        f"</span></div>"
        for b in rep.buckets)
    xaxis = "".join(f"<div>{b.start:%H:%M}</div>" for b in rep.buckets)

    # ── คอมเมนต์เชิงลบที่คนเห็นมากสุด 15 อันดับ
    max_reach = max((c.comment.reach for c in classified), default=1) or 1
    rows = ""
    for c in negatives[:15]:
        cm = c.comment
        s_c, s_t = _SENT[c.sentiment]
        who = (f'<a href="{E(cm.profile_url)}" target="_blank" rel="noopener">{E(cm.author)}</a>'
               if cm.profile_url else E(cm.author))
        link = (f'<a href="{E(cm.comment_url)}" target="_blank" rel="noopener" title="เปิดคอมเมนต์">↗</a>'
                if cm.comment_url else "")
        topics = "".join(f'<span class="topic">{E(t)}</span>' for t in c.topics) or "—"
        rows += (f'<tr><td class="when"><b>{cm.created_at:%H:%M}</b>{cm.created_at:%d/%m}</td>'
                 f'<td class="who">{who}</td><td class="txt">{E(cm.text)}</td>'
                 f'<td><span class="tag" style="color:{s_c}">● {s_t}</span></td>'
                 f'<td>{topics}</td>'
                 f'<td class="rch"><b>{cm.reach:,}</b>'
                 f'<span class="rbar"><i style="width:{cm.reach / max_reach * 100:.0f}%"></i></span></td>'
                 f"<td>{link}</td></tr>")

    return f"""<!doctype html><html lang="th"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Crisis Radar — {E(rep.brand.title())}</title>
<style>
:root{{color-scheme:light;--plane:#f6f5f2;--surface:#fff;--inset:#f1f0eb;--ink:#171715;--ink2:#55544d;
  --muted:#8a887f;--border:#e5e3db;--border2:#d4d1c7;--neg:#d33b34;--vc:{color}}}
@media(prefers-color-scheme:dark){{:root{{color-scheme:dark;--plane:#121211;--surface:#1c1c1a;--inset:#252422;
  --ink:#f6f5f1;--ink2:#c4c2b9;--muted:#8d8b82;--border:#302f2b;--border2:#3d3b36}}}}
*{{box-sizing:border-box}}
body{{margin:0;background:var(--plane);color:var(--ink);font-size:15px;line-height:1.65;
  font-family:"Noto Sans Thai","IBM Plex Sans Thai",system-ui,-apple-system,"Segoe UI",sans-serif}}
.wrap{{max-width:1100px;margin:0 auto;padding:24px 20px 60px}}
a{{color:#2563eb;text-decoration:none}} .muted{{color:var(--muted);font-size:13px}}
h1{{font-size:19px;margin:0;letter-spacing:-.02em}} .top{{color:var(--muted);font-size:13px;margin:2px 0 20px}}
.card{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:20px 22px;margin-bottom:18px}}
.card h2{{font-size:16.5px;margin:0 0 4px;font-weight:680;letter-spacing:-.01em}}
.card .sub{{color:var(--muted);font-size:13px;margin-bottom:16px}}
.tnum{{font-variant-numeric:tabular-nums}}

.verdict{{border:1.5px solid var(--vc);border-radius:14px;padding:22px 24px;margin-bottom:18px;
  background:linear-gradient(180deg,color-mix(in srgb,var(--vc) 13%,var(--surface)),var(--surface));
  display:grid;grid-template-columns:minmax(0,1fr) auto;gap:24px;align-items:center}}
@media(max-width:820px){{.verdict{{grid-template-columns:1fr}}}}
.vhead{{display:flex;align-items:center;gap:11px;margin-bottom:8px}}
.vdot{{width:15px;height:15px;border-radius:50%;background:var(--vc);
  box-shadow:0 0 0 5px color-mix(in srgb,var(--vc) 22%,transparent)}}
.vhead b{{font-size:21px;font-weight:730;color:var(--vc);letter-spacing:-.02em}}
.vsum{{font-size:16.5px;font-weight:560;max-width:66ch}}
.vact{{margin-top:12px;font-size:14px;color:var(--ink2);background:color-mix(in srgb,var(--vc) 8%,transparent);
  border-radius:10px;padding:10px 14px;max-width:70ch}}
.vfacts{{display:flex;flex-direction:column;gap:11px;padding-left:24px;border-left:1px solid var(--border);min-width:180px}}
@media(max-width:820px){{.vfacts{{padding:14px 0 0;border-left:0;border-top:1px solid var(--border);
  flex-direction:row;flex-wrap:wrap;gap:22px}}}}
.vfact .l{{font-size:12px;color:var(--muted)}} .vfact .v{{font-size:15.5px;font-weight:680}}

.kpis{{display:grid;grid-template-columns:repeat(4,1fr);gap:14px;margin-bottom:18px}}
@media(max-width:860px){{.kpis{{grid-template-columns:repeat(2,1fr)}}}}
.kpi{{background:var(--surface);border:1px solid var(--border);border-radius:14px;padding:16px 18px}}
.kpi .l{{font-size:12.5px;color:var(--muted)}}
.kpi .v{{font-size:29px;font-weight:700;letter-spacing:-.03em;margin:4px 0 2px;font-variant-numeric:tabular-nums}}
.kpi .v small{{font-size:15px;font-weight:600;color:var(--ink2)}}
.kpi .d{{font-size:12.5px;color:var(--ink2)}}

.alert{{display:flex;gap:13px;align-items:flex-start;border:1px solid var(--border);border-left:4px solid var(--neg);
  border-radius:11px;padding:13px 16px;margin-bottom:10px}}
.alert .ic{{font-size:16px}} .alert .t{{font-size:14.5px;font-weight:660}}
.alert .d{{font-size:13px;color:var(--ink2);margin-top:3px}}
.owner{{display:inline-block;font-size:12px;font-weight:640;padding:3px 11px;border-radius:999px;
  background:var(--inset);border:1px solid var(--border);color:var(--ink2);margin-top:9px}}

.grid{{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1.25fr);gap:18px;align-items:stretch}}
@media(max-width:880px){{.grid{{grid-template-columns:1fr}}}}
.stack{{display:flex;height:34px;border-radius:9px;overflow:hidden;margin-bottom:14px;background:var(--inset)}}
.stack i{{display:block;height:100%}}
.srow{{display:flex;align-items:center;gap:11px;padding:8px 10px;font-size:14px}}
.srow .sw{{width:11px;height:11px;border-radius:3px}} .srow .nm{{flex:1;color:var(--ink2)}}
.srow .pc{{font-weight:680;font-variant-numeric:tabular-nums}}
.srow .ct{{color:var(--muted);font-size:12.5px;width:78px;text-align:right;font-variant-numeric:tabular-nums}}
.note{{margin-top:14px;padding-top:13px;border-top:1px solid var(--border);font-size:12.5px;color:var(--muted)}}

.trow{{display:grid;grid-template-columns:22px minmax(0,1fr) auto;gap:12px;align-items:center;padding:10px}}
.trow .rk{{font-size:12.5px;color:var(--muted);font-weight:680;text-align:center}}
.trow .nm{{font-size:14.5px;font-weight:640}}
.trow .meta{{font-size:12px;color:var(--muted)}}
.tbar{{height:7px;border-radius:4px;background:var(--inset);margin-top:6px;overflow:hidden;max-width:340px}}
.tbar i{{display:block;height:100%;background:var(--neg)}}
.trow .rt{{text-align:right;white-space:nowrap}}
.trow .rt .n{{font-size:17px;font-weight:700;font-variant-numeric:tabular-nums}}
.trow .rt .u{{font-size:11.5px;color:var(--muted);display:block;margin-top:-3px}}
.hot{{font-size:11px;font-weight:680;color:var(--neg);background:color-mix(in srgb,var(--neg) 13%,transparent);
  border-radius:6px;padding:1px 7px;margin-left:7px;white-space:nowrap}}

.legend{{display:flex;gap:16px;flex-wrap:wrap;font-size:12px;color:var(--muted);margin-bottom:12px}}
.legend span{{display:inline-flex;align-items:center;gap:6px}} .legend i{{width:11px;height:11px;border-radius:3px}}
.chart{{position:relative;padding-left:44px}}
.yax{{position:absolute;left:0;top:22px;height:180px;width:38px;font-size:11px;color:var(--muted);
  display:flex;flex-direction:column;justify-content:space-between;text-align:right;font-variant-numeric:tabular-nums}}
/* scroll ครอบ plot+xax และเผื่อ padding-top ให้ป้าย "พุ่ง" ที่ลอยเหนือแท่งสูงสุด (overflow-x ตัดแนวตั้งด้วย) */
.scroll{{overflow-x:auto;padding-top:22px}}
.plot{{position:relative;height:180px;display:flex;align-items:flex-end;gap:5px;min-width:100%;
  border-bottom:1.5px solid var(--border2)}}
.col{{flex:1;min-width:22px;height:100%;display:flex;flex-direction:column;justify-content:flex-end;position:relative}}
.stk{{display:flex;flex-direction:column;justify-content:flex-end;border-radius:5px 5px 0 0;overflow:hidden;min-height:3px}}
.stk .neg{{background:var(--neg)}} .stk .rest{{background:var(--border2)}}
.flag{{position:absolute;left:50%;transform:translateX(-50%);white-space:nowrap;font-size:10.5px;font-weight:700;
  color:#fff;background:var(--neg);border-radius:6px;padding:1px 7px}}
.avg{{position:absolute;left:0;right:0;border-top:1.5px dashed #2563eb}}
.avg b{{position:absolute;left:0;top:-9px;font-size:10.5px;color:#2563eb;background:var(--surface);padding-right:5px}}
.xax{{display:flex;gap:5px;padding-top:7px;min-width:100%}}
.xax div{{flex:1;min-width:22px;text-align:center;font-size:10.5px;color:var(--muted);font-variant-numeric:tabular-nums}}

.tbl{{overflow-x:auto;border:1px solid var(--border);border-radius:9px}}
table{{width:100%;border-collapse:collapse;font-size:13.5px}}
th,td{{text-align:left;padding:11px 13px;border-bottom:1px solid var(--border);vertical-align:top}}
tr:last-child td{{border-bottom:0}}
th{{font-size:11.5px;text-transform:uppercase;letter-spacing:.05em;color:var(--muted);font-weight:680;white-space:nowrap}}
td.when{{white-space:nowrap;color:var(--muted);font-size:12.5px}} td.when b{{display:block;color:var(--ink2)}}
td.who{{white-space:nowrap}} td.txt{{min-width:280px;max-width:460px}}
td.rch{{white-space:nowrap;width:100px}} td.rch b{{font-variant-numeric:tabular-nums}}
.rbar{{display:block;height:5px;border-radius:3px;background:var(--inset);margin-top:4px;overflow:hidden}}
.rbar i{{display:block;height:100%;background:var(--neg)}}
.tag{{font-weight:640;white-space:nowrap}}
.topic{{display:inline-block;font-size:11.5px;color:var(--ink2);background:var(--inset);border:1px solid var(--border);
  border-radius:6px;padding:2px 8px;margin:1px 3px 1px 0;white-space:nowrap}}
.how{{border:1px dashed var(--border2);background:none}}
.how ol{{margin:0;padding-left:22px;color:var(--ink2);font-size:13.5px}} .how li{{margin-bottom:7px}}
.how b{{color:var(--ink)}}
@media print{{body{{background:#fff}} .card{{break-inside:avoid}}}}
</style></head><body><div class="wrap">
<h1>Crisis Radar — {E(rep.brand.title())}</h1>
<div class="top">รายงานเฝ้าระวังดราม่าบน Facebook · ข้อมูลช่วง {window}</div>

<div class="verdict">
  <div>
    <div class="vhead"><span class="vdot"></span><b>{E(head)}</b></div>
    <div class="vsum">{summary}</div>
    <div class="vact">👉 <b>ควรทำอะไรต่อ:</b> {action}</div>
  </div>
  <div class="vfacts">
    <div class="vfact"><div class="l">ช่วงเวลาของข้อมูล</div><div class="v">{window}</div></div>
    <div class="vfact"><div class="l">คอมเมนต์ที่อ่าน</div><div class="v tnum">{rep.total:,} รายการ</div></div>
    <div class="vfact"><div class="l">จากผู้ใช้</div><div class="v tnum">{uniq:,} คน</div></div>
  </div>
</div>

<div class="kpis">{kpi_html}</div>

<div class="card"><h2>สิ่งที่ควรจัดการ</h2>
  <div class="sub">เรียงจากเรื่องที่ควรรีบดูที่สุด</div>{alerts}</div>

<div class="grid">
  <div class="card"><h2>อารมณ์ของคอมเมนต์</h2><div class="sub">จากทั้งหมด {rep.total:,} คอมเมนต์</div>
    <div class="stack">{stack}</div>{sent_rows}
    <div class="note">🤖 มี <b>{rep.escalated_count:,}</b> คอมเมนต์ที่กำกวมหรือเข้าข่ายประชด
      ถูกส่งให้ AI อีกชั้นอ่านซ้ำเพื่อความแม่นยำ</div></div>
  <div class="card"><h2>เรื่องที่คนบ่น</h2>
    <div class="sub">เรียงตามความแรง · พร้อมทีมที่ควรรับเรื่องไปแก้</div>{topic_html}</div>
</div>

<div class="card"><h2>ดราม่าเกิดตอนไหน</h2>
  <div class="sub">ความสูง = จำนวนคอมเมนต์ในชั่วโมงนั้น · ส่วนสีแดงด้านล่างคือคอมเมนต์เชิงลบ</div>
  <div class="legend"><span><i style="background:var(--neg)"></i>คอมเมนต์เชิงลบ</span>
    <span><i style="background:var(--border2)"></i>คอมเมนต์อื่น ๆ (บวก/กลาง)</span>
    <span><i style="border-top:2px dashed #2563eb;height:0;width:16px"></i>ค่าเฉลี่ยคอมเมนต์ลบ</span>
    <span>🚨 = ช่วงที่ระบบตัดสินว่าผิดปกติ</span></div>
  <div class="chart">
    <div class="yax"><div>{max_total:,}</div><div>{max_total // 2:,}</div><div>0</div></div>
    <div class="scroll">
      <div class="plot">{timeline}
        <span class="avg" style="bottom:{avg_neg / max_total * 100:.1f}%"><b>ค่าเฉลี่ยคอมเมนต์ลบ {avg_neg:.0f}</b></span></div>
      <div class="xax">{xaxis}</div>
    </div>
  </div></div>

<div class="card"><h2>คอมเมนต์เชิงลบที่คนเห็นมากสุด</h2>
  <div class="sub">15 อันดับแรก เรียงตามยอดไลก์+ตอบกลับ — เข้าไปตอบอันบนสุดก่อน</div>
  <div class="tbl"><table>
  <thead><tr><th>เวลา</th><th>ผู้คอมเมนต์</th><th>ข้อความ</th><th>อารมณ์</th><th>ประเด็น</th>
    <th>ไลก์+ตอบกลับ</th><th></th></tr></thead>
  <tbody>{rows}</tbody></table></div></div>

<div class="card how"><h2>ระบบตัดสินยังไง</h2><ol>
  <li><b>อ่านทุกคอมเมนต์</b> แล้วจัดว่าเป็นบวก/กลาง/ลบ พร้อมจับว่าพูดถึงเรื่องอะไร —
      คอมเมนต์ที่กำกวมหรือประชดจะถูกส่งให้ AI อ่านซ้ำอีกชั้น</li>
  <li><b>เทียบกับ “ปกติของเพจนี้”</b> ไม่ได้ดูแค่ว่าคอมเมนต์ลบเยอะไหม แต่ดูว่าชั่วโมงนี้ลบพุ่งกว่าชั่วโมงก่อน ๆ กี่เท่า
      และคอมเมนต์นั้นมีคนไลก์/ตอบกลับมากแค่ไหน</li>
  <li><b>เตือนเมื่อผิดปกติจริง</b> พร้อมบอกว่าทีมไหนควรรับเรื่อง</li>
</ol>
<div class="note">อยากค้นหา/กรอง/เจาะดูคอมเมนต์ทีละอัน — เปิดหน้าเว็บแบบโต้ตอบได้ที่ backend/server.py</div></div>
</div></body></html>"""
