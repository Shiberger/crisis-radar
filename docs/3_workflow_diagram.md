# 3. Workflow Diagram

## Pipeline หลัก (data flow)
```mermaid
flowchart LR
    subgraph SRC["1 · Source (สลับได้)"]
      A1["SampleFacebookSource<br/>(เดโม่)"]
      A2["Meta Graph API /<br/>Apify (production)"]
    end
    SRC -->|"Comment ที่ mask PII แล้ว"| B

    subgraph AI["2 · Hybrid AI Classify"]
      B["Thai lexicon<br/>(เร็ว/ถูก)"] -->|"มั่นใจ"| D
      B -->|"ประชด/สแลง/<br/>ไม่มั่นใจ"| C["LLM escalation<br/>(Claude Haiku)"]
      C --> D["sentiment + topic +<br/>confidence"]
    end

    D --> E

    subgraph CR["3 · Crisis Detector"]
      E["จัดกลุ่มตามเวลา +<br/>ถ่วง reach"] --> F{"severity ><br/>baseline × 2.5 ?"}
      F -->|ใช่| G["🚨 spike → alert"]
      F -->|ไม่| H["บันทึกเป็น baseline"]
    end

    G --> I
    H --> I
    subgraph OUT["4 · Output"]
      I["Dashboard (สถานะรายแบรนด์)"]
      G --> J["แจ้งเตือน Discord<br/>(ตาม channel ของทีม)"]
    end
```

## แจ้งเตือนเข้า Discord ผ่าน n8n (ทำงานจริงแล้ว)
Crisis Radar เป็นฝ่าย **ยิง webhook ออก** เมื่อมีเรื่องต้องแจ้ง — n8n รับแล้วเลือกปลายทาง
(รอบตรวจยังคุมด้วย monitor ในตัว ไม่ต้องพึ่ง Schedule ของ n8n)

```mermaid
flowchart LR
    subgraph CR["Crisis Radar"]
      P["รอบตรวจ (monitor)"] --> Q{"คอมเมนต์ลบ +<br/>reach ≥ เกณฑ์ ?"}
      Q -->|ใช่| A1["auto alert"]
      Q -->|ไม่| M["อัปเดต dashboard เงียบ ๆ"]
      M -.->|"AI อ่านเป็น กลาง/บวก<br/>แต่คนอ่านออกว่าเป็นเรื่อง"| A2["🔔 คนกดปุ่มแจ้งเอง"]
      A1 --> D["กันแจ้งซ้ำ<br/>(alerts_sent.json)"]
      A2 --> D
    end
    D -->|"POST + X-Crisis-Radar-Token"| W["n8n Webhook"]
    W --> S{"severity"}
    S -->|high| L1["Discord #crisis-alert<br/>+ mention role ทีมเจ้าของเรื่อง"]
    S -->|medium| L2["Discord #watch"]
    L1 --> R["ทีมเข้าไปจัดการ"]
```

> **ทำไมต้องมี 2 ทาง:** ระบบแจ้งเองครอบเฉพาะสิ่งที่ AI ตัดสินว่า "ลบและแรง" —
> เคสที่ AI อ่านพลาด (ให้เป็นกลาง/บวก) จะไม่มีวันถูกแจ้งเลย คนที่นั่งดูจึงต้องดันเข้า Discord เองได้
> · ตั้งค่า/ไฟล์ workflow: [`n8n/README.md`](../n8n/README.md)

## Multi-tenant (ทำไม compact + ใช้ยาว)
```mermaid
flowchart TB
    CORE["Crisis Radar core<br/>(pipeline เดียว)"]
    CORE --> G1["Talesrunner"]
    CORE --> G2["WarzTH"]
    CORE --> G3["TOSM"]
    CORE --> G4["CabalX / Cabal Mobile"]
    CORE --> G5["...เกมใหม่ (เพิ่มแค่ config)"]
```
> เพิ่มเกมใหม่ = เพิ่ม config เพจ + brand ไม่ต้องเขียนโค้ดใหม่ → 1 tool ดูแลทั้งเครือ
