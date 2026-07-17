# คู่มือดึงข้อมูล Facebook จริง (รัน local)

> ⚠️ อ่านส่วน "กฎหมาย/PDPA" ก่อนดึงกลุ่ม. เดโม่แนะนำให้เริ่มจาก **เพจ public** ก่อน

## ความเป็นไปได้ของแต่ละเป้าหมาย

| เป้าหมาย | ประเภท | ดึงได้ | ต้องมีอะไร |
|---|---|---|---|
| `thehof.talesrunner` | เพจ public | ✅ | Apify token (หรือ Playwright + session) |
| `groups/talesrunnerthgroup` | กลุ่ม | ⚠️ ถ้า private | เป็นสมาชิก + **cookie ล็อกอิน** |
| `groups/1024366639073240` | กลุ่ม | ⚠️ ถ้า private | เป็นสมาชิก + **cookie ล็อกอิน** |

**ทำไมไม่มี "ดึงแบบไม่ล็อกอิน":** ทดสอบแล้ว — เข้าเพจโดยไม่ล็อกอินได้แค่ **หน้า login wall**
(HTTP 200 แต่ไม่มีคอมเมนต์จริง). ทุกวิธีที่ได้คอมเมนต์จริงต้องมี session ล็อกอิน

---

## วิธี A — Apify (แนะนำ: เสถียรสุด)

```bash
pip install apify-client
export APIFY_TOKEN=xxxx          # console.apify.com > Settings > Integrations

# เพจ public เท่านั้น (demo ปลอดภัย) — ดึงแล้วรัน pipeline ต่อเลย
python scrape_facebook.py --method apify --only page --max-posts 10 --max-comments 30 --run
```

ผลลัพธ์: `data/facebook_live_talesrunner.json` → เข้า pipeline → `output/dashboard.html`

**ถ้า field ไม่ตรง** (actor เปลี่ยนเวอร์ชัน): ดู raw item ตัวแรกแล้วปรับ `_pick(...)` ใน `facebook_apify.py`
```bash
python scrape_facebook.py --method apify --only page --inspect
```

### ดึงกลุ่ม (ต้องเป็นสมาชิก)
1. ล็อกอิน FB ในเบราว์เซอร์ → export cookies เป็น JSON (ใช้ extension เช่น "Get cookies.txt" แล้วแปลงเป็น JSON array)
2. ```bash
   FB_COOKIES_JSON=fb_cookies.json python scrape_facebook.py --method apify --run
   ```

---

## วิธี B — Playwright (ฟรี แต่เปราะ)

```bash
pip install playwright && python -m playwright install chromium
# เตรียม session ครั้งเดียว (ดูวิธีใน src/sources/facebook_playwright.py)
python scrape_facebook.py --method playwright --only page --run
```
ข้อจำกัด: selector FB เปลี่ยนบ่อยต้องคอยปรับ, ดึง like count ไม่ได้ (reach=0). ใช้เมื่อไม่มีงบ Apify

---

## กฎหมาย / PDPA (ต้องอ่าน)

| เป้าหมาย | ความเสี่ยง | การรับมือ |
|---|---|---|
| เพจ public | ต่ำ — คอนเทนต์เปิดสาธารณะ | mask PII, ใช้ภายในองค์กร |
| กลุ่ม (โดยเฉพาะ private) | **สูง** — สมาชิกคาดหวังความเป็นส่วนตัว, PDPA ไทย | เริ่มทีหลัง, เคลียร์ฐานทางกฎหมาย (legitimate interest), mask ชื่อ, เก็บเชิงรวม (aggregate) ไม่เก็บรายบุคคล |

**หลักปฏิบัติเสมอ:** ดึงเท่าที่จำเป็น · mask ชื่อทันที (`security.py`) · เก็บภายใน · ไม่เผยแพร่ข้อมูลบุคคลออกนอก ·
เคารพ ToS/robots · rate-limit สุภาพ

> **คำแนะนำเชิงกลยุทธ์:** ปลายทางที่ถูกต้องคือ **Meta Graph API + page admin token** (เพจที่บริษัทดูแล)
> ซึ่งถูก ToS 100% และไม่ต้อง scrape. Scraper ชุดนี้ไว้ **พิสูจน์คุณค่าช่วง prototype** ก่อนขอ API จริง
