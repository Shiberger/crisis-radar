"""ชั้นที่ 1 ของ Hybrid AI: Thai lexicon sentiment + topic tagging (รัน offline ได้).

ทำไมเป็น lexicon ไม่ใช่ deep model ในเดโม่:
  - รันได้ทันทีไม่ต้องโหลดโมเดล/ไม่ต้องเน็ต → test case ได้ผลจริงพิสูจน์ pipeline ได้
  - ใน production ชั้นนี้จะถูกสลับเป็น Wisesight/WangchanBERTa (interface เดียวกัน)
  - เคสที่ lexicon ไม่มั่นใจ (ประชด/สแลง/มีทั้งบวกลบ) จะถูกส่งต่อชั้น LLM (ดู pipeline.py)

ข้อจำกัดที่รู้ตัว (documented): ภาษาไทยไม่มีเว้นวรรค เราจึงใช้ substring matching
ซึ่งอาจ false-positive ได้ (เช่น 'ดี' ใน 'ดีเลย์') — เป็นเหตุผลว่าทำไมต้องมีชั้น LLM.
"""
from __future__ import annotations

POSITIVE = {
    "ชอบมาก", "สนุก", "สุดยอด", "เจ๋ง", "ประทับใจ", "คุ้ม", "น่ารัก", "สวย",
    "ยอดเยี่ยม", "ดีใจ", "รักเลย", "แจ่ม", "ฟิน", "แฮปปี้", "เยี่ยม", "ถูกใจ",
    "กราฟิกสวย", "ขอบคุณมาก", "เพลิน", "ดีขึ้น",
}
NEGATIVE = {
    "แย่", "ห่วย", "เจ๊ง", "พัง", "บั๊ก", "บัก", "ล่ม", "ค้าง", "หลอก", "โกง",
    "แพง", "กาก", "ผิดหวัง", "ปิดเซิร์ฟ", "คืนเงิน", "เซ็ง", "น่าเบื่อ", "หลุด",
    "เข้าไม่ได้", "เด้ง", "error", "รอนาน", "แก้ช้า", "เอาเปรียบ", "ระบบพัง",
    "p2w", "pay to win", "เงินหาย", "โมโห", "แก้ไม่ได้", "เลิกเล่น", "ลาก่อน",
    "โคตรแพง", "ไม่คุ้ม", "อิมบา",
    # เพิ่มจากภาษาจริงในคอมเมนต์ Talesrunner (คำที่ generalize ได้)
    "น่ารำคาญ", "รำคาญ", "อคติ", "กล่าวโทษ", "โทษผู้เล่น", "ความผิดผู้เล่น",
    "ปิดเว็บ", "ห่วยแตก", "ไม่พอใจ", "เสียเวลา", "หลอกลวง", "โกหก", "พังยับ",
    "แย่ที่สุด", "ไม่โอเค", "งี่เง่า", "ไม่รับผิดชอบ", "พลาด",
    # rewards/redeem — อาการ "รับของไม่ได้" (ดู TOPIC_KEYWORDS['rewards/redeem'])
    "ไม่ติด", "ใช้ไม่ได้", "หมดอายุ", "ไม่ได้ของ", "ของไม่เข้า", "ไม่เข้าคลัง",
    "ไม่เข้ากระเป๋า", "ไม่ได้รางวัล", "กรอกไม่ได้", "รับไม่ได้", "แลกไม่ได้",
}
# ตัวขยายความรุนแรง (เพิ่มน้ำหนักคะแนน)
INTENSIFIERS = {"โคตร", "มาก", "สุด", "ที่สุด", "เกินไป", "ด่วน"}
# คำปฏิเสธ — ถ้าอยู่ก่อนคำบวกใกล้ ๆ = พลิกเป็นลบ
NEGATORS = {"ไม่", "หมด", "เลิก"}
# ร่องรอยประชด — ไม่ตัดสินเอง แต่ยก flag ให้ LLM
SARCASM_HINTS = {"555", "ขอบคุณมากค่า", "ดีจริง ๆ นะ", "ดีจังเนอะ", "เก่งมาก", "แหม"}

# คำที่บอกว่า "นี่คือคำถาม" — ใช้ตัดคอมเมนต์ถามข้อมูลออกก่อนถึงชั้น AI (ดู classify/llm.py prefilter)
# คำถามที่ไม่มีคำลบปน = กลาง แทบ 100% ในข้อมูลจริง จึงไม่ต้องจ่ายเงินให้ AI อ่าน
QUESTION_CUES = {"ไหม", "มั้ย", "หรือเปล่า", "รึเปล่า", "หรอ", "เหรอ", "เมื่อไหร่", "เมื่อไร",
                 "ยังไง", "อย่างไร", "อะไรบ้าง", "ทำไง", "ขอถาม", "สอบถาม", "ใครรู้", "?"}

