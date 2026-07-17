# 📡 Crisis Radar

**AI social-listening + crisis early-warning สำหรับชุมชนเกมที่เราดูแล**
เริ่มที่ Talesrunner (Facebook) → ออกแบบให้ต่อเกมอื่น/ช่องทางอื่นได้

> ดึงคอมเมนต์ → จัด sentiment (บวก/กลาง/ลบ) + topic → **ตรวจจับการพุ่งผิดปกติ (spike)** →
> แจ้งเตือนทีม Community ให้เข้าไปจัดการก่อนดราม่าลุกลาม รักษาภาพลักษณ์แบรนด์

## รันเดโม่ (offline, ไม่ต้องเน็ต)
```bash
python3 run_demo.py        # → output/crisis_report.md, classified.json, dashboard.html
python3 tests/run_tests.py # → 9 test, ผลจริง
```

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
| Orchestration | รันมือ | n8n schedule → alert เข้า LINE |

## เอกสารส่ง (ดู `docs/`)
1. [Project Summary](docs/1_project_summary.md)
2. [Before–After Workflow](docs/2_before_after_workflow.md)
3. [Workflow Diagram](docs/3_workflow_diagram.md)
4. [Test Cases + ผล](docs/4_test_cases.md)
5. [Git Repository](docs/5_git_repository.md)
6. [Owner](docs/6_owner.md)
7. [Security Information](docs/7_security.md)

> ⚠️ ข้อมูลในเดโม่เป็น **synthetic fixture** (ชื่อสมมติ) เพื่อพิสูจน์ pipeline ก่อนได้ API จริง
