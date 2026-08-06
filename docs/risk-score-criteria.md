# เกณฑ์การให้คะแนนจุดเสี่ยง — โมเดล v2 (4 เกณฑ์ × 25%, Percentile Rank + จุดตัดคงที่)

เอกสารอ้างอิงประกอบโมเดลใน `scripts/build_risk_points.py`
(โมเดล v1 แบบ log-norm 30/35/20/15 ดูได้จาก git history — ถูกแทนที่เพราะปัญหา score drift)

## สิ่งที่เปลี่ยนจาก v1 และเหตุผล

| ประเด็น | v1 (เดิม) | v2 (ปัจจุบัน) | เหตุผล |
|---|---|---|---|
| Normalize | log-ratio-to-max | **Percentile Rank** | ทนต่อ outlier: ข้อมูลจริงมีจุดที่เกิด 994 ครั้งปนกับจุดที่เกิด 3 ครั้ง วิธีที่อิงค่าสูงสุด (min-max, value/max) ถูกบิดจนใช้ไม่ได้ |
| ค่าอ้างอิง | คำนวณใหม่ทุกครั้งที่รัน | **ล็อกเป็นเวอร์ชัน ตามรอบเวลา** | กันคะแนน "ลอย" เมื่อข้อมูลใหม่เข้า — เปรียบเทียบข้ามช่วงเวลาได้ |
| น้ำหนักเกณฑ์ | 30/35/20/15 (คาลิเบรตเอง) | **เท่ากัน 4 × 25%** | PCA: PC1 อธิบายความแปรปรวนแค่ 40% ไม่มีปัจจัยร่วมเด่น → equal weighting ตาม OECD |
| เกณฑ์ลักษณะถนน | ยืมสัดส่วน conflict point ต่างประเทศ | **% เหตุที่เกิดบริเวณทางแยก/ทางโค้ง/ทางร่วม/ต่างระดับ** (ตั้งแต่ r5) | อ่านเข้าใจทันที ("30% ของเหตุเกิดที่ทางแยก/ทางโค้ง") แทน gc_score ทศนิยม 1.0151 ที่อธิบายยาก |
| แบ่งระดับ | mean±0.5SD + KSI override | **จุดตัดคงที่ 3 ชั้น** (≤40/≤60/>60) | อธิบายง่ายสำหรับนำเสนอ (v2568-r5) — เดิม r1/r2 ใช้ Jenks Natural Breaks (ยังเก็บฟังก์ชันไว้อ้างอิง ดู [ข้อจำกัด](#ข้อจำกัด-ควรระบุในรายงาน)) |
| เกณฑ์ความรุนแรง | EPDO 10:4:1 (ปรับสเกลเอง) | **มูลค่าความเสียหายจริง (บาท) ของ TDRI** | ตัวเลขไทย ตรวจสอบได้ อ้างอิงเป็นทางการ |

## ⚠️ หลักการสำคัญที่สุด: Fixed-Schedule Recalibration

**ห้าม**คำนวณค่าอ้างอิง (Percentile Rank, จุดตัดระดับ, FI weights) ใหม่แบบ dynamic
ทุกครั้งที่ระบบถูกเรียกใช้ — คะแนนของจุดที่ไม่ได้เปลี่ยนจริงจะลอยขึ้นลงทุกครั้งที่มี
อุบัติเหตุใหม่เข้าแม้เหตุเดียว สีบนแผนที่จะ "กะพริบ" โดยไม่มีเหตุผล

วิธีที่ถูกต้อง (ตามที่ implement ใน pipeline):

1. กำหนดรอบ recalibration ตายตัวล่วงหน้า — โปรเจกต์นี้ใช้ **ทุก 6 เดือน**
2. ถึงรอบจึงรัน `scripts/build_risk_points.py` ใหม่ แล้ว **ล็อกผลเป็นเวอร์ชัน**
   (ปัจจุบัน `v2568-r5` — snapshot ทุกรอบเก็บไว้ที่ `data/calibrations/`)
3. ระหว่างรอบ จุดใหม่ใช้ค่าอ้างอิงของรอบปัจจุบันไปก่อน
4. เก็บ log ทุกเวอร์ชันไว้ตรวจสอบย้อนหลัง (โฟลเดอร์ `data/calibrations/`)
5. หน้าเว็บ (เรียลไทม์) อ่านเฉพาะผลที่คำนวณไว้แล้ว — ท้ายหน้าแดชบอร์ดระบุเวอร์ชันกำกับไว้

ที่มาของหลักการ: Srinivasan & Carter (2011), *Development of Safety Performance
Functions for North Carolina*, UNC HSRC/NCDOT หน้า 49-51 — คำนวณ Calibration Factor
ตามรอบเวลาที่กำหนด ไม่ใช่แบบ dynamic
🔍 ประโยคยืนยันในเอกสาร: *"It will be beneficial for NCDOT to use the most recent years
of data to re-develop or re-calibrate the SPFs"*

> หมายเหตุ: รายงานฉบับนี้ใช้อ้างอิง**เฉพาะหลักการ recalibration ตามรอบเวลา**เท่านั้น
> ไม่ใช่แหล่งของสูตร normalize ใดๆ (เนื้อหาหน้า 11-13, 34 เป็น Negative Binomial
> Regression / SPF ที่ต้องใช้ AADT ซึ่งชุดข้อมูลนี้ไม่มี)

## ขั้นที่ 0: จับกลุ่มจุดเสี่ยงด้วย DBSCAN (eps 400 ม., min_samples 3)

พิกัดเหตุการณ์ที่จุดเดียวกันจริงกระจายตัวตามความคลาดเคลื่อน GPS จึงรวมเหตุที่เกิด
ใกล้กัน (รัศมี 400 ม. ครอบคลุมช่วงถนนหนึ่งช่วง) เป็นจุดเสี่ยงเดียวก่อนคำนวณทุกเกณฑ์

หลักการ DBSCAN: เหตุการณ์ที่มีเพื่อนบ้าน ≥ 3 รายในรัศมี 400 ม. เป็น **core point**
core ที่อยู่ในรัศมีถึงกัน "ลาม" รวมเป็นคลัสเตอร์เดียว (จับแนวยาวตามถนนได้),
เหตุที่อยู่ในรัศมีของ core แต่เพื่อนบ้านไม่ถึงเกณฑ์เป็น **border point** (นับรวมเข้าคลัสเตอร์),
ที่เหลือเป็น **noise** ไม่นับเป็นจุดเสี่ยง — จึงไม่ต้องกำหนดจำนวนกลุ่มล่วงหน้า
และเหตุกระจัดกระจายไม่ปนเปื้อนคะแนน

ผลรอบ v2568-r5: 4,460 เหตุการณ์มีพิกัด → **171 จุดเสี่ยง** (ครอบคลุม 3,784 เหตุการณ์,
noise 676) เกณฑ์ขั้นต่ำ 3 เหตุการณ์สอดคล้องนิยาม Black Spot ออสเตรเลีย
(เหตุบาดเจ็บ/เสียชีวิต ≥ 3 ครั้ง — ใช้เป็น sanity check เชิงคุณภาพ ไม่ใช่สูตรคำนวณ)

## วิธี Normalize ทุกเกณฑ์: Percentile Rank

```
Percentile Rank(x) = (อันดับเฉลี่ยของ x ในรอบข้อมูลปัจจุบัน ÷ จำนวนจุดทั้งหมด) × 100
อันดับเฉลี่ย = (จำนวนจุดที่ค่าน้อยกว่า x) + (จำนวนจุดที่ค่าเท่ากับ x + 1) ÷ 2
```

จัดการค่าเท่ากัน (tie) ด้วย average rank — pandas: `s.rank(pct=True, method='average') * 100`
ทำให้จุดที่มีค่าดิบเท่ากันได้คะแนนเท่ากันเสมอ (จำเป็นมากกับข้อมูลชุดนี้: 55 จุดมีอุบัติเหตุ
3 ครั้งเท่ากัน, 118 จุดมี conflict_pct = 0 เท่ากัน)

**เหตุผลที่ต้องใช้ Percentile Rank** — ทดสอบวิธีอื่นกับข้อมูลจริงแล้วพังทั้งหมด
เพราะข้อมูลมีจุดที่เกิด 994 ครั้ง ปนกับจุดที่เกิด 3 ครั้ง (ค่ามัธยฐานอยู่แค่ 4 ครั้ง):

| วิธี | ผลกับจุดที่มี 156 ครั้ง (ตาย 9) | ผลรวม |
|---|---|---|
| `value/max×100` | ได้ 15.7 คะแนน | outlier ดึงเพดาน |
| mean-anchored | 89.5% ของจุดได้ 0 คะแนน | 167/171 จุดเป็นระดับต่ำ |
| min-max | ได้ 15.4 คะแนน | **ไม่มีจุดไหนเป็นระดับสูงเลย** |
| ตารางเกณฑ์ (banded, ทดลองใน r4) | ได้ 25 เต็ม | คะแนนหยาบ เหลือ 12 ค่า 31 จุดคะแนนซ้ำกัน |
| **Percentile Rank** | **ได้ 98.2 คะแนน** ✅ | **ใช้อยู่ปัจจุบัน** |

- **แหล่งอ้างอิงวิธี:** Nardo et al. (2008), OECD/JRC Handbook, หัวข้อ Normalisation —
  *"Ranking is the simplest normalisation technique. This method is not affected by
  outliers and allows the performance of countries to be followed over time in terms
  of relative positions"*

## เกณฑ์ที่ 1: ความถี่อุบัติเหตุ (25%)

```
Frequency_Score(จุด) = PercentileRank(จำนวนอุบัติเหตุทั้งหมดที่จุดนั้น)   -> 0-100
```

บริบทเชิงคุณภาพ: จุดที่มีเหตุบาดเจ็บ/เสียชีวิต ≥ 3 ครั้ง/ปี เข้านิยาม Black Spot
(เอกสาร thaincd.com โดย อ.ณัฐพงศ์ บุญตอบ) — ใช้เทียบผลลัพธ์ ไม่ใช่สูตร

## เกณฑ์ที่ 2: มูลค่าความเสียหายทางเศรษฐกิจ (25%)

```
economic_loss(จุด) = ผู้เสียชีวิต×6,700,000 + ผู้บาดเจ็บสาหัส×2,000,000 + ผู้บาดเจ็บเล็กน้อย×58,000  (บาท)
EconomicLoss_Score(จุด) = PercentileRank(economic_loss)   -> 0-100
```

ต้นทุนต่อราย: มูลนิธิสถาบันวิจัยเพื่อการพัฒนาประเทศไทย (TDRI), *ความสูญเสียทางเศรษฐกิจ
ของอุบัติเหตุทางถนนของประเทศไทย ปีงบประมาณ พ.ศ. 2565* (เผยแพร่โดยกรมควบคุมโรค)

## เกณฑ์ที่ 3: Single vs Multiple Vehicle Crash Ratio (25%)

```
Single-Vehicle Ratio(จุด) %   = เหตุที่ "รถที่เกิดเหตุ" ≤ 1 / เหตุทั้งหมดของจุด × 100
Multiple-Vehicle Ratio(จุด) % = เหตุที่ "รถที่เกิดเหตุ" ≥ 2 / เหตุทั้งหมดของจุด × 100
SingleVehicle_Score(จุด) = PercentileRank(Single-Vehicle Ratio)   -> 0-100
```

**เก็บทั้งสองค่าคู่กัน** ในฐานข้อมูล/popup เพื่อวินิจฉัยรูปแบบปัญหา
(Single สูง → ปัญหาไหล่ทาง/ทางโค้ง · Multiple สูง → ปัญหาทางแยก/ความขัดแย้งจราจร)
แต่**สูตรคะแนนใช้เฉพาะ Single-Vehicle Ratio** เพราะสองค่ารวมกันเป็น 100% เสมอ
(สหสัมพันธ์ -1.00) ใส่ทั้งคู่ไม่เพิ่มข้อมูล

อ้างอิง: FHWA, *Roadway Departure Crashes* — มาตรการ *"Edge line and shoulder rumble
strips to reduce single vehicle run-off-road crashes"* (ที่มาของคำแนะนำเชิงวิศวกรรมใน popup)

## เกณฑ์ที่ 4: ลักษณะถนน (25%)

วัด **สัดส่วนเหตุที่เกิดบริเวณทางแยก/ทางโค้ง/ทางร่วม/ต่างระดับ** เทียบกับเหตุบนทางตรง
(แนวคิด conflict point — จุดที่กระแสจราจรตัดกัน)

จัดกลุ่มจากคอลัมน์ `บริเวณที่เกิดเหตุ`:

| ค่าในคอลัมน์ | กลุ่ม conflict | นับเข้าสูตรเกณฑ์ที่ 4? |
|---|---|---|
| ทางตรง (ทุกแบบ) | NCP — ไม่มีจุดที่กระแสจราจรตัดกัน (baseline) | ❌ |
| ทางโค้งกว้าง (ทุกแบบ), ทางร่วม, ทางเชื่อมทุกประเภท | Merging | ✅ |
| ทางแยกต่างระดับ/Ramps, จุดกลับรถต่างระดับ | Diverging | ✅ |
| ทางสามแยก (Y), ทางสี่แยก | Crossing | ✅ |
| อื่นๆ / ไม่มีข้อมูล | fallback NCP อย่างระมัดระวัง | ❌ |

```
conflict_pct(จุด) = เหตุที่เกิดบริเวณทางแยก/ทางโค้ง/ทางร่วม/ต่างระดับ / เหตุทั้งหมดของจุด × 100
Geometry_Score(จุด) = PercentileRank(conflict_pct)   -> 0-100
```

อ้างอิงแนวคิด: TxDOT Design Manual §11.3.7.1 — *"Conflict points are a high-level,
simple measure of the potential collision"* — ยิ่งจุดหนึ่งมีสัดส่วนเหตุที่เกิดบริเวณ
ทางแยก/ทางโค้งมาก ยิ่งสะท้อนว่าเป็นปัญหาเชิงกายภาพของถนน ไม่ใช่เหตุสุ่มบนทางตรง

### FI Rate ของข้อมูลไทยเอง (ข้อมูลประกอบ — ไม่อยู่ในสูตรคะแนนแล้ว)

รอบ r1–r3 ใช้ค่านี้ถ่วงน้ำหนักเป็น `gc_score` ตั้งแต่ r5 เก็บไว้เป็นหลักฐานสนับสนุน
ว่า "ทางแยก/ทางโค้ง = อันตรายกว่าทางตรงจริงในบริบทไทย" (FI = เหตุที่มีผู้บาดเจ็บ/เสียชีวิต ≥ 1 ราย):

```
NCP:       n=3,948  FI 42.1%  → weight 1.000 (baseline)
Merging:   n=230    FI 42.6%  → weight 1.011
Diverging: n=54     FI 35.2%  → weight 0.835   ⚠️ ตัวอย่างน้อย ระวังการตีความ
Crossing:  n=35     FI 57.1%  → weight 1.356
```

ลำดับความรุนแรงสอดคล้อง VDOT — *"merging and diverging conflict points ... are
associated with less severe crash types than crossing conflict points"*
(ผลจริง: Crossing 1.356 > Merging 1.011 > Diverging 0.835)
· `gc_score`/`geom_group` ยังอยู่ใน GeoJSON เป็นข้อมูลประกอบ

## การรวมคะแนนและจัดระดับ

```
Risk Score(จุด) = 0.25×Frequency + 0.25×EconomicLoss + 0.25×SingleVehicle + 0.25×Geometry
                  (ทุกเกณฑ์เป็น Percentile Rank 0-100 -> Risk Score เต็ม 100)
```

**เหตุผลน้ำหนักเท่ากัน:** PCA พบ PC1 อธิบายความแปรปรวนเพียง ~40% และ loading ของ
Single-Vehicle/Geometric Complexity เป็นลบ — ไม่มีปัจจัยร่วมเด่นเดียว สอดคล้องการออกแบบ
ให้ 4 เกณฑ์อิสระต่อกัน (Spearman ทุกคู่ < 0.30) → ใช้ equal weighting ตาม OECD Handbook
(อ้าง Greco et al.: วิธีที่ใช้แพร่หลายที่สุดเมื่อไม่มีทฤษฎีกำหนดน้ำหนัก)

**แบ่ง 3 ระดับด้วยจุดตัดคงที่** (ตั้งแต่รอบ v2568-r5): ≤40 ต่ำ, 40–60 ปานกลาง, >60 สูง
เลือกใช้เลขกลมเพื่อให้อธิบาย/นำเสนอง่าย ทดแทนวิธีเดิม (v2568-r1, r2) ที่ใช้
**Jenks Natural Breaks** (Fisher's optimal partition — implement เป็น dynamic
programming ในสคริปต์, ฟังก์ชัน `jenks_breaks()` ยังเก็บไว้พร้อม self-test) ซึ่งเป็น
วิธีเดียวกับที่ CDC ใช้: *"clusters data into groups that minimize the within-group
variance and maximize the between-group variance"*

**ข้อแลกเปลี่ยนของการเปลี่ยนวิธี:** จุดตัดคงที่ 40/60 อธิบายง่ายกว่ามาก แต่ไม่มีหลักฐาน
ทางสถิติรองรับตัวเลขเจาะจงนี้ (ต่างจาก Jenks ที่ตอบได้ว่าจุดตัดมาจากการลดความแปรปรวน
ภายในกลุ่ม) — ตรวจสอบแล้วว่าผลลัพธ์ใกล้เคียงกับ Jenks เดิม (r2: ต่ำ 53/กลาง 78/สูง 40
เทียบ r3: ต่ำ 45/กลาง 86/สูง 40 จุด, เปลี่ยนระดับ 8 จุดจาก 171 จุด)

ผลรอบ **v2568-r5** (ค่าคงที่ ไม่ต้องคำนวณใหม่แม้ Risk Score เปลี่ยนตามข้อมูล):

| ระดับ | ช่วง Risk Score | จำนวนจุด |
|---|---|---|
| 🟢 ต่ำ | ≤ 40 | 45 |
| 🟠 ปานกลาง | 40 – 60 | 85 |
| 🔴 สูง | > 60 | 41 |

Risk Score จริงกระจายอยู่ในช่วง 21.4 – 79.4

## ข้อจำกัด (ควรระบุในรายงาน)

1. **Percentile Rank เป็นคะแนนเชิงเปรียบเทียบภายในรอบ** — คะแนน 90 หมายถึงอยู่ใน 10% แรก
   ของรอบนั้น ไม่ใช่ค่าความเสี่ยงสัมบูรณ์ เทียบข้ามรอบ calibration ตรงๆ ไม่ได้
2. **จุดตัดระดับ 40/60 เป็นการเลือกเชิงนำเสนอ** (ตั้งแต่ r3) ไม่ได้คำนวณจากการกระจาย
   ของข้อมูลเหมือน Jenks Natural Breaks ที่ใช้ในรอบ r1–r2 — ถ้าถูกถามที่มา ต้องตอบตรงๆ
3. 69% ของจุดมี `conflict_pct` = 0 (ทางตรงล้วน) ทุกจุดจึงได้ Percentile เท่ากันที่ 34.8
   เกณฑ์ที่ 4 แยกความต่างได้น้อยในทางปฏิบัติ — เป็นลักษณะข้อมูลต้นทาง ไม่ใช่ข้อบกพร่องของสูตร
4. เกณฑ์ Diverging มีตัวอย่างเพียง 54 เหตุการณ์ — FI weight 0.835 ไม่แน่นอนสูง
   (เป็นข้อมูลประกอบ ไม่อยู่ในสูตรคะแนนแล้วตั้งแต่ r5)
5. ข้อมูล 167 เหตุการณ์ (3.6%) ไม่มีพิกัด ถูกตัดจากการจับกลุ่ม แต่ยังใช้ประมาณ FI Rate
6. เหตุการณ์ noise 676 รายไม่เข้าจุดเสี่ยงใด — ธรรมชาติของ DBSCAN ควรรายงานควบคู่เสมอ
7. `รถที่เกิดเหตุ` นับจำนวนคัน ไม่แยกประเภทคู่กรณี (รถ-คนเดินเท้า นับ 1 คัน เข้ากลุ่ม Single)

## รายการอ้างอิงทั้งหมด

1. **thaincd.com** (กรมควบคุมโรค), "จุดเสี่ยง/จุดอันตรายบนถนน" โดย อ.ณัฐพงศ์ บุญตอบ —
   นิยาม Black Spot ออสเตรเลีย (≥3 ครั้ง/ปี ช่วง 3-5 ปี)
   <http://www.thaincd.com/document/file/download/powerpoint/4.1Black_Spot_Treatment_โดย_อ.ณัฐพงศ์_บุญตอบ.pdf>
2. **TDRI**, "ความสูญเสียทางเศรษฐกิจของอุบัติเหตุทางถนนของประเทศไทย ปีงบประมาณ พ.ศ. 2565"
   (เผยแพร่โดยกรมควบคุมโรค กระทรวงสาธารณสุข) — ต้นทุน 6.7 ล้าน / 2 ล้าน / 58,000 บาทต่อราย
   <https://ddc.moph.go.th/uploads/publish/1587620240712091713.pdf>
3. **FHWA**, "Roadway Departure Crashes" — Single-vehicle run-off-road + มาตรการแก้ไข
   <https://highways.dot.gov/safety/other/roadway-departure-crashes>
4. **TxDOT** Design Manual §11.3.7.1 "Conflict Points"
   <https://www.txdot.gov/manuals/des/tsp/chapter-11-interchange-analysis/11-3-interchange-configuration-evaluation--ice-/11-3-7-stage-2-safety-performance-and-ice/11-3-7-1-conflict-points.html>
5. **VDOT**, "Continuous Green-T Intersection" — ลำดับความรุนแรง crossing > merging/diverging
   <https://www.vdot.virginia.gov/about/our-system/highways/innovative-intersections/continuous-green-t/>
6. **ITRE, NC State University**, "New Conflict Point Crash Prediction Method" (2020) —
   Weighted Conflict Points (VJuST) — precedent เชิงวิธีการ
   <https://connect.ncdot.gov/projects/research/RNAProjDocs/Conflict%20Point%20Crash%20Prediction%20Webinar%2009232020.pdf>
7. **Nardo, M. et al. (2008)**, "Handbook on Constructing Composite Indicators," OECD/JRC —
   Ranking normalisation + Equal weighting
   <https://www.unescap.org/sites/default/files/JRC-OECD_Handbook%20Composite%20Indicators.pdf>
8. **Jenks, G.F. (1967)**, "The Data Model Concept in Statistical Mapping," Intl. Yearbook of
   Cartography 7:186-190 — วิธีที่ CDC ใช้ <https://www.cdc.gov/nchs/hus/sources-definitions/jenks-natural-breaks.htm>
9. **Srinivasan, R., & Carter, D. (2011)**, "Development of Safety Performance Functions for
   North Carolina," UNC HSRC/NCDOT หน้า 49-51 — เฉพาะหลักการ Fixed-Schedule Recalibration
   <https://connect.ncdot.gov/projects/research/RNAProjDocs/2010-09FinalReport.pdf>
10. **ข้อมูลอุบัติเหตุ**: `data/accident2025_1.xlsx` — MOT Data Catalog ปี 2568,
    6 จังหวัด 4,627 เหตุการณ์ — แหล่งคำนวณน้ำหนัก FI Rate ของเกณฑ์ที่ 4 โดยตรง
    <https://datagov.mot.go.th/dataset/roadaccident>
