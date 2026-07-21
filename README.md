# 📡 Crisis Radar

**AI social-listening + crisis early-warning สำหรับชุมชนเกมที่เราดูแล**
เริ่มที่ Talesrunner (Facebook) → ออกแบบให้ต่อเกมอื่น/ช่องทางอื่นได้

> ดึงคอมเมนต์ → จัด sentiment (บวก/กลาง/ลบ) + topic → **ตรวจจับการพุ่งผิดปกติ (spike)** →
> แจ้งเตือนทีม Community ให้เข้าไปจัดการก่อนดราม่าลุกลาม รักษาภาพลักษณ์แบรนด์

## 🖥️ ใช้ผ่านเว็บ (สำหรับทีม — กดปุ่มเดียว ไม่ต้องพิมพ์คำสั่ง)
```bash
python3 backend/server.py         # แล้วเปิด http://127.0.0.1:8000
```
- macOS: **ดับเบิลคลิก `start_web.command`** ได้เลย (เปิดเบราว์เซอร์ให้อัตโนมัติ)
- แชร์ให้ทีมในออฟฟิศ: `python3 backend/server.py --host 0.0.0.0` แล้วให้ทีมเข้า `http://<ip-เครื่อง>:8000`
- ไม่ต้อง `pip install` อะไรเลย — backend เป็น Python stdlib ล้วน
- หน้าเว็บมีปุ่มเดียว **"เริ่มตรวจ"**: เลือก *ข้อมูลตัวอย่าง* (ดูทันที) หรือ *Facebook จริง* (owner ตั้ง `APIFY_TOKEN` ที่ server ก่อน)
- ผลลัพธ์เล่าเรื่องตามลำดับ: **สถานะ + สิ่งที่ควรทำต่อ → ตัวเลขสำคัญ → สิ่งที่ควรจัดการ (พร้อมทีมที่รับเรื่อง)
  → เรื่องที่คนบ่น → ดราม่าเกิดตอนไหน → คอมเมนต์จริง** — ทุกการ์ดกดเจาะดูคอมเมนต์ต้นเรื่องได้ทันที

## รันแบบ CLI (สำหรับ dev)
```bash
python3 run_demo.py        # → output/crisis_report.md, classified.json, dashboard.html
python3 tests/run_tests.py # → 13 test, ผลจริง
python3 backend/selftest.py # → ทดสอบ web backend end-to-end (10 test)
```

## ดึง Facebook จริง (ผ่าน Apify — ไม่ต้องลง package)
1. ใส่ `APIFY_TOKEN` ในไฟล์ `.env` (ดู `.env.example`) · ใส่ URL โพสต์ใน `data/targets.json` → `post_urls`
2. **ผ่านเว็บ:** เปิด server → กดปุ่ม **📘 ดึง Facebook จริง** (ใช้ Apify REST API สดผ่าน urllib stdlib)
3. **หรือ CLI:** `python3 scrape_facebook.py --run`
```bash
# ทางลัดไม่ต้องต่อ token: import ไฟล์ JSON ที่ Download จาก Apify Console
python3 scrape_facebook.py --import ไฟล์.json --run
```
> ⚠️ เพจ public ก่อน (ปลอดภัย). กลุ่ม private ต้องเป็นสมาชิก + cookie + เช็ก PDPA (ดู [docs/SCRAPING.md](docs/SCRAPING.md))

## สถาปัตยกรรม (สลับ scraper → API ได้โดยไม่แก้ pipeline)
```
sources/  → classify/           → crisis/       → dashboard.py
(connector) (Thai lexicon+LLM)   (spike detect)  (HTML)
```

| ชั้น | เดโม่วันนี้ | production |
|---|---|---|
| Source | `SampleFacebookSource` (fixture) | Meta Graph API / Apify (ต้องได้ page admin) |
| AI | Thai lexicon + offline-heuristic LLM | Wisesight/WangchanBERTa + Claude Haiku |
| Dashboard | static HTML | React (reuse stack Warz) + API |
| Orchestration | รันมือ | n8n schedule → alert เข้า Discord (แยก channel ตามทีม) |

## Deploy ขึ้นเว็บ (Render — สำหรับ demo ให้ทีมกดเอง)

repo นี้มี [render.yaml](render.yaml) ให้แล้ว ทำตามนี้:

1. push ขึ้น GitHub
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint** → เลือก repo นี้
3. กรอก 2 ค่าตอน deploy:
   - `APIFY_TOKEN` — token จาก Apify (ถ้าจะใช้โหมด Facebook จริง)
   - `RUN_PASSCODE` — รหัสอะไรก็ได้ที่ตั้งเอง **กันคนที่ได้ลิงก์กดดึง Facebook จนเครดิต Apify หมด**
4. รอ build เสร็จ → ได้ URL `https://crisis-radar-xxxx.onrender.com`

โหมด **ตัวอย่าง** เปิดให้ทุกคนกดได้ทันที · โหมด **Facebook จริง** จะถามรหัสก่อน

> Render free tier จะ sleep หลังไม่มีคนใช้ 15 นาที → เปิดครั้งถัดไปรอโหลด ~1 นาที
> และ job ที่ค้างอยู่ตอน sleep จะหาย (state เก็บใน memory) — พอสำหรับ demo

## เอกสารส่ง (ดู `docs/`)
1. [Project Summary](docs/1_project_summary.md)
2. [Before–After Workflow](docs/2_before_after_workflow.md)
3. [Workflow Diagram](docs/3_workflow_diagram.md)
4. [Test Cases + ผล](docs/4_test_cases.md)
5. [Git Repository](docs/5_git_repository.md)
6. [Owner](docs/6_owner.md)
7. [Security Information](docs/7_security.md)

**ประกอบการนำเสนอ:** [presentation.html](docs/presentation.html) (เดคหลัก 7 หัวข้อ) ·
[presentation_appendix.html](docs/presentation_appendix.html) — baseline ความมั่นใจของ AI, ตัวอย่าง alert บน Discord (n8n), เส้นทางส่งต่อทีม

> ⚠️ ข้อมูลในเดโม่เป็น **synthetic fixture** (ชื่อสมมติ) เพื่อพิสูจน์ pipeline ก่อนได้ API จริง
