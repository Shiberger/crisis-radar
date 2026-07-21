# Project Brief: Crisis Radar (AI Social-Listening & Crisis Early-Warning)

**วันที่เริ่ม:** 2026-07-17
**ผู้ขอ / Stakeholder:** ทีม Community/Social ของเกมในเครือ + ทีม INT (AI Project Phase 2)
**สถานะ:** 🟡 Demo/Prototype เสร็จ (Talesrunner / Facebook) — รอ pilot 15 วัน

---

## 1. คำถามธุรกิจ (เราพยายามตัดสินใจอะไร?)
> เราจะ **จับสัญญาณดราม่า/วิกฤตบน Social ของเกมที่เราดูแลให้เร็วขึ้น** เพื่อรักษาภาพลักษณ์แบรนด์
> โดยให้ AI ทำแทนการนั่งไล่ส่องคอมเมนต์ด้วยตา ได้อย่างไร?

## 2. ขอบเขต (Scope)
- **In:** ดึงคอมเมนต์ → sentiment + topic → spike/crisis detection → alert + dashboard
- **In (เดโม่):** 1 แบรนด์ Talesrunner, 1 ช่องทาง Facebook, บน synthetic fixture
- **Out (เฟสนี้):** ตอบคอมเมนต์อัตโนมัติ, ช่องทาง X/TikTok, การดึง FB จริง (รอ page admin access)

## 3. Metric / KPI
- Detection lead time (จับดราม่าได้เร็วกว่าคนเฝ้าเดิมกี่ชม.)
- Coverage (เพจ/เกมที่เฝ้าพร้อมกัน), เวลา manual ที่ประหยัด
- Sentiment accuracy, true/false alert rate

## 4. แหล่งข้อมูล
- [x] Facebook (เดโม่ = synthetic fixture; production = Meta Graph API)
- [ ] Pantip / Google Play / YouTube (เฟสถัดไป)

## 5. Success Criteria
- Pipeline ครบวงจร + test ผ่าน (✅ 13/13) — **ทำแล้ว**
- จับ crisis จาก sample ได้ถูก (✅ CRISIS + spike) — **ทำแล้ว**
- ต่อ Facebook API จริง + รัน pilot 15 วัน วัด Impact — **ขั้นถัดไป**

## 6. สมมติฐาน
- คอมเมนต์ลบที่ "พุ่งผิดปกติเทียบ baseline" = สัญญาณวิกฤตที่ควรเตือน
- Hybrid (Thai model + LLM เฉพาะเคสยาก) แม่นพอและคุมต้นทุนได้

## 7. ข้อสังเกต / ข้อจำกัด
- เดโม่ยังไม่ได้แตะ FB จริง (ไม่มี admin access) → ใช้ fixture พิสูจน์ pipeline ก่อน, connector สลับเป็น API ได้ทันที
- labeled set เล็ก (24) = smoke-test ไม่ใช่ benchmark → production ต้องมี labeled holdout จริง

## 8. ผลสรุป (Bottom Line)
- **ตัวเลขที่เจอ:** sample 41 คอมเมนต์ → 🔴 CRISIS, spike 14:00 (severity 1232 vs baseline 8); accuracy 97%; test 13/13
- **ความหมาย:** pipeline ทำงานจริงครบวงจร พิสูจน์คอนเซปต์ crisis early-warning ได้
- **Next Action:** ขอ FB Graph API access → รัน pilot Talesrunner 15 วัน → ขยายเกมอื่น (multi-tenant)
