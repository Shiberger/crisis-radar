# 📡 Crisis Radar

**AI social-listening + crisis early-warning สำหรับชุมชนเกมที่เราดูแล**
เริ่มที่ Talesrunner (Facebook) → ออกแบบให้ต่อเกมอื่น/ช่องทางอื่นได้

> ดึงคอมเมนต์ → จัด sentiment (บวก/กลาง/ลบ) + topic → **ตรวจจับการพุ่งผิดปกติ (spike)** →
> แจ้งเตือนทีม Community ให้เข้าไปจัดการก่อนดราม่าลุกลาม รักษาภาพลักษณ์แบรนด์

## 🖥️ ใช้ผ่านเว็บ (สำหรับทีม — เปิดมาเห็นเลย ไม่ต้องกดอะไร)
```bash
python3 backend/server.py         # แล้วเปิด http://127.0.0.1:8000
```
- macOS: **ดับเบิลคลิก `start_web.command`** ได้เลย (เปิดเบราว์เซอร์ให้อัตโนมัติ)
- แชร์ให้ทีมในออฟฟิศ: `python3 backend/server.py --host 0.0.0.0` แล้วให้ทีมเข้า `http://<ip-เครื่อง>:8000`
- ไม่ต้อง `pip install` อะไรเลย — backend เป็น Python stdlib ล้วน
- **หน้าเว็บเป็นจอสถานะ ไม่ใช่ฟอร์ม**: server เฝ้าเพจที่ตั้งไว้ให้เอง เปิดมาเมื่อไหร่ก็เห็นทันทีว่า
  ตอนนี้เพจมีดราม่าไหม (ดู [โหมดเฝ้าเพจอัตโนมัติ](#-โหมดเฝ้าเพจอัตโนมัติ-monitor) ด้านล่าง)
- ปุ่ม **"ตรวจเอง"** ไว้ตรวจนอกรอบ — เจาะโพสต์ที่สงสัย หรือดู *ข้อมูลตัวอย่าง*
- ผลลัพธ์เล่าเรื่องตามลำดับ: **สถานะ + สิ่งที่ควรทำต่อ → ตัวเลขสำคัญ → สิ่งที่ควรจัดการ (พร้อมทีมที่รับเรื่อง)
  → เรื่องที่คนบ่น → ดราม่าเกิดตอนไหน → คอมเมนต์จริง** — ทุกการ์ดกดเจาะดูคอมเมนต์ต้นเรื่องได้ทันที

## 👁 โหมดเฝ้าเพจอัตโนมัติ (monitor)

เปิดใช้อยู่แล้วโดยไม่ต้องตั้งอะไร — เป้าหมายคือ *ไม่ต้องมีใครจำว่าต้องเข้ามากดตรวจ*

| | |
|---|---|
| เฝ้าเพจไหน | `targets[].url` ใน [data/targets.json](data/targets.json) (ตอนนี้ = เพจ TalesRunner) |
| ตรวจใหม่เมื่อไหร่ | ผลล่าสุดเก่าเกิน `MONITOR_INTERVAL_MIN` (ค่าเริ่มต้น 60 นาที) แล้วมีคนเปิดหน้าเว็บ |
| เก็บผลไว้ที่ไหน | `data/monitor_latest.json` + ประวัติย่อ `data/monitor_history.json` — restart server แล้วยังเห็นผลล่าสุดทันที |
| แหล่งข้อมูล | Facebook จริงถ้ามี `APIFY_TOKEN` · ไม่มี → ข้อมูลตัวอย่าง (เดโม่ได้ฟรี) |

**ค่าใช้จ่าย Apify ควบคุมได้:** ตรวจใหม่ได้มากสุด **1 รอบต่อ interval** ไม่ว่าจะมีคนเปิดเว็บพร้อมกันกี่คน
· ไม่มีคนดู = ไม่ยิงเลย · ดึงพลาดจะพัก 5 นาทีก่อนลองใหม่ (ไม่รีทรายรัว)
· ปุ่ม **"ตรวจใหม่ตอนนี้"** (ข้ามรอบ) ถูกล็อกด้วย `RUN_PASSCODE` เหมือนโหมด Facebook จริง

ปรับได้ผ่าน env — ดูรายการเต็มใน [.env.example](.env.example):
```bash
MONITOR=off                # ปิดโหมดเฝ้า → กลับไปเป็นแบบกดปุ่มเองอย่างเดียว
MONITOR_SOURCE=sample      # บังคับใช้ข้อมูลตัวอย่าง (เดโม่ให้ทีมดูโดยไม่แตะเครดิต)
MONITOR_INTERVAL_MIN=30    # ตรวจถี่ขึ้น (โหมด Facebook จริงต่ำสุด 15 นาที)
MONITOR_ALWAYS=1           # ตรวจตามรอบแม้ไม่มีคนเปิดเว็บ — เฉพาะ server ที่ไม่หลับ
```

> เหตุผลที่ default เป็น "ตรวจตอนมีคนเปิดเว็บ" ไม่ใช่ตั้ง cron: Render free tier หลับหลังไม่มีคนใช้
> 15 นาที — thread เบื้องหลังตายไปด้วยอยู่ดี แบบนี้ตรงกับพฤติกรรมจริงและไม่เผาเครดิตตอนไม่มีใครดู

## ✍️ แก้เมื่อ AI อ่านผิด (human override)

AI อ่านภาษาคนพลาดได้เสมอ — โดยเฉพาะมุกตลก ประชด และบ่นเล่น ๆ เช่นคอมเมนต์จริงอันนี้:

> *"รำคาญหัวเด้งสุดละไม่มีไรแก้ทางเลยนอกจากไปเล่นร้านเกมแล้วมันนั่งอยู่ข้างๆ 👋"*

lexicon เจอคำว่า **รำคาญ** + **เด้ง** → ตัดสินเป็น *ลบ* ทั้งที่คนอ่านออกว่าหยอกเล่น
ถ้าปล่อยไว้ ตัวเลขคอมเมนต์ลบจะเฟ้อและ crisis จะเตือนผิด

**วิธีแก้:** ในตาราง *อ่านคอมเมนต์จริง* → กดที่ **ป้ายอารมณ์** ของแถวนั้น → เลือกอารมณ์/ประเด็นที่ถูก → บันทึก

| | |
|---|---|
| ผลทันที | server คิดรายงานใหม่จากคอมเมนต์ชุดเดิม — **ไม่ scrape ซ้ำ ไม่เสียเครดิต** · สถานะ/KPI/timeline/alert ขยับตามจริง |
| จำได้ | เก็บที่ `data/overrides.json` (key = comment_id) → **รอบ scrape ถัดไปก็ยังถูก** ไม่ต้องแก้ซ้ำ |
| ตรวจสอบย้อนหลังได้ | เก็บค่าที่ AI ทายไว้เดิมคู่กันเสมอ · แถวที่แก้มีป้าย **"แก้เอง"** และกด *คืนค่าที่ AI ทาย* ได้ |
| เอาไปพัฒนา AI ต่อ | ไฟล์ override = ชุดข้อมูล "AI ทายอะไร vs คนตัดสินว่าอะไร" → เอาไปปรับ lexicon/prompt ได้ตรงจุด |

> ⚠️ ถ้าตั้ง `RUN_PASSCODE` ไว้ การแก้ label ต้องกรอกรหัสก่อน (ลิงก์สาธารณะไม่ควรแก้ข้อมูลของทีมได้)
> · ตอน deploy ควร mount disk ถาวรให้ `data/overrides.json` ไม่งั้นที่แก้ไว้จะหายตอน restart

## ✓ คลัง "อ่านแล้ว" (archive)

รอบ scrape ถัดไปจะได้คอมเมนต์เดิมกลับมาเกือบทั้งหมด — ถ้าไม่มีที่จำว่า *"อันนี้ทีมจัดการแล้ว"*
ของใหม่ที่ต้องรีบดูจะจมอยู่ในกองเดิม

**วิธีใช้:** ในตารางกด **“✓ อ่านแล้ว”** ที่แถวนั้น (หรือ **“อ่านแล้วทั้งหมด (N)”** เพื่อเก็บทีเดียวทั้งที่กรองอยู่)
· สลับดูได้ที่แท็บ **ยังไม่ได้อ่าน / คลัง (อ่านแล้ว)** · เอากลับได้ทุกเมื่อ · toast มีปุ่ม **เลิกทำ**

### ประหยัดอะไรได้จริง (พูดตรง ๆ)

| | |
|---|---|
| ✅ **token ของ AI** | คอมเมนต์ในคลังไม่ถูกส่งเข้า classifier อีก ใช้ label เดิมที่เก็บไว้ · log จะขึ้น `ข้าม N คอมเมนต์ที่ทีมอ่านแล้ว` · วันที่สลับชั้น LLM เป็น Claude Haiku จริงจะประหยัดตามจำนวนนั้นตรง ๆ |
| ✅ **ภาระคน + เวลา/CPU ต่อรอบ** | หน้า Monitor เหลือแต่ของใหม่ที่ยังไม่ได้จัดการ |
| ❌ **ไม่ได้ลดค่า Apify** | Apify คิดเงินตอน "ดึง" คอมเมนต์ ซึ่งเกิดก่อนที่เราจะรู้ว่าอันไหนอ่านแล้ว และ actor สั่งข้ามรายตัวไม่ได้ — อยากลดค่า Apify ต้องลด `MONITOR_MAX_POSTS` / `MONITOR_MAX_COMMENTS` หรือยืด `MONITOR_INTERVAL_MIN` |

> ⚠️ **คอมเมนต์ในคลังไม่ถูกนับในสถานะ/spike** (ถือว่าจัดการแล้ว) — แปลว่ากด "อ่านแล้ว" คอมเมนต์ลบเยอะ ๆ
> สถานะจะดูดีขึ้นได้ · หน้าเว็บจึงแสดงจำนวนในคลังคู่กับสถานะเสมอ และ **สถานะหมายถึง "ของที่ยังไม่ได้จัดการ"**
> · เก็บที่ `data/archive.json` (ตอน deploy ควร mount disk ถาวร ไม่งั้นหายตอน restart)

## รันแบบ CLI (สำหรับ dev)
```bash
python3 run_demo.py        # → output/crisis_report.md, classified.json, dashboard.html
python3 tests/run_tests.py # → 23 test, ผลจริง
python3 backend/selftest.py # → ทดสอบ web + monitor + override + archive end-to-end (31 test)
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
| AI | Thai lexicon + offline-heuristic LLM + คนแก้ทับได้ | Wisesight/WangchanBERTa + Claude Haiku (feed override กลับไป fine-tune) |
| Dashboard | static HTML | React (reuse stack Warz) + API |
| Orchestration | monitor ในตัว (เฝ้าตามรอบ เก็บ snapshot ลงไฟล์) | n8n schedule → alert เข้า Discord (แยก channel ตามทีม) |

## Deploy ขึ้นเว็บ (Render — สำหรับ demo ให้ทีมกดเอง)

repo นี้มี [render.yaml](render.yaml) ให้แล้ว ทำตามนี้:

1. push ขึ้น GitHub
2. [Render Dashboard](https://dashboard.render.com) → **New** → **Blueprint** → เลือก repo นี้
3. กรอก 2 ค่าตอน deploy:
   - `APIFY_TOKEN` — token จาก Apify (ถ้าจะใช้โหมด Facebook จริง)
   - `RUN_PASSCODE` — รหัสอะไรก็ได้ที่ตั้งเอง **กันคนที่ได้ลิงก์กดดึง Facebook จนเครดิต Apify หมด**
4. รอ build เสร็จ → ได้ URL `https://crisis-radar-xxxx.onrender.com`

เปิดลิงก์มาจะเห็นสถานะล่าสุดจาก **โหมดเฝ้าอัตโนมัติ** ทันที · โหมด **ตัวอย่าง** กดได้ทุกคน ·
**ตรวจใหม่ตอนนี้** / **Facebook จริง** จะถามรหัสก่อน

> Render free tier จะ sleep หลังไม่มีคนใช้ 15 นาที → เปิดครั้งถัดไปรอโหลด ~1 นาที แล้ว monitor
> จะตรวจรอบใหม่ให้เอง · job ที่ค้างอยู่ตอน sleep จะหาย และ snapshot บนดิสก์ถูกล้างตอน restart
> (ดิสก์เป็น ephemeral) — พอสำหรับ demo · อยากให้ประวัติอยู่ยาว ต้องต่อ disk หรือ DB

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
