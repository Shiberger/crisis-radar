# 1. Project Summary

## ชื่อโปรเจกต์
**Crisis Radar** — AI Social-Listening & Crisis Early-Warning สำหรับชุมชนเกม

## ปัญหา (Pain Point)
บริษัทเราเป็น agency ดูแลหลายเกม (Talesrunner, WarzTH, TOSM, CabalX, Cabal Mobile ฯลฯ)
ชุมชนหลักอยู่บน Facebook. ทุกวันนี้ทีม Community ต้อง **นั่งไล่ส่องคอมเมนต์หลายเพจด้วยตาเอง**
เพื่อจับว่ามีดราม่า/บั๊ก/คำร้องเรียนโผล่ไหม → ช้า, พลาดได้, และมัก **รู้ตัวหลังเรื่องลุกลามไปแล้ว**
ซึ่งกระทบภาพลักษณ์แบรนด์ของลูกค้าโดยตรง

## สิ่งที่ทำ (Solution)
เครื่องมือที่ทำงานเป็น workflow ต่อเนื่อง: **ดึงคอมเมนต์ → จัด sentiment + topic ด้วย AI →
ตรวจจับ "การพุ่งผิดปกติของคอมเมนต์ลบ" (spike) → แจ้งเตือนทีมทันที** พร้อม dashboard สรุปสถานะรายแบรนด์

จุดต่างจาก "sentiment dashboard ทั่วไป": แกนของ Crisis Radar คือ **early-warning** —
ไม่ได้แค่ป้ายบวก/ลบ แต่บอกว่า *"ตอนนี้กำลังมีวิกฤตไหม เรื่องอะไร รุนแรงแค่ไหน"* โดยถ่วงน้ำหนักด้วย
reach (คอมเมนต์ที่คนแห่ไป like/reply เยอะ = อันตรายกว่า)

## ขอบเขตเดโม่ (Phase 1)
- 1 แบรนด์: **Talesrunner** · 1 ช่องทาง: **Facebook**
- Pipeline ครบวงจรทำงานจริง + test ผ่าน (ดู doc 4) บน synthetic fixture
- ออกแบบ connector ให้ **สลับเป็น Facebook API จริงได้ทันทีเมื่อได้ page admin access**

## คุณค่าเชิงธุรกิจ (ทำไมคุ้มลงทุน)
| เกณฑ์ Phase 2 | Crisis Radar ตอบยังไง |
|---|---|
| AI อยู่ใน workflow จริง | AI (sentiment/topic/crisis-score) เป็นแกนของ flow เตือนภัยรายวัน |
| ลด lead time | จับดราม่าได้เร็วขึ้น = ทีมเข้าไปตอบ/ออกแถลงก่อนลุกลาม |
| ลดงาน manual | เลิกไล่ส่องคอมเมนต์หลายเพจด้วยตา — รวมมาจอเดียว |
| compact ใช้ยาว | **1 tool ใช้ซ้ำได้ทุกเกมในเครือ** (multi-tenant) = เข้าเงื่อนไข incentive รายเดือน |

## ผลลัพธ์เดโม่ (ตัวเลขจริงจากการรัน)
- คอมเมนต์ 34 → จับสถานะ **🔴 CRISIS** ได้ถูก, spike ที่ 14:00 (severity 1232 vs baseline 8)
- ระบุประเด็นหลักอัตโนมัติ: bug/technical (14), billing/price (8), service/support (4)
- Sentiment accuracy **96%** (hybrid) — ชั้น LLM ช่วยเคสประชด 3/3
- Test **9/9 passed**
