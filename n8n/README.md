# แจ้งเตือนเข้า Discord ผ่าน n8n

> ไฟล์นี้ = ทางลัด **Incoming Webhook** ตั้ง 5 นาทีเสร็จ
> อยากใช้ **Discord Bot** (แยกหลาย channel ตามทีมด้วย credential เดียว · ต่อยอดปุ่ม/thread/slash command ได้)
> → [`docs/integrate_n8n_discord.md`](../docs/integrate_n8n_discord.md)

Crisis Radar **ยิง webhook ออก** เมื่อมีคอมเมนต์ที่ต้องมีคนรับเรื่อง — n8n เป็นตัวรับแล้วส่งต่อเข้า Discord

```
Crisis Radar ──POST──▶  n8n Webhook  ──▶ severity?  ──high──▶ Discord #crisis-alert
(auto / คนกดปุ่ม)                                    └─medium─▶ Discord #watch
```

**ทำไมไม่ยิง Discord ตรง ๆ:** channel ที่ใช้ ทีมที่ต้อง ping และปลายทางอื่น (Jira/Sheet/LINE)
เปลี่ยนบ่อยกว่าตัวโค้ดมาก — วางไว้ที่ n8n ทีมแก้เองได้โดยไม่ต้องแตะ repo แล้ว deploy ใหม่
(อยากยิงตรงจริง ๆ ก็ได้ — ตั้ง `DISCORD_WEBHOOK_URL` แทน `N8N_WEBHOOK_URL` ระบบจะส่งเฉพาะ
ชั้นข้อความ `discord` ที่เข้ารูปแบบ Discord webhook อยู่แล้ว)

## alert เกิดขึ้นเมื่อไหร่

| ทาง | เงื่อนไข | severity |
|---|---|---|
| **อัตโนมัติ** | คอมเมนต์ **เชิงลบ** + ไลก์+ตอบกลับ ≥ `ALERT_MIN_REACH` (ค่าเริ่มต้น 150 · ช่วงสถานะ CRISIS ลดครึ่ง) | `high` / `medium` |
| **คนกดปุ่ม** | คนที่นั่ง monitor กด **“🔔 แจ้ง Discord”** ที่คอมเมนต์นั้น — สำหรับเคสที่ AI อ่านเป็น **“กลาง/บวก”** แต่คนอ่านออกว่าเป็นเรื่อง | `high` เสมอ (ผ่านสายตาคนแล้ว) |

กันข้อความท่วม: คอมเมนต์เดิมส่งซ้ำไม่ได้ (จำที่ `data/alerts_sent.json`) · auto ส่งได้มากสุด
`ALERT_MAX_PER_RUN` ต่อรอบตรวจ (เรียงจาก reach มากสุด) · คอมเมนต์ที่กด “อ่านแล้ว” ไม่ถูกแจ้งอัตโนมัติ

## ติดตั้ง (5 นาที)

1. **Discord:** Server Settings → Integrations → Webhooks → สร้าง webhook ของ channel ที่ต้องการ → คัดลอก URL
2. **n8n:** Workflows → Import from File → เลือก `crisis_radar_discord_alert.json`
3. แก้ URL ใน node **Discord #crisis-alert** และ **Discord #watch** ให้เป็น webhook ที่ได้จากข้อ 1
4. ที่ node **Crisis Radar webhook** → Credential for Header Auth → *Create new*
   - Name: `X-Crisis-Radar-Token`
   - Value: ตั้งอะไรก็ได้ (จะเอาไปใส่ `N8N_WEBHOOK_SECRET` ในข้อถัดไป)
5. **Activate** workflow แล้วคัดลอก *Production URL* ของ Webhook node
6. **Crisis Radar:** ใส่ค่าลง `.env` (หรือ Environment ของ Render)

```bash
N8N_WEBHOOK_URL=https://<your-n8n>/webhook/crisis-radar-alert
N8N_WEBHOOK_SECRET=<ค่าเดียวกับข้อ 4>
PUBLIC_URL=https://<url ของ dashboard>          # แนบลิงก์กลับไปในข้อความ
# ALERT_MIN_REACH=150 · ALERT_MAX_PER_RUN=5 · ALERT_AUTO=off  (ดู .env.example)
```

7. รีสตาร์ท server → เปิดหน้าเว็บ ปุ่ม **🔔 แจ้ง Discord** จะขึ้นในตาราง *อ่านคอมเมนต์จริง*

**ทดสอบก่อนต่อของจริง:** ใน n8n กด *Listen for test event* แล้วกดปุ่มแจ้งจากหน้าเว็บ 1 ครั้ง
หรือวาง `sample_payload.json` เป็น pinned data ของ Webhook node เพื่อลองไล่ workflow ทั้งเส้น

## หน้าตา payload

`sample_payload.json` คือของจริงที่ระบบยิงออก (สร้างจาก pipeline ไม่ได้เขียนมือ) — มี 2 ชั้น:

| ชั้น | ใช้ทำอะไร |
|---|---|
| `discord` | ข้อความสำเร็จรูป (content + embeds) — HTTP Request node ยิงต่อได้เลยด้วย `{{ JSON.stringify($json.body.discord) }}` |
| `trigger` · `severity` · `routing` · `comment` · `report` | ข้อมูลดิบไว้ตัดสินใจใน n8n เอง (เลือก channel, ping role, เปิดการ์ด Jira, เก็บ log) |

ฟิลด์ที่ใช้ route บ่อย:

```
{{ $json.body.severity }}          high | medium
{{ $json.body.trigger }}           auto (ระบบเจอเอง) | manual (คนกดแจ้ง)
{{ $json.body.routing.owner }}     "Dev / QA" · "Marketing / Monetization" · …
{{ $json.body.routing.topic }}     bug/technical · billing/price · rewards/redeem · …
{{ $json.body.comment.url }}       ลิงก์ตรงไปคอมเมนต์นั้นบน Facebook
```

อยากแยก channel ตามทีม: เปลี่ยน IF เป็น **Switch** node แล้วเทียบ `routing.topic`
· อยาก ping role: ตั้ง `DISCORD_ROLE_MAP` ฝั่ง Crisis Radar (`{"bug/technical":"<role id>"}`)
ระบบจะใส่ `<@&id>` ให้ในฟิลด์ `content` เอง

## ข้อควรรู้

- Crisis Radar บันทึกว่า “ส่งแล้ว” **เฉพาะตอนได้ response 2xx** — n8n ล่ม/ตอบ error จะยังส่งซ้ำได้รอบหน้า
  (workflow ตัวอย่างจึงจบด้วย *Respond to Webhook*; ถ้าเปลี่ยนเป็น respond ทันทีก็ยังใช้ได้ แต่จะไม่รู้ว่า
  ขา Discord สำเร็จจริงไหม)
- ข้อความที่ส่งออกมี **ข้อความคอมเมนต์ + ชื่อผู้คอมเมนต์** ติดไปด้วย — ใช้กับ channel ภายในทีมเท่านั้น
  (ดู `docs/7_security.md` §3.2)
- ไทม์เอาต์ฝั่ง Crisis Radar 8 วินาที — workflow ที่ยาวกว่านั้นให้ตอบ webhook ก่อนแล้วค่อยทำงานต่อ
- **โหมดข้อมูลตัวอย่าง (demo) ก็ยิง alert จริง** เหมือนกัน (คอมเมนต์ละครั้งเดียวเพราะกันแจ้งซ้ำ) —
  ตอนซ้อมนำเสนอให้ชี้ `N8N_WEBHOOK_URL` ไป channel ทดสอบ หรือตั้ง `ALERT_AUTO=off` ไว้ก่อน
