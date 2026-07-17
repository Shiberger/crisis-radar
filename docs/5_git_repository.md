# 5. Git Repository

## สถานะ
โปรเจกต์ init เป็น git repo แยกของตัวเองแล้ว (standalone) พร้อม push ขึ้น GitHub เป็น repo ส่วนตัว/องค์กร
— ทำแบบเดียวกับที่เคยแยก `line-invitefriend-service` ออกมา

## โครงสร้าง repo
```
crisis_radar/
├── README.md
├── requirements.txt
├── run_demo.py                 # รัน pipeline end-to-end
├── data/
│   └── sample_talesrunner_fb_comments.json   # synthetic fixture (ชื่อสมมติ)
├── src/
│   ├── models.py               # Comment / Classified / CommentSource (interface)
│   ├── security.py             # PII masking
│   ├── dashboard.py            # สร้าง dashboard.html
│   ├── sources/
│   │   ├── sample.py           # connector เดโม่
│   │   └── facebook.py         # โครงตัวดึง FB จริง (Graph API/Apify)
│   ├── classify/
│   │   ├── lexicon.py          # Thai sentiment ชั้น 1
│   │   ├── llm.py              # LLM escalation ชั้น 2
│   │   └── pipeline.py         # hybrid routing
│   └── crisis/
│       └── detector.py         # spike detection + report
├── tests/
│   ├── labeled_test_set.json
│   └── run_tests.py            # 9 test, รัน offline
├── output/                     # ผลลัพธ์ (gitignore ไฟล์ generated)
└── docs/                       # เอกสารส่ง 7 หัวข้อ
```

## Branch strategy (ตามที่ทีมใช้กับโปรเจกต์อื่น)
- `main` — เวอร์ชันเสถียร/เดโม่
- `dev` — พัฒนา feature (ต่อ API จริง, เพิ่มช่องทาง)

## คำสั่งรัน
```bash
git clone <repo-url> && cd crisis_radar
python3 run_demo.py           # ไม่ต้องติดตั้งอะไรเพิ่ม (เดโม่ใช้ stdlib ล้วน)
python3 tests/run_tests.py
```

## ลิงก์
- Repo URL: _(รอ push — ยังไม่ push จนกว่าจะยืนยัน remote)_
- Owner: ดู doc 6
