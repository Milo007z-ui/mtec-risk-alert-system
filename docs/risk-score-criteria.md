# เกณฑ์การให้คะแนนจุดเสี่ยง — โมเดล v2 (4 เกณฑ์ × 25%, Percentile Rank + Jenks)

เอกสารอ้างอิงประกอบโมเดลใน `scripts/build_risk_points.py`
(โมเดล v1 แบบ log-norm 30/35/20/15 ดูได้จาก git history — ถูกแทนที่เพราะปัญหา score drift)

## สิ่งที่เปลี่ยนจาก v1 และเหตุผล

| ประเด็น | v1 (เดิม) | v2 (ปัจจุบัน) | เหตุผล |
|---|---|---|---|
| Normalize | log-ratio-to-max | **Percentile Rank** | ทดสอบจริง: เพิ่ม outlier n=100 เข้าไป คะแนนจุด freq=10 เปลี่ยนแค่ 0.3 แต้ม (95.0→94.7) เทียบกับ log-ratio ที่เปลี่ยน 6.76 แต้ม (22.35→15.59) |
| ค่าอ้างอิง | คำนวณใหม่ทุกครั้งที่รัน | **ล็อกเป็นเวอร์ชัน ตามรอบเวลา** | กันคะแนน "ลอย" เมื่อข้อมูลใหม่เข้า — เปรียบเทียบข้ามช่วงเวลาได้ |
| น้ำหนักเกณฑ์ | 30/35/20/15 (คาลิเบรตเอง) | **เท่ากัน 4 × 25%** | PCA: PC1 อธิบายความแปรปรวนแค่ 40% ไม่มีปัจจัยร่วมเด่น → equal weighting ตาม OECD |
| น้ำหนักลักษณะถนน | ยืมสัดส่วน conflict point ต่างประเทศ | **FI Rate จากข้อมูลไทยเอง** | วัดจากความรุนแรงจริงในไฟล์ ไม่ใช่ทฤษฎีต่างบริบท |
| แบ่งระดับ | mean±0.5SD + KSI override | **Jenks Natural Breaks 3 ชั้น** | หาจุดตัดที่ลดความแปรปรวนภายในชั้น เป็นวิธีที่ CDC ใช้จริง |
| เกณฑ์ความรุนแรง | EPDO 10:4:1 (ปรับสเกลเอง) | **มูลค่าความเสียหายจริง (บาท) ของ TDRI** | ตัวเลขไทย ตรวจสอบได้ อ้างอิงเป็นทางการ |

## ⚠️ หลักการสำคัญที่สุด: Fixed-Schedule Recalibration

**ห้าม**คำนวณค่าอ้างอิง (percentile rank, Jenks breaks, FI weights) ใหม่แบบ dynamic
ทุกครั้งที่ระบบถูกเรียกใช้ — คะแนนของจุดที่ไม่ได้เปลี่ยนจริงจะลอยขึ้นลงทุกครั้งที่มี
อุบัติเหตุใหม่เข้าแม้เหตุเดียว สีบนแผนที่จะ "กะพริบ" โดยไม่มีเหตุผล

วิธีที่ถูกต้อง (ตามที่ implement ใน pipeline):

1. กำหนดรอบ recalibration ตายตัวล่วงหน้า — โปรเจกต์นี้ใช้ **ทุก 6 เดือน**
2. ถึงรอบจึงรัน `scripts/build_risk_points.py` ใหม่ แล้ว **ล็อกผลเป็นเวอร์ชัน**
   (ปัจจุบัน `v2568-r1` — snapshot อยู่ที่ `data/calibrations/v2568-r1.json`)
3. ระหว่างรอบ จุดใหม่ใช้ค่าอ้างอิงของรอบปัจจุบันไปก่อน
4. เก็บ log ทุกเวอร์ชันไว้ตรวจสอบย้อนหลัง (โฟลเดอร์ `data/calibrations/`)
5. หน้าเว็บ (เรียลไทม์) อ่านเฉพาะผลที่คำนวณไว้แล้ว — popup/แดชบอร์ดระบุเวอร์ชันเสมอ

