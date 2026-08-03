# เกณฑ์การให้คะแนนจุดเสี่ยง (Road Risk Assessment Model, คะแนนเต็ม 100)

เอกสารอ้างอิงประกอบโมเดลใน `scripts/build_risk_points.py` (เกณฑ์แบบเก่า)

## สรุปที่มา: อะไร "อ้างอิงได้" อะไร "คาลิเบรตเอง"

จุดสำคัญที่ต้องแยกให้ชัดเวลานำเสนอ/สอบ: **ทฤษฎีและวิธี** ของทุกปัจจัยมีงานวิจัยรองรับ แต่ **ตัวเลขเจาะจงบางค่า** เป็นการปรับสเกลตามชุดข้อมูล (empirical calibration) ไม่ได้ลอกตัวเลขมาจากงานวิจัยตรงๆ — การระบุแบบนี้ในรายงานทำให้งานน่าเชื่อถือขึ้น ไม่ใช่จุดอ่อน

| พารามิเตอร์ | ค่าที่ใช้ | สถานะ | แหล่งอ้างอิง + หน้า |
|---|---|---|---|
| การจัดกลุ่ม DBSCAN | eps 400 ม., min 3 | **วิธีอ้างอิงได้** | ResearchGate 383141692; Taylor & Francis (Hanoi 2019) |
| สเกล log + saturation (วิธี) | ln(1+x) | **วิธีอ้างอิงได้** | OECD/JRC 2008 |
| จุดอิ่มตัว FREQ/EPDO | 50 / 120 | *คาลิเบรตเอง* | จากการกระจายข้อมูลจริง (ไม่มีงานวิจัยตรง) |
| วิธี EPDO (ถ่วงน้ำหนักตามความรุนแรง) | — | **วิธีอ้างอิงได้** | FHWA Network Screening (Step 2) |
| อัตราส่วน EPDO | 10 : 4 : 1 | *คาลิเบรตเอง* | ปรับสเกลลงจากอัตราส่วนต้นทุน FHWA ที่สูงกว่ามาก |
| ลักษณะถนน (Conflict Point Theory) | 1.0–0.3 | **ทฤษฎีอ้างอิงได้** | FHWA Roundabouts Guide, Exhibit 2-3 **หน้า 25-26** |
| ความเร็ว² (Nilsson power model) | (v/120)² | **สมการอ้างอิงได้** | ETSC 2019 **หน้า 3, 6**; Nilsson 2004 |
| เพดานความเร็ว 100/90/80 | ตามประเภทถนน | **กฎหมายอ้างอิงได้** | กฎกระทรวงฯ พ.ศ. 2564, ข้อ 8-9 |
| KSI safety override | ตาย≥2→สูง, ≥1→กลาง | **หลักการอ้างอิงได้** | KSI (UK/EU standard) |
| น้ำหนัก 4 ปัจจัย | 30/35/20/15 | *คาลิเบรตเอง* | แนวคิดผสม reactive+proactive (Walden 2015 หน้า 2) |
| เกณฑ์แบ่งระดับ | สูง≥55, กลาง≥40 | *คาลิเบรตเอง* | จากการกระจายคะแนนจริง (ไม่มีงานวิจัยตรง) |

## กรอบแนวคิดรวม

โมเดลผสมปัจจัย 2 กลุ่มตามแนวทาง Highway Safety Improvement Program (HSIP) ของ FHWA:

| กลุ่ม | ปัจจัย | คะแนน | ลักษณะ |
|---|---|---|---|
| **Reactive** (จากอุบัติเหตุที่เกิดจริง) | ความถี่ | 30 | จำนวนอุบัติเหตุในคลัสเตอร์ |
| | ความรุนแรง | 35 | ผู้เสียชีวิต/บาดเจ็บ ถ่วงน้ำหนัก EPDO |
| **Proactive/Systemic** (จากปัจจัยเสี่ยงเชิงกายภาพ) | ลักษณะถนน | 20 | จุดขัดแย้งกระแสจราจร |
| | ความเร็วถนน | 15 | เพดานความเร็วตามกฎหมาย |

FHWA ระบุว่าแนวทาง systemic (proactive) "ไม่ได้แทนที่ site analysis แบบดั้งเดิม แต่**เสริมกัน**" — *"a systemic approach does not replace the traditional site analysis but instead complements it"* (Walden et al. 2015, หน้า 2)

