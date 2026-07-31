"""Hybrid classify pipeline: Thai lexicon (เร็ว/ถูก) → LLM เฉพาะเคสไม่มั่นใจ.

3 ชั้น เรียงจากถูกไปแพง — ชั้นที่แพงที่สุดได้งานน้อยที่สุด:

    คอมเมนต์ทั้งชุด
      → ชั้น 1 [lexicon.classify]  เจอ keyword ชัด → จบตรงนี้ (ฟรี · กิน volume ส่วนใหญ่)
      → ชั้น 2 [llm.prefilter]     กฎ deterministic: ประชด / คำถาม / อีโมจิล้วน → จบ (ฟรี)
      → ชั้น 3 [LLM.analyze_batch] ที่เหลือจริง ๆ ถึงเข้า Claude เป็นชุด (เสียเงิน)

ชั้น 2 เพิ่มทีหลังเพราะวัดแล้วพบว่า 78% ของที่ส่งเข้า AI ติดเงื่อนไขเดียวคือ "lexicon ไม่เจอ
keyword เลย" ซึ่งเป็นคำถาม/ชวนคุยเสียส่วนใหญ่ — กฎเดิมที่มีอยู่แล้วตัดสินได้โดยไม่ต้องจ่ายเงิน

ทำไมต้องรวมเป็นชุดก่อนค่อยเรียก LLM (ไม่ยิงทีละคอมเมนต์):
  - ค่า API: system prompt ยาว ๆ ถูกจ่ายครั้งเดียวต่อชุด ไม่ใช่ครั้งเดียวต่อคอมเมนต์
  - เวลา: 30 คอมเมนต์ = 2 request ไม่ใช่ 30 request (สำคัญกับ monitor ที่มี timeout)

ถ้าชั้น LLM ตอบไม่ได้ (คีย์หมด/API ล่ม/โดนปฏิเสธ) จะได้ None กลับมา → ตกไปใช้ engine สำรอง
(OfflineHeuristicLLM) แทน ไม่ปล่อยให้รอบตรวจพังทั้งรอบเพราะปลายทางมีปัญหา
"""
from __future__ import annotations

from typing import Optional

from ..models import Classified, Comment
from . import lexicon
from .llm import OfflineHeuristicLLM, SentimentLLM, from_env, max_items, prefilter

CONF_THRESHOLD = 0.5


class HybridClassifier:
    def __init__(self, llm: Optional[SentimentLLM] = None, conf_threshold: float = CONF_THRESHOLD,
                 log=None, max_llm_items: Optional[int] = None):
        self.log = log or (lambda _m: None)
        # ไม่ส่ง llm มา = เลือกจาก env ให้เอง (มี ANTHROPIC_API_KEY → Claude จริง ไม่มี → heuristic)
        self.llm = llm or from_env(log=self.log)
        self.fallback = OfflineHeuristicLLM()
        self.conf_threshold = conf_threshold
        self.max_llm_items = max_items() if max_llm_items is None else max_llm_items
        self.stats = {"total": 0, "gated": 0, "to_llm": 0}   # ไว้ให้ jobs.py เขียน log ค่าใช้จ่าย

    @property
    def engine(self) -> str:
        return getattr(self.llm, "name", "unknown")

    def classify_one(self, c: Comment) -> Classified:
        return self.classify_all([c])[0]

    def classify_all(self, comments: list[Comment]) -> list[Classified]:
        base = [lexicon.classify(c.text) for c in comments]

        # ชั้น 1 ตัดสินเองได้เท่าไร / ต้องส่งต่อเท่าไร
        need = [i for i, b in enumerate(base)
                if b["needs_llm"] or b["confidence"] < self.conf_threshold]

        # เพดานต่อรอบ — คอมเมนต์กำกวมทะลักตอนเพจแตกต้องไม่กลายเป็นบิลบานปลาย
        # เรียงตามลำดับเดิม (คอมเมนต์เก่าก่อน) เพื่อให้ผลเดิมซ้ำได้ ไม่สุ่มเปลี่ยนทุกรอบ
        if len(need) > self.max_llm_items:
            self.log(f"คอมเมนต์กำกวม {len(need)} เกินเพดาน {self.max_llm_items} ต่อรอบ — "
                     f"ส่วนเกินใช้ผลจากชั้นแรก")
            need = need[:self.max_llm_items]

        # ── ชั้น 2: กฎ deterministic ตัดสินก่อน (ฟรี) ────────────────────────────
        # วัดจากข้อมูลจริง: คอมเมนต์ที่ถูกส่งเข้า AI ส่วนใหญ่ติดเงื่อนไข "lexicon ไม่เจอ keyword เลย"
        # ซึ่งมักเป็นคำถาม/อีโมจิ/ประชดที่กฎเดิมรู้จักดีอยู่แล้ว — ไม่ต้องจ่ายเงินให้ AI อ่านซ้ำ
        answers: dict[int, dict] = {}
        gated = 0
        still_need: list[int] = []
        for i in need:
            got = prefilter(comments[i].text, base[i])
            if got:
                answers[i] = got
                gated += 1
            else:
                still_need.append(i)
        if gated:
            self.log(f"กฎเดิมตัดสินได้เอง {gated} คอมเมนต์ — ไม่ต้องส่งเข้า AI")
        need = still_need

        # ── ชั้น 3: ที่เหลือถึงจะเข้า AI (เสียเงิน) ──────────────────────────────
        # escalated_to_llm = "ถูกส่งเข้าชั้น AI จริง" — ตัวที่ชั้น 2 ตัดสินได้เองไม่นับ
        # (ป้าย "AI อ่านซ้ำ" บนหน้าเว็บจึงตรงกับสิ่งที่จ่ายเงินไปจริง ๆ)
        escalated = set(need)
        self.stats = {"total": len(comments), "gated": gated, "to_llm": len(need)}
        if need:
            items = [(comments[i].text, base[i]["topics"]) for i in need]
            results = self.llm.analyze_batch(items)
            missing = [n for n, r in zip(need, results) if r is None]
            for n, r in zip(need, results):
                if r is not None:
                    answers[n] = r
            if missing:
                # ชั้น LLM ตอบไม่ได้ → ใช้ตัวสำรอง ไม่ปล่อยให้คอมเมนต์กำกวมตกไปเป็นค่าดิบของ lexicon
                self.log(f"ใช้ตัวสำรองแทน {len(missing)} คอมเมนต์ที่ AI ตอบไม่ได้")
                spare = self.fallback.analyze_batch(
                    [(comments[i].text, base[i]["topics"]) for i in missing])
                answers.update({i: r for i, r in zip(missing, spare) if r})

        out: list[Classified] = []
        for i, c in enumerate(comments):
            got = answers.get(i)
            b = base[i]
            out.append(Classified(
                comment=c,
                sentiment=(got or b)["sentiment"],
                confidence=(got or b)["confidence"],
                topics=list((got or b).get("topics") or b["topics"]),
                escalated_to_llm=i in escalated,
            ))
        return out
