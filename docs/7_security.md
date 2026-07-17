# 7. Security Information

## หลักคิด
Crisis Radar สนใจ **"สัญญาณรวม"** (มีดราม่าไหม เรื่องอะไร รุนแรงแค่ไหน) ไม่ใช่ตัวบุคคล
→ ออกแบบให้ไม่ต้องเก็บ/เปิดเผยตัวตนผู้คอมเมนต์

## 1. PII (ข้อมูลส่วนบุคคล)
| มาตรการ | ทำอะไร | โค้ด |
|---|---|---|
| Mask ชื่อ | ชื่อผู้คอมเมนต์ถูก hash เป็น `user_xxxxxx` ตั้งแต่ตอนโหลด (ก่อนเก็บ/ก่อนเข้า AI) | `security.mask_author` |
| Scrub ในข้อความ | แทนเบอร์โทร/อีเมลที่คนอาจแปะในคอมเมนต์ด้วย `[phone]` / `[email]` | `security.scrub_pii_in_text` |
| ตามตัวกลับไม่ได้ | ใช้ salt + sha256 — ยังนับ unique user ได้ แต่ไม่รู้ว่าเป็นใคร | ตรวจใน Test T5 |

> พิสูจน์แล้วใน Test T5: output ทุกไฟล์ (`classified.json`, `dashboard.html`) ไม่มีชื่อจริงหลุด

## 2. ความลับ / Credentials
- **ไม่ commit token/คีย์ลง git** — ทั้งหมดอ่านจาก env var (`ANTHROPIC_API_KEY`, FB page token)
- salt ของ hash ย้ายไป env var ตอน production
- `.gitignore` กัน `.env`, ไฟล์ generated, cache

## 3. การดึงข้อมูล (Scraping / API) — ดูละเอียดใน [SCRAPING.md](SCRAPING.md)
- **เดโม่ pipeline:** ใช้ synthetic fixture — ไม่แตะข้อมูลจริง ไม่มีความเสี่ยงกฎหมาย
- **ดึงจริง (prototype):** Apify (แนะนำ) หรือ Playwright + session ของผู้ใช้เอง — mask PII ทันทีที่เข้า pipeline
- **Production (ทางที่ถูกต้อง):** ใช้ **Meta Graph API + Page access token** ของเพจที่บริษัทเป็นแอดมิน
  → ถูก ToS, เสถียร, ไม่ต้อง scrape เถื่อน
- ระหว่างช่วง prototype ถ้าจำเป็นต้อง scrape: rate-limit อย่างสุภาพ, เคารพ robots, เก็บเฉพาะที่จำเป็น,
  ใช้ **ภายในองค์กรเท่านั้น** ไม่เผยแพร่ข้อมูลบุคคลออกนอก

### 3.1 PDPA (พ.ร.บ.คุ้มครองข้อมูลส่วนบุคคล) — สำคัญเมื่อดึง "กลุ่ม"
| แหล่ง | ความเสี่ยง PDPA | การรับมือ |
|---|---|---|
| เพจ public | ต่ำ (คอนเทนต์สาธารณะ) | mask PII + ใช้ภายใน |
| กลุ่ม (private) | **สูง** — สมาชิกคาดหวังความเป็นส่วนตัว | เริ่มทีหลัง, ต้องมีฐานทางกฎหมาย (legitimate interest), เก็บเชิงรวม (aggregate) ไม่ระบุตัวบุคคล |
> เดโม่ Phase 1 จึงเริ่มจาก **เพจ public** ก่อน แล้วค่อยพิจารณากลุ่มเมื่อเคลียร์ประเด็นกฎหมาย

## 4. ขอบเขตการเข้าถึงข้อมูล (Data Governance)
- เก็บเท่าที่ใช้: ข้อความคอมเมนต์ (scrub แล้ว) + เวลา + reach + topic/sentiment
- ไม่เก็บ: โปรไฟล์ผู้ใช้, รูป, เพื่อน, ข้อมูลการเงิน
- Dashboard เข้าถึงภายในทีมเท่านั้น (ตอน deploy จริงใส่ auth)

## 5. ความเสี่ยงที่รู้ตัว + การรับมือ
| ความเสี่ยง | รับมือ |
|---|---|
| AI จัด sentiment ผิด (ประชด/สแลง) | hybrid + human-in-the-loop ก่อนออกแถลง ไม่ให้ AI ตัดสินคนเดียว |
| False alarm | Test T4 คุม threshold + ปรับต่อเนื่องช่วง pilot |
| FB เปลี่ยน/บล็อกการดึง | connector แยกชั้น — สลับไป Graph API/Apify ได้โดยไม่แตะ pipeline |
| Prompt injection ในคอมเมนต์ | ข้อความผู้ใช้เป็น "ข้อมูลที่ต้องจัดหมวด" ไม่ใช่คำสั่ง — คุมด้วย system prompt + ไม่ให้ LLM ทำ action |