## สูตรรวม

```
risk_score = frequency + severity + geometry + speed          (เต็ม 100)

frequency = 30 × min(1, ln(1+n) / ln(1+50))
severity  = 35 × min(1, ln(1+EPDO) / ln(1+120))
            โดย EPDO = 10×ตาย + 4×สาหัส + 1×เล็กน้อย
geometry  = 20 × ค่าเฉลี่ย geometry_weight ของทุกเหตุการณ์ในคลัสเตอร์
speed     = 15 × (v_limit / 120)²
```

## รายละเอียดและแหล่งอ้างอิงรายเกณฑ์

### 1) การจัดกลุ่มจุดเสี่ยงด้วย DBSCAN (eps 400 ม., min_samples 3)

พิกัด GPS ของเหตุที่ "จุดเดียวกัน" ในโลกจริงไม่ตรงกันเป๊ะ จึงจัดกลุ่มก่อนให้คะแนน DBSCAN เป็นวิธีมาตรฐานในงานวิจัย accident hotspot เพราะ (ก) ไม่ต้องกำหนดจำนวนกลุ่มล่วงหน้า (ข) จับกลุ่มรูปทรงอิสระได้ (ถนนโค้ง/แยกซับซ้อน)

- Exploring Road Traffic Accidents Hotspots Using Clustering Algorithms and GIS-based Spatial Analysis (2024) — https://www.researchgate.net/publication/383141692
- Determining road traffic accident hotspots using GIS-based techniques, Hanoi (Taylor & Francis, 2019) — https://www.tandfonline.com/doi/full/10.1080/10095020.2019.1683437

### 2) ความถี่ (30 คะแนน) — สเกล log + จุดอิ่มตัว

จำนวนอุบัติเหตุต่อคลัสเตอร์แจกแจงหางยาว (ข้อมูลจริงปี 2568: ส่วนใหญ่ 3-20 ครั้ง, สูงสุด 364 ครั้ง) จึงใช้ log transform ตามหลัก diminishing returns ของการสร้างดัชนีรวม แล้วตัดหางที่ **FREQ_SATURATION = 50 ครั้ง** (คาลิเบรตเอง)

- OECD/JRC (2008). *Handbook on Constructing Composite Indicators: Methodology and User Guide* — https://www.oecd.org/en/publications/handbook-on-constructing-composite-indicators-methodology-and-user-guide_9789264043466-en.html
- แนวคิด frequency เป็นตัวชี้วัดหลักของ network screening: FHWA, Step 2 Conduct Network Screening — https://highways.dot.gov/safety/local-rural/improving-safety-rural-local-and-tribal-roads-safety-toolkit/step-2-conduct

### 3) ความรุนแรง (35 คะแนน) — EPDO

**วิธี EPDO (Equivalent Property Damage Only)** — ถ่วงน้ำหนักเหยื่อแต่ละระดับตามความรุนแรง เป็นวิธีมาตรฐานของ HSM/HSIP network screening: *"weighting factors related to the societal costs of fatal, injury, and property damage-only crashes are assigned to crashes by severity"*

**อัตราส่วน 10 : 4 : 1** (ตาย : สาหัส : เล็กน้อย) เป็น **ค่าปรับสเกลลง** จากอัตราส่วนต้นทุนอุบัติเหตุจริงของ FHWA ที่สูงกว่านี้มาก (เช่นปี 2024 K:A:B ≈ 41.6:4.4:1) — ปรับให้ severity อยู่ใน range 0-35 ของโมเดล จุดอิ่มตัว **EPDO_SATURATION = 120** (≈เสียชีวิต 12 ราย, คาลิเบรตเอง)

- นิยามวิธี EPDO: FHWA, Step 2 Conduct Network Screening — https://highways.dot.gov/safety/local-rural/improving-safety-rural-local-and-tribal-roads-safety-toolkit/step-2-conduct
- ต้นทุนอุบัติเหตุอ้างอิง: FHWA Crash Cost Fact Sheet (วิธี FHWA-SA-17-071) — https://highways.dot.gov/sites/fhwa.dot.gov/files/2025-10/CrashCostFactSheet_508_OCT2025.pdf
- ต้นทุนอุบัติเหตุไทย (เทียบเคียง): TDRI (2560) เสียชีวิต ~10 ล้านบาท, สาหัส ~3 ล้านบาท — https://tdri.or.th/2017/08/econ_traffic_accidents/

