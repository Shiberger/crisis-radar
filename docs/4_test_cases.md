# 4. Test Cases พร้อมผลทดสอบ

รันทั้งหมด offline:  `python3 tests/run_tests.py`  (ไม่ต้องเน็ต, ผลด้านล่างคือผลจริงจากการรัน)

## สรุปผล: ✅ 9 / 9 passed

| # | Test Case | สิ่งที่ตรวจ | ผลจริง | สถานะ |
|---|---|---|---|---|
| T1 | Sentiment accuracy | hybrid classify บน labeled set 24 เคส ≥ 80% | **96%** (23/24) | ✅ PASS |
| T2 | ชั้น LLM ยกระดับผล | hybrid ต้อง ≥ lexicon-only | 92% → **96%** (+4 จุด) | ✅ PASS |
| T2b | เคสประชด (sarcasm) | hybrid จับถูก ≥ ครึ่ง | **3/3** | ✅ PASS |
| T3 | Crisis detection | sample จริงต้องได้สถานะ CRISIS | status = CRISIS | ✅ PASS |
| T3b | Spike detection | เจอช่วงพุ่งผิดปกติ ≥ 1 | 1 ช่วง (14:00) | ✅ PASS |
| T3c | Alert | สร้าง alert ≥ 1 | 2 alert | ✅ PASS |
| T4 | Calm scenario | ข้อมูลปกติต้อง **ไม่** alert (กัน false alarm) | status = NORMAL, 0 spike | ✅ PASS |
| T5 | PII masking | ชื่อจริงต้องไม่หลุดใน output | 'Somchai R' → 'user_6515f5' | ✅ PASS |
| T6 | Connector interface | source คืน field ครบ | 34 comments ครบ field | ✅ PASS |

## รายละเอียดที่สำคัญ

### T1–T2b — ความแม่นของ AI + คุณค่าของชั้น LLM
- Confusion (gold → hybrid): positive 6/6 ถูก, negative 13/13 ถูก, neutral 4/5 ถูก (1 เคส mixed เอนไปลบ)
- **จุดขายของ hybrid:** เคสประชดอย่าง *"ดีจริง ๆ นะคะที่ล่มตอนคนกำลังจะเล่น ขอบคุณมากค่า"* —
  lexicon อ่านผิดเป็นกลาง/บวก แต่ชั้น LLM เห็นบริบท "ล่ม" + น้ำเสียงประชด → แก้เป็น **ลบ** ถูกต้อง
- ต้นทุน LLM คุมได้: เดโม่ส่งต่อ LLM แค่ **8/34 เคส (24%)** เฉพาะที่ไม่มั่นใจ

> ⚠️ ข้อจำกัดที่ระบุตรง ๆ: labeled set นี้เป็น curated set เล็ก (24) — เป็น smoke-test พิสูจน์ว่า
> logic ทำงานถูก ไม่ใช่ benchmark generalization. Production ต้องมี labeled holdout ชุดใหญ่จากคอมเมนต์จริง

### T3 — Crisis detection (หัวใจของ tool)
Timeline ที่ระบบตรวจได้จาก sample:

| ช่วง | คอมเมนต์ | ลบ | severity | baseline | spike |
|---|---|---|---|---|---|
| 10:00 | 4 | 0 | 0 | 0 | |
| 11:00 | 4 | 1 | 10 | 0 | |
| 12:00 | 4 | 2 | 12 | 5 | |
| 13:00 | 3 | 2 | 10 | 7 | |
| 14:00 | 19 | 18 | **1232** | 8 | 🚨 |

ระบบจับ spike ที่ 14:00 (หลังปล่อยแพตช์) ได้ถูก พร้อมระบุประเด็น: bug/technical(12), billing/price(6), service/support(4)
และจับคอมเมนต์ลบไวรัล reach 203 เรื่องกาชาแพงได้

### T4 — กัน false alarm
ป้อนคอมเมนต์บวกล้วน 20 อัน → ระบบให้ NORMAL, 0 spike (ไม่เตือนมั่ว) — พิสูจน์ว่า threshold ไม่ไวเกิน

### T5 — Security (PII)
ชื่อผู้คอมเมนต์ถูก hash เป็น `user_xxxxxx` ตั้งแต่ตอนโหลด — output ทุกไฟล์ไม่มีชื่อจริง (ดู doc 7)