ที่มาของหลักการ: Srinivasan & Carter (2011), *Development of Safety Performance
Functions for North Carolina*, UNC HSRC/NCDOT หน้า 49-51 — คำนวณ Calibration Factor
ตามรอบเวลาที่กำหนด ไม่ใช่แบบ dynamic
🔍 ประโยคยืนยันในเอกสาร: *"It will be beneficial for NCDOT to use the most recent years
of data to re-develop or re-calibrate the SPFs"*

> หมายเหตุ: รายงานฉบับนี้ใช้อ้างอิง**เฉพาะหลักการ recalibration ตามรอบเวลา**เท่านั้น
> ไม่ใช่แหล่งของสูตร normalize ใดๆ (เนื้อหาหน้า 11-13, 34 เป็น Negative Binomial
> Regression / SPF ที่ต้องใช้ AADT ซึ่งชุดข้อมูลนี้ไม่มี)

## ขั้นที่ 0: จับกลุ่มจุดเสี่ยงด้วย DBSCAN (eps 150 ม., min_samples 3)

พิกัดเหตุการณ์ที่จุดเดียวกันจริงกระจายตัวตามความคลาดเคลื่อน GPS จึงรวมเหตุที่เกิด
ใกล้กัน (สเปกกำหนด buffer 100-150 ม.) เป็นจุดเสี่ยงเดียวก่อนคำนวณทุกเกณฑ์

หลักการ DBSCAN: เหตุการณ์ที่มีเพื่อนบ้าน ≥ 3 รายในรัศมี 150 ม. เป็น **core point**
core ที่อยู่ในรัศมีถึงกัน "ลาม" รวมเป็นคลัสเตอร์เดียว (จับแนวยาวตามถนนได้),
เหตุที่อยู่ในรัศมีของ core แต่เพื่อนบ้านไม่ถึงเกณฑ์เป็น **border point** (นับรวมเข้าคลัสเตอร์),
ที่เหลือเป็น **noise** ไม่นับเป็นจุดเสี่ยง — จึงไม่ต้องกำหนดจำนวนกลุ่มล่วงหน้า
และเหตุกระจัดกระจายไม่ปนเปื้อนคะแนน

ผลรอบ v2568-r1: 4,460 เหตุการณ์มีพิกัด → **290 จุดเสี่ยง** (ครอบคลุม 3,349 เหตุการณ์,
noise 1,111) เกณฑ์ขั้นต่ำ 3 เหตุการณ์สอดคล้องนิยาม Black Spot ออสเตรเลีย
(เหตุบาดเจ็บ/เสียชีวิต ≥ 3 ครั้ง — ใช้เป็น sanity check เชิงคุณภาพ ไม่ใช่สูตรคำนวณ)

## วิธี Normalize ทุกเกณฑ์: Percentile Rank

```
PercentileRank(x) = (จำนวนจุดที่มีค่า ≤ x ในรอบข้อมูลอ้างอิงปัจจุบัน) / (จำนวนจุดทั้งหมดในรอบ) × 100
```

จัดการค่าเท่ากัน (tie) ด้วย average rank — pandas: `s.rank(pct=True, method='average') * 100`

- **แหล่งอ้างอิงวิธี:** Nardo et al. (2008), OECD/JRC Handbook, หัวข้อ Normalisation —
  *"Ranking is the simplest normalisation technique. This method is not affected by
  outliers and allows the performance of countries to be followed over time in terms
  of relative positions"*
- **เหตุผลไม่ใช้ min-max/log-ratio:** ไวต่อ outlier (ผลทดสอบในตารางบนสุด)

## เกณฑ์ที่ 1: ความถี่อุบัติเหตุ (25%)

```
Frequency_Score(จุด) = PercentileRank(จำนวนอุบัติเหตุทั้งหมดที่จุดนั้นในรอบข้อมูล)
```