### 4) ลักษณะถนน (20 คะแนน) — Conflict Point Theory

น้ำหนัก 0-1 ต่อเหตุการณ์ ตามจำนวนจุดขัดแย้งกระแสจราจร (conflict points) ของรูปแบบถนน:

| บริเวณ | น้ำหนัก | เหตุผล + อ้างอิง |
|---|---|---|
| ทางแยก/ทางร่วม | 1.0 | สี่แยกมาตรฐานมี conflict point สูงสุด 32 จุด (crossing 16 + merging 8 + diverging 8) — FHWA Roundabouts Guide, **Exhibit 2-3 หน้า 25-26** |
| จุดกลับรถ | 0.9 | crossing conflict กับกระแสสวนทาง — TxDOT Manual §11.3.7.1 |
| ทางโค้งลาดชัน / ทางโค้ง | 0.9 / 0.8 | โค้งรัศมีแคบมีอุบัติเหตุรุนแรงเกินสัดส่วนระยะทาง ~3 เท่า — Walden et al. 2015, **Figure 2-3 หน้า 40** |
| ทางเชื่อมเข้าพื้นที่ | 0.7 | access density เป็น systemic risk factor — Walden et al. 2015, **Table 1-2 หน้า 7** |
| ทางลาดชัน | 0.5 | ความเสี่ยงปานกลาง ไม่มีจุดตัดกระแส |
| ทางตรง | 0.3 | ฐานความเสี่ยงต่ำสุด (ไม่มี conflict point) |

- FHWA (2000). *Roundabouts: An Informational Guide* (FHWA-RD-00-067), Ch.2 หน้า 25-26 — https://www.fhwa.dot.gov/publications/research/safety/00067/000672.pdf
- TxDOT Traffic Safety Manual §11.3.7.1 Conflict Points — https://www.txdot.gov/manuals/des/tsp/chapter-11-interchange-analysis/11-3-interchange-configuration-evaluation--ice-/11-3-7-stage-2-safety-performance-and-ice/11-3-7-1-conflict-points.html

### 5) ความเร็วถนน (15 คะแนน) — Nilsson Power Model

`15 × (v/120)²` — ความเสี่ยงอุบัติเหตุบาดเจ็บแปรผันตามกำลังสองของความเร็ว (injury crashes ∝ v²) ตาม power model ของ Nilsson ฐานฟิสิกส์คือแรงปะทะต่อร่างกาย F = ½mv²/s แปรผันตาม v² (ETSC 2019, **หน้า 3** หัวข้อ 1.4; กำลัง 2/3/4 สำหรับบาดเจ็บ/สาหัส/เสียชีวิต: **หน้า 6** หัวข้อ 2.5) ตัวหาร 120 = เพดานความเร็วสูงสุดตามกฎหมายไทย

ความเร็วรายถนนอนุมานจากประเภทสายทาง (ทางพิเศษ 100 / ทางหลวง 90 / ทางหลวงชนบท 80 กม./ชม.)

- ETSC (2019). *The mathematical relation between collision risk and speed* หน้า 3, 6 — https://etsc.eu/wp-content/uploads/The-mathematical-relation-between-collision-risk-and-speed.pdf
- Nilsson, G. (2004). *Traffic safety dimensions and the Power Model to describe the effect of speed on safety.* Bulletin 221, Lund Institute of Technology
- กฎกระทรวงกำหนดอัตราความเร็วสำหรับการขับรถในทางเดินรถ พ.ศ. 2564 (ราชกิจจานุเบกษา เล่ม 138 ตอนที่ 77 ก, ข้อ 8-9) — https://th.wikisource.org/wiki/กฎกระทรวงกำหนดอัตราความเร็วสำหรับการขับรถในทางเดินรถ_พ.ศ._2564

### 6) เกณฑ์แบ่งระดับ — Threshold คงที่ + KSI Override

แบ่ง 3 ระดับด้วยเกณฑ์คงที่ **สูง ≥ 55, ปานกลาง ≥ 40** (คาลิเบรตจากการกระจายคะแนนจริง — ดู percentile ที่ print ใน main)

**Safety override ตามหลัก KSI** (Killed or Seriously Injured): จุดที่มีผู้เสียชีวิต ≥ 2 จัดระดับสูงทันที, ≥ 1 จัดระดับกลางขึ้นไป เพราะตัวชี้วัดสากลด้าน road safety ถือว่าจุดที่เคยมีผู้เสียชีวิตต้องไม่ถูกจัดความเสี่ยงต่ำ แม้คะแนนรวมไม่ถึงเกณฑ์