TOPIC_KEYWORDS = {
    "bug/technical": ["บั๊ก", "บัก", "ล่ม", "ค้าง", "เข้าไม่ได้", "เด้ง", "error",
                       "หลุด", "โหลดช้า", "lag", "แลค", "dc", "1023", "ระบบพัง",
                       "ติดตั้ง", "โฟลเดอร์", "โฟเดอร์", "ไดรฟ", "install", "ลงเกม", "ไฟล์เกม"],
    "billing/price": ["แพง", "เติมเงิน", "ราคา", "กาชา", "เปย์", "เงินหาย", "คืนเงิน",
                       "รายเดือน", "คุ้ม", "ช็อป", "ไอเทม"],
    "balance/fairness": ["p2w", "pay to win", "อิมบา", "เอาเปรียบ", "โกง", "ดรอป", "อัตรา"],
    "service/support": ["แอดมิน", "ทีมงาน", "ตอบช้า", "แก้ช้า", "แก้ด่วน", "support", "cs",
                         "ประกาศ", "ชี้แจง", "บริษัท", "จัดการ", "กล่าวโทษ", "โทษผู้เล่น", "รับผิดชอบ"],
    "content/event": ["อีเวนต์", "กิจกรรม", "แพตช์", "อัปเดต", "แผนที่", "ตัวละคร", "ชุด", "เซิร์ฟ"],
    # ⚠️ ห้ามใส่ "โค้ด" เดี่ยว ๆ — ในข้อมูลจริงส่วนใหญ่หมายถึง program code
    #    ("ผิดที่โค้ตตัว uninstall", "เขียนโค้ดพลาด") ไม่ใช่ item code → ต้อง match เป็นวลี
    "rewards/redeem": ["กรอกโค้ด", "ใส่โค้ด", "แลกโค้ด", "รับโค้ด", "แจกโค้ด", "เติมโค้ด",
                        "โค้ดแจก", "มีโค้ด", "ขอโค้ด", "โค้ดฟรี", "โค้ดกิจกรรม",
                        "โค้ดไม่ติด", "โค้ดใช้ไม่ได้", "โค้ดหมดอายุ", "ไอเทมโค้ด", "item code",
                        "redeem", "คูปอง", "coupon", "ซีเรียล", "serial",
                        "รับไอเทม", "รับของ", "รับรางวัล", "ของรางวัล", "ไม่ได้ของ", "ของไม่เข้า",
                        "ไม่เข้าคลัง", "ไม่เข้ากระเป๋า", "เช็คอิน", "ล็อกอินรับ",
                        # reward ads: ดูโฆษณาแลกของ — มักพังพร้อมกันทั้งแคมเปญ
                        "ดูโฆษณา", "กดโฆษณา", "โฆษณาไม่ขึ้น", "ดูแอด", "แอดไม่ขึ้น", "reward ad"],
}

# ชื่อไทยสำหรับแสดงบน dashboard/monitor (โค้ดยังใช้ key อังกฤษเป็น canonical)
TOPIC_LABELS = {
    "bug/technical": "บั๊ก/เทคนิค",
    "billing/price": "เติมเงิน/ราคา",
    "balance/fairness": "สมดุล/ความเป็นธรรม",
    "service/support": "บริการ/ทีมงาน",
    "content/event": "คอนเทนต์/อีเวนต์",
    "rewards/redeem": "ของรางวัล/โค้ด",
}


# คำที่ "กินกัน" จาก substring matching — ตัดทิ้งก่อน match กันตีความผิด
# เช่น 'ไม่ติด' (โค้ดใช้ไม่ได้ = ลบ) ไปโผล่ใน 'ไม่ติดตั้ง' (แค่เล่าขั้นตอน = ไม่ลบ)
_CONFUSABLES = ("ไม่ติดตั้ง", "ถอนการติดตั้ง")


def _normalize(text: str) -> str:
    t = text.lower()
    for c in _CONFUSABLES:
        t = t.replace(c, " ")
    return t


def _count_hits(text: str, terms) -> list[str]:
    return [t for t in terms if t in text]


def tag_topics(text: str) -> list[str]:
    t = _normalize(text)
    found = []
    for topic, kws in TOPIC_KEYWORDS.items():
        if any(kw in t for kw in kws):
            found.append(topic)
    return found


def looks_like_question(text: str) -> bool:
    """เป็นคำถามขอข้อมูลไหม — ใช้เป็นเงื่อนไขหนึ่งของ prefilter ก่อนถึงชั้น AI."""
    t = _normalize(text)
    return any(q in t for q in QUESTION_CUES)


def has_letters(text: str) -> bool:
    """มีตัวอักษรจริงไหม (ไม่ใช่อีโมจิ/สติกเกอร์/เครื่องหมายล้วน)."""
    return any(("ก" <= ch <= "๙") or ch.isalpha() for ch in text)


def classify(text: str) -> dict:
    """คืน dict: sentiment, confidence, topics, needs_llm.

    needs_llm=True เมื่อ lexicon ไม่มั่นใจ → pipeline จะส่งต่อชั้น LLM.
    """
    t = _normalize(text)

    pos = _count_hits(t, POSITIVE)
    neg = _count_hits(t, NEGATIVE)

    # negation: ถ้ามีคำปฏิเสธในข้อความ + มีคำบวก ให้ลดน้ำหนักคำบวก
    has_negator = any(n in t for n in NEGATORS)
    if has_negator and pos:
        # "ไม่สนุก / ไม่คุ้ม" → คำบวกกลายเป็นสัญญาณลบ
        neg = neg + pos
        pos = []

    intensity = 1 + sum(1 for i in INTENSIFIERS if i in t) * 0.5
    score = (len(pos) - len(neg)) * intensity

    has_sarcasm = any(h in text for h in SARCASM_HINTS)
    mixed = bool(pos) and bool(neg)

    # ตัดสิน sentiment
    if score > 0:
        sentiment = "positive"
    elif score < 0:
        sentiment = "negative"
    else:
        sentiment = "neutral"

    # confidence จาก margin
    margin = abs(len(pos) - len(neg))
    confidence = min(1.0, 0.45 + margin * 0.2)

    # เงื่อนไขที่ต้องให้ LLM ช่วย (โมเดลไทยไม่ควรเชื่อ 100%)
    needs_llm = has_sarcasm or mixed or (pos == [] and neg == [] and len(text) > 15)
    if needs_llm:
        confidence = min(confidence, 0.5)

    return {
        "sentiment": sentiment,
        "confidence": round(confidence, 3),
        "topics": tag_topics(text),
        "needs_llm": needs_llm,
        "_debug": {"pos": pos, "neg": neg, "score": round(score, 2)},
    }
