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
      G --> J["แจ้งเตือน LINE ทีม Community"]
    end
```

## Orchestration ตอน production (n8n)
```mermaid
flowchart LR
    T["⏰ Schedule<br/>(ทุก 30–60 นาที)"] --> S["ดึงคอมเมนต์<br/>ทุกเพจ/เกม"]
    S --> P["Crisis Radar pipeline"]
    P --> Q{"สถานะ = CRISIS ?"}
    Q -->|ใช่| L["ส่ง LINE alert +<br/>tag ทีมเกมนั้น"]
    Q -->|ไม่| M["อัปเดต dashboard เงียบ ๆ"]
    L --> R["ทีมเข้าไปจัดการ"]
```

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