- KSI: Killed or seriously injured (มาตรฐานสหราชอาณาจักร/สหภาพยุโรป) — https://en.wikipedia.org/wiki/Killed_or_seriously_injured
- Road safety comparisons with international data on seriously injured (ScienceDirect) — https://www.sciencedirect.com/science/article/abs/pii/S0967070X17303682

## ผลจากข้อมูลจริง (รันล่าสุด, ข้อมูลปี 2568)

- ข้อมูลอุบัติเหตุ 12,544 แถวทั่วประเทศ → กรุงเทพฯ+ปริมณฑล 2,178 จุด → 108 คลัสเตอร์
- ผลจัดระดับ: **สูง 28 | ปานกลาง 52 | ต่ำ 28 จุด**
- risk_score: min 27.0 | P25 39.8 | P50 45.8 | P75 56.2 | P90 65.0 | max 83.5

## ข้อจำกัด (ควรระบุในรายงาน)

1. ค่าที่ "คาลิเบรตเอง" (อัตราส่วน EPDO 10:4:1, saturation 50/120, threshold 55/40, น้ำหนัก 30/35/20/15) ยังไม่ได้ตรวจสอบด้วย regression กับข้อมูลอุบัติเหตุปีถัดไป — แนวทางพัฒนาต่อคือประมาณน้ำหนักแบบ Safety Performance Function (SPF) ตาม Highway Safety Manual ซึ่งต้องการข้อมูลปริมาณจราจร (AADT) รายจุดที่ชุดข้อมูลปัจจุบันไม่มี
2. ความเร็วรายจุดเป็นค่าอนุมานจากประเภทสายทาง ไม่ใช่ป้ายจำกัดความเร็วจริง
3. งานวิจัยรุ่นหลัง (Elvik 2013, 2019) เสนอว่าความสัมพันธ์ความเร็ว-ความเสี่ยงเป็น exponential แม่นกว่า power model — ในช่วงความเร็วแคบ (80-100 กม./ชม.) ของงานนี้ ทั้งสองแบบให้ผลใกล้เคียงกัน (ETSC 2019 หน้า 8-9)

## เอกสารอ้างอิงหลัก (รูปแบบเต็ม)

1. Walden, T.D., Lord, D., Ko, M., Geedipally, S., & Wu, L. (2015). *Developing Methodology for Identifying, Evaluating, and Prioritizing Systemic Improvements.* Texas A&M Transportation Institute / TxDOT. https://ftp.txdot.gov/pub/txdot-info/trf/trafficsafety/engineering/systemic-improvements.pdf
2. FHWA. *Step 2: Conduct Network Screening* (EPDO method). https://highways.dot.gov/safety/local-rural/improving-safety-rural-local-and-tribal-roads-safety-toolkit/step-2-conduct
3. FHWA (2000). *Roundabouts: An Informational Guide* (FHWA-RD-00-067). https://www.fhwa.dot.gov/publications/research/safety/00067/000672.pdf
4. ETSC (2019). *The mathematical relation between collision risk and speed.* https://etsc.eu/wp-content/uploads/The-mathematical-relation-between-collision-risk-and-speed.pdf
5. Nilsson, G. (2004). *Traffic safety dimensions and the Power Model.* Bulletin 221, Lund Institute of Technology.
6. Elvik, R., Christensen, P., & Amundsen, A. (2004). *Speed and road accidents: An evaluation of the Power Model.* TØI report 740/2004.
7. OECD/JRC (2008). *Handbook on Constructing Composite Indicators.* OECD Publishing.
8. TxDOT Traffic Safety Manual, Ch.11 §11.3.7.1 Conflict Points.
9. TDRI (2560). อุบัติเหตุทางถนน...ความเสียหายร้ายแรงต่อเศรษฐกิจไทย. https://tdri.or.th/2017/08/econ_traffic_accidents/
10. กฎกระทรวงกำหนดอัตราความเร็วสำหรับการขับรถในทางเดินรถ พ.ศ. 2564. ราชกิจจานุเบกษา เล่ม 138 ตอนที่ 77 ก.
11. Killed or seriously injured — Wikipedia / ScienceDirect S0967070X17303682.
