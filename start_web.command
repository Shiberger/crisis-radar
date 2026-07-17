#!/bin/bash
# ดับเบิลคลิกไฟล์นี้ใน Finder เพื่อเปิด Crisis Radar (ไม่ต้องพิมพ์คำสั่ง)
# จะเปิดเบราว์เซอร์ให้อัตโนมัติที่ http://127.0.0.1:8000
cd "$(dirname "$0")" || exit 1
python3 -c "import webbrowser,threading; threading.Timer(1.8, lambda: webbrowser.open('http://127.0.0.1:8000')).start()"
echo "กำลังเปิด Crisis Radar… ปิดหน้าต่างนี้เพื่อหยุดเซิร์ฟเวอร์"
python3 backend/server.py