บริบทเชิงคุณภาพ: จุดที่มีเหตุบาดเจ็บ/เสียชีวิต ≥ 3 ครั้ง/ปี เข้านิยาม Black Spot
(เอกสาร thaincd.com โดย อ.ณัฐพงศ์ บุญตอบ) — ใช้เทียบผลลัพธ์ ไม่ใช่สูตร

## เกณฑ์ที่ 2: มูลค่าความเสียหายทางเศรษฐกิจ (25%)

```
economic_loss(จุด) = ผู้เสียชีวิต×6,700,000 + ผู้บาดเจ็บสาหัส×2,000,000 + ผู้บาดเจ็บเล็กน้อย×58,000  (บาท)
EconomicLoss_Score(จุด) = PercentileRank(economic_loss)
```

ต้นทุนต่อราย: มูลนิธิสถาบันวิจัยเพื่อการพัฒนาประเทศไทย (TDRI), *ความสูญเสียทางเศรษฐกิจ
ของอุบัติเหตุทางถนนของประเทศไทย ปีงบประมาณ พ.ศ. 2565* (เผยแพร่โดยกรมควบคุมโรค)

## เกณฑ์ที่ 3: Single vs Multiple Vehicle Crash Ratio (25%)

```
Single-Vehicle Ratio(จุด) %   = เหตุที่ "รถที่เกิดเหตุ" ≤ 1 / เหตุทั้งหมดของจุด × 100
Multiple-Vehicle Ratio(จุด) % = เหตุที่ "รถที่เกิดเหตุ" ≥ 2 / เหตุทั้งหมดของจุด × 100
SingleVehicle_Score(จุด) = PercentileRank(Single-Vehicle Ratio)
```

**เก็บทั้งสองค่าคู่กัน** ในฐานข้อมูล/popup เพื่อวินิจฉัยรูปแบบปัญหา
(Single สูง → ปัญหาไหล่ทาง/ทางโค้ง · Multiple สูง → ปัญหาทางแยก/ความขัดแย้งจราจร)
แต่**สูตรคะแนนใช้เฉพาะ Single-Vehicle Ratio** เพราะสองค่ารวมกันเป็น 100% เสมอ
(สหสัมพันธ์ -1.00) ใส่ทั้งคู่ไม่เพิ่มข้อมูล

อ้างอิง: FHWA, *Roadway Departure Crashes* — มาตรการ *"Edge line and shoulder rumble
strips to reduce single vehicle run-off-road crashes"* (ที่มาของคำแนะนำเชิงวิศวกรรมใน popup)

## เกณฑ์ที่ 4: Geometric Complexity Ratio (25%)

จัดกลุ่มจากคอลัมน์ `บริเวณที่เกิดเหตุ`:

| ค่าในคอลัมน์ | กลุ่ม conflict |
|---|---|
| ทางตรง (ทุกแบบ) | NCP — ไม่มีจุดตัดกระแส (baseline) |
| ทางโค้งกว้าง (ทุกแบบ), ทางร่วม, ทางเชื่อมทุกประเภท | Merging |
| ทางแยกต่างระดับ/Ramps, จุดกลับรถต่างระดับ | Diverging |
| ทางสามแยก (Y), ทางสี่แยก | Crossing |
| อื่นๆ / ไม่มีข้อมูล | fallback NCP (1.000) อย่างระมัดระวัง และไม่ใช้ประมาณ FI Rate |

**น้ำหนักคำนวณจาก FI Rate ของข้อมูลในไฟล์เอง** (FI = เหตุที่มีผู้บาดเจ็บ/เสียชีวิต ≥ 1 ราย)
— ผลจริงรอบ v2568-r1 ตรงกับค่าอ้างอิงในสเปก:

