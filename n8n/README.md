# แจ้งเตือนเข้า Discord ผ่าน n8n

> ไฟล์นี้ = ทางลัด **Incoming Webhook** ตั้ง 5 นาทีเสร็จ
> อยากใช้ **Discord Bot** (แยกหลาย channel ตามทีมด้วย credential เดียว · ต่อยอดปุ่ม/thread/slash command ได้)
> → [`docs/integrate_n8n_discord.md`](../docs/integrate_n8n_discord.md)

Crisis Radar **ยิง webhook ออก** เมื่อมีคอมเมนต์ที่ต้องมีคนรับเรื่อง — n8n เป็นตัวรับแล้วส่งต่อเข้า Discord

มี 2 workflow แยกกัน เพราะทิศทางการยิงคนละทาง:

```
A) alert รายคอมเมนต์ — Crisis Radar เป็นคนเริ่ม (เกิดเมื่อไหร่ก็ได้)
   Crisis Radar ──POST──▶ n8n Webhook ──▶ severity? ──high──▶ Discord #crisis-alert
   (auto / คนกดปุ่ม)                                 └medium─▶ Discord #watch

B) สรุปประจำวัน — n8n เป็นคนเริ่ม (วันละครั้งตามเวลาที่ตั้ง)
   n8n Schedule 09:00 ──POST /api/digest──▶ Crisis Radar (ดึง Apify + สรุป)
                        ◀──payload สรุป──┘
                        └──▶ Discord #crisis-daily
```

| | A. alert รายคอมเมนต์ | B. สรุปประจำวัน |
|---|---|---|
| ไฟล์ workflow | `crisis_radar_discord_alert.json` | `crisis_radar_daily_digest.json` |
| ใครเริ่ม | Crisis Radar ยิงเข้า n8n | n8n เรียก Crisis Radar |
| ตอบคำถามว่า | “มีคอมเมนต์นี้ที่ต้องรีบดู” | “เมื่อวานเพจเป็นยังไง วันนี้ต้องสนใจอะไร” |
| ส่งกี่ข้อความ | 1 คอมเมนต์ = 1 ข้อความ | ทั้งรอบ = 1 ข้อความ |
| ส่งวันที่เงียบ ๆ ไหม | ไม่ส่ง | **ส่งเสมอ** — เป็นสัญญาณชีพว่าระบบยังทำงาน |

ใช้คู่กันได้ (แนะนำ) — B เป็นตัวทริกเกอร์รอบดึงของวัน แล้ว A จะเด้งจากรอบเดียวกันนั้นเอง

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

## ติดตั้ง workflow B — สรุปประจำวัน (โหมดดึงวันละรอบ)

ใช้เมื่อ **เครดิต Apify จำกัด** จนดึงได้แค่วันละรอบ: ให้ n8n เป็นคนกำหนดเวลาดึง แล้วสรุปทั้งวัน
ในข้อความเดียว (แทนที่จะรอให้มีคนเปิดหน้าเว็บถึงจะเริ่มดึง — ซึ่งบน Render free tier ที่ container
หลับหลังไม่มีคนใช้ 15 นาที แปลว่าอาจไม่มีรอบดึงเลยทั้งวัน)

1. **Crisis Radar (.env / Environment ของ Render):**

   ```bash
   MONITOR_INTERVAL_MIN=1380   # 23 ชม. — เพดานจริงของค่าใช้จ่าย: ยิงซ้ำกี่ครั้งก็ scrape ได้รอบเดียว
   MONITOR_MAX_POSTS=5         # ≈ $0.066/รอบ → 30 วัน ≈ $2 (เครดิตฟรี Apify $5/เดือน)
   ALERT_MAX_PER_RUN=3         # วันละรอบ = คอมเมนต์สะสม 24 ชม. ต่อรอบ ไม่ลดจะเด้งรัวตอนเช้า
   RUN_PASSCODE=<ตั้งรหัส>      # /api/digest ยิงข้อความออกนอกระบบ จึงล็อกด้วยรหัสเดียวกับปุ่มอื่น
   PUBLIC_URL=https://<url ของ dashboard>
   ```

2. **n8n:** Import `crisis_radar_daily_digest.json` → แก้ 4 จุดที่เขียนว่า `REPLACE`
   (URL ของ Crisis Radar ×2 · `X-Run-Passcode` ×2 · Discord webhook URL ×2)
3. Workflow **Settings → Timezone → Asia/Bangkok** (ไม่ตั้ง = 09:00 จะเป็นเวลา UTC = 16:00 บ้านเรา)
4. **Activate** → กด *Execute Workflow* 1 ครั้งเพื่อลองจริง

**ทำไมยิงซ้ำแล้วไม่เปลืองเครดิต:** `/api/digest` ส่ง `refresh:true` = “ดึงใหม่ **ถ้าถึงรอบแล้ว**”
คนตัดสินคือ Crisis Radar (จาก `MONITOR_INTERVAL_MIN`) ไม่ใช่ n8n → n8n retry, มีคนกด Execute เอง,
หรือมีคนเปิดหน้าเว็บพร้อมกัน 10 คน ก็ยังเป็น **1 scrape ต่อ interval** เท่าเดิม
และตัวสรุปเองกันซ้ำรายวันอีกชั้น (จำที่ `data/alerts_sent.json` คีย์ `digest:YYYY-MM-DD`)

**response ที่ต้องรู้จัก:**

| ได้อะไรกลับมา | แปลว่า | workflow ทำอะไรต่อ |
|---|---|---|
| `discord` + `report` | สรุปพร้อมส่ง | ยิงเข้า Discord |
| `skipped: true` | วันนี้ส่งไปแล้ว | ไม่ทำอะไร (ไม่ใช่ error) |
| HTTP 202 `pending: true` | ยังดึงไม่เสร็จ | รอ 5 นาทีแล้วขอใหม่ (มีใน workflow แล้ว) |
| HTTP 400 | ยังไม่มีผลตรวจให้สรุป | ดู log ฝั่ง Crisis Radar |

`sample_digest_payload.json` = ของจริงที่ endpoint นี้คืนกลับมา (สร้างจาก pipeline ไม่ได้เขียนมือ)
ฟิลด์ที่ใช้บ่อย: `$json.discord` (ข้อความสำเร็จรูป) · `$json.severity` (high/medium/low ตามสถานะเพจ)
· `$json.report.status` · `$json.top_negative[]` (อยากทำการ์ดแยกใบต่อคอมเมนต์)

> cron อยู่ที่อื่น (cron-job.org / GitHub Actions) ที่ไม่มีที่ให้ต่อ Discord? ส่ง `{"push": true}`
> ไปด้วย — Crisis Radar จะยิงเข้า `N8N_WEBHOOK_URL` เองเหมือน alert ปกติ (workflow A จะรับให้
> โดยลงห้อง `#watch` เพราะ severity ไม่ใช่ high — อยากแยกห้องให้เช็ก `$json.body.event` ก่อน)

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