```
NCP:       n=3,948  FI 42.1%  → weight 1.000 (baseline)
Merging:   n=230    FI 42.6%  → weight 1.011
Diverging: n=54     FI 35.2%  → weight 0.835   ⚠️ ตัวอย่างน้อย ระวังการตีความ
Crossing:  n=35     FI 57.1%  → weight 1.356

gc_score(จุด) = ค่าเฉลี่ยน้ำหนักของทุกเหตุที่จุดนั้น
GeometricComplexity_Score(จุด) = PercentileRank(gc_score)
```

อ้างอิงแนวคิด: TxDOT Design Manual §11.3.7.1 — *"Conflict points are a high-level,
simple measure of the potential collision"* · ลำดับความรุนแรง: VDOT — *"merging and
diverging conflict points ... are associated with less severe crash types than crossing
conflict points"* (สอดคล้องผลจริง: Crossing 1.356 > Merging 1.011 > Diverging 0.835)
· วิธีถ่วงน้ำหนัก: ITRE/NCSU 2020 (VJuST Weighted Conflict Points — precedent เชิงวิธีการเท่านั้น)

## การรวมคะแนนและจัดระดับ

```
Risk Score(จุด) = 0.25×Frequency + 0.25×EconomicLoss + 0.25×SingleVehicle + 0.25×GeometricComplexity
```

**เหตุผลน้ำหนักเท่ากัน:** PCA พบ PC1 อธิบายความแปรปรวนเพียง ~40% และ loading ของ
Single-Vehicle/Geometric Complexity เป็นลบ — ไม่มีปัจจัยร่วมเด่นเดียว สอดคล้องการออกแบบ
ให้ 4 เกณฑ์อิสระต่อกัน (Spearman ทุกคู่ < 0.30) → ใช้ equal weighting ตาม OECD Handbook
(อ้าง Greco et al.: วิธีที่ใช้แพร่หลายที่สุดเมื่อไม่มีทฤษฎีกำหนดน้ำหนัก)

**แบ่ง 3 ระดับด้วย Jenks Natural Breaks** (Fisher's optimal partition — implement
เป็น dynamic programming ในสคริปต์ ไม่พึ่งไลบรารีเพิ่ม) — วิธีเดียวกับที่ CDC ใช้:
*"clusters data into groups that minimize the within-group variance and maximize
the between-group variance"*

ผลรอบ **v2568-r1** (คำนวณจากข้อมูลจริง แล้วล็อกไว้ — ห้าม hardcode ถาวร
รอบถัดไปต้องคำนวณใหม่ตามตาราง):

| ระดับ | ช่วง Risk Score | จำนวนจุด |
|---|---|---|
| 🟢 ต่ำ | ≤ 41.9 | 97 |
| 🟠 ปานกลาง | 41.9 – 60.3 | 117 |
| 🔴 สูง | > 60.3 | 76 |

## ข้อจำกัด (ควรระบุในรายงาน)

1. เกณฑ์ Diverging มีตัวอย่างเพียง 54 เหตุการณ์ — น้ำหนัก 0.835 มีความไม่แน่นอนสูง
2. ข้อมูล 167 เหตุการณ์ไม่มีพิกัด (คิดเป็น 3.6%) ถูกตัดจากการจับกลุ่ม
   แต่ยังใช้ประมาณ FI Rate (ความรุนแรงเป็นข้อมูลจริงแม้ไม่มีพิกัด)
3. เหตุการณ์ noise 1,111 รายไม่เข้าจุดเสี่ยงใด — เป็นธรรมชาติของ DBSCAN
   (เหตุกระจัดกระจายไม่ถือเป็น hotspot) ควรรายงานตัวเลขนี้ควบคู่เสมอ
4. `รถที่เกิดเหตุ` นับจำนวนคัน ไม่แยกประเภทคู่กรณี (เช่น รถ-คนเดินเท้า นับเป็น 1 คัน
   จึงเข้ากลุ่ม Single)
5. Percentile Rank เป็นคะแนน "เชิงเปรียบเทียบภายในรอบ" — คะแนน 90 หมายถึงอยู่ใน
   10% แรกของรอบนั้น ไม่ใช่ค่าความเสี่ยงสัมบูรณ์

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
