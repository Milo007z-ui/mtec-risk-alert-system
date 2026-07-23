# ระบบแจ้งเตือนจุดเสี่ยงอุบัติเหตุ — กรุงเทพฯ และปริมณฑล

เว็บแอปแผนที่ (Leaflet + OpenStreetMap) ติดตามตำแหน่ง GPS แบบเรียลไทม์
เมื่อเข้าใกล้จุดเสี่ยงอุบัติเหตุในระยะ **500 เมตร** จะแจ้งเตือนด้วย**เสียงพูดภาษาไทย**
(Web Speech API) พร้อมแบนเนอร์บนจอ

ข้อมูลจุดเสี่ยงมาจากสถิติอุบัติเหตุปี 2568 ของ **MOT Data Catalog** (datagov.mot.go.th)
นำมาจัดกลุ่มด้วย DBSCAN (รัศมี 400 ม. ขั้นต่ำ 3 เหตุการณ์) ครอบคลุม 6 จังหวัด:
กรุงเทพมหานคร นนทบุรี ปทุมธานี สมุทรปราการ นครปฐม สมุทรสาคร

## วิธีใช้งาน

```bash
# 1) (ทำครั้งแรก หรือเมื่ออยากอัปเดตข้อมูล) สร้างไฟล์จุดเสี่ยง
pip install requests scikit-learn numpy
py scripts/build_risk_points.py     # ได้ data/risk_points_bkk_metro.geojson

# 2) เปิด local server ที่โฟลเดอร์โปรเจกต์
py -m http.server 8123

# 3) เปิดเบราว์เซอร์
#    http://localhost:8123          <- ใช้งานจริง (GPS จริง)
#    http://localhost:8123/?mock=1  <- โหมดจำลอง: ขับรถผ่านจุดเสี่ยงอัตโนมัติ
```

กดปุ่ม **"เริ่มใช้งาน"** หนึ่งครั้งเพื่อปลดล็อกเสียงและเริ่มติดตามตำแหน่ง
(เบราว์เซอร์บังคับว่าเสียงต้องเริ่มจากการกดของผู้ใช้)

> **ทดสอบบนมือถือจริง:** Geolocation ใช้ได้เฉพาะ HTTPS หรือ localhost —
> deploy ขึ้น GitHub Pages (ได้ HTTPS ฟรี) หรือใช้ ngrok ชั่วคราว

## โครงสร้างโปรเจกต์

```
├── index.html                  # หน้าเดียวจบ โหลด Leaflet จาก CDN
├── css/style.css
├── js/
│   ├── distance.js             # Haversine + bounding box (ไม่แตะ DOM, test ได้ใน Node)
│   ├── riskpoints.js           # โหลด GeoJSON + วาด marker สีตามระดับความเสี่ยง
│   ├── map.js                  # ตั้งค่าแผนที่ + marker ตำแหน่งผู้ใช้ + auto-pan
│   ├── gps.js                  # watchPosition + โหมดจำลอง (?mock=1)
│   ├── alert.js                # ตรวจรัศมี 500 ม. + cooldown กันเตือนซ้ำ
│   ├── tts.js                  # เสียงพูดไทย th-TH + fallback เป็นแบนเนอร์
│   └── app.js                  # จุดเริ่มต้น ประกอบทุกโมดูล
├── data/risk_points_bkk_metro.geojson   # จุดเสี่ยง 108 จุด (สร้างจากสคริปต์)
├── scripts/build_risk_points.py         # ดึงข้อมูล MOT -> DBSCAN -> GeoJSON
├── api/server.py                        # REST API (FastAPI) ให้อุปกรณ์ดึงข้อมูลจุดเสี่ยง
├── device/pi_alert_client.py            # ไคลเอนต์ Raspberry Pi: GPS -> เรียก API -> พูดเตือน
└── tests/distance.test.js               # unit test: node tests/distance.test.js
```

## REST API สำหรับอุปกรณ์ (`api/server.py`)

เซิร์ฟเวอร์ FastAPI แจกจ่ายข้อมูลจุดเสี่ยงให้อุปกรณ์ภายนอก (Raspberry Pi, มือถือ ฯลฯ)
และเสิร์ฟหน้าเว็บเดิมไปพร้อมกัน — ใช้เซิร์ฟเวอร์เดียวแทน `py -m http.server` ได้เลย

```bash
pip install -r api/requirements.txt
python -m uvicorn api.server:app --host 0.0.0.0 --port 8000
# เว็บ:      http://localhost:8000
# API docs:  http://localhost:8000/docs   (Swagger UI อัตโนมัติ)
```

| Endpoint | ความหมาย |
|---|---|
| `GET /api/health` | สถานะเซิร์ฟเวอร์ + จำนวนจุดเสี่ยง |
| `GET /api/risk-points` | ทุกจุด กรองได้: `?level=high` `?province=นนทบุรี` `?min_score=55` |
| `GET /api/risk-points/nearby?lat=..&lng=..&radius=600` | จุดในรัศมี เรียงใกล้→ไกล พร้อม `distance_m` และ **`alert_message`** (ข้อความเตือนไทยสำเร็จรูป สร้างจากกติกา Dynamic Alert เดียวกับเว็บ) |
| `GET /api/risk-points/{id}` | รายละเอียดจุดเดียว + ปัจจัยเสี่ยง |

## ไคลเอนต์ Raspberry Pi (`device/pi_alert_client.py`)

สคริปต์สำหรับติดบนรถ (เช่น รถเมล์): อ่านพิกัด GPS ของรถ ถาม API ว่ามีจุดเสี่ยงใกล้ๆ ไหม
เมื่อเข้าใกล้กว่า 500 ม. จะพูดเตือนคนขับเป็นภาษาไทยผ่านลำโพง (espeak-ng)
ใช้กติกา cooldown ชุดเดียวกับหน้าเว็บ ใช้เฉพาะ Python standard library ไม่ต้อง pip install

```bash
# บน Raspberry Pi (ต่อ GPS USB + ลำโพง)
sudo apt install gpsd espeak-ng
python3 device/pi_alert_client.py --api http://<IP-เซิร์ฟเวอร์>:8000 --gpsd

# ทดสอบโดยไม่มี GPS: พิกัดคงที่ หรือจำลองเส้นทางจากไฟล์ (บรรทัดละ lat,lng)
python3 device/pi_alert_client.py --api http://localhost:8000 --test 13.665 100.534
python3 device/pi_alert_client.py --api http://localhost:8000 --route route.csv
```

## กติกาการแจ้งเตือน (ปรับได้ใน `js/alert.js`)

| ค่า | ความหมาย | ค่าเริ่มต้น |
|---|---|---|
| `ALERT_RADIUS_M` | รัศมีที่เริ่มเตือน | 500 ม. |
| `EXIT_RADIUS_M` | ต้องออกไกลกว่านี้ถึงจะ "เตือนซ้ำได้เมื่อกลับเข้ามา" (hysteresis) | 600 ม. |
| `REALERT_MS` | วนอยู่ในรัศมีเดิมนานเท่านี้ถึงเตือนซ้ำ | 5 นาที |

## Road Risk Assessment Model (คะแนนเต็ม 100)

แต่ละจุดเสี่ยงได้ `risk_score` จาก 4 ปัจจัย (คำนวณใน `scripts/build_risk_points.py`):

| ปัจจัย | น้ำหนัก | วิธีคิด |
|---|---|---|
| Accident Frequency | 30 | จำนวนอุบัติเหตุ สเกล log อิ่มตัวที่ 50 ครั้ง/ปี (การแจกแจงหางยาว) |
| Accident Severity | 35 | EPDO = เสียชีวิต×10 + สาหัส×4 + เล็กน้อย×1 สเกล log อิ่มตัวที่ 120 |
| Road Geometry | 20 | ค่าเฉลี่ยน้ำหนักอันตรายของ "บริเวณที่เกิดเหตุ" ทุกเหตุการณ์ในกลุ่ม (ทางแยก 1.0 > จุดกลับรถ 0.9 > ทางโค้ง 0.8-0.9 > ทางตรง 0.3) ตามจำนวน conflict points |
| Speed Limit | 15 | (ความเร็วจำกัด/120)² — พลังงานจลน์แปรผันตามความเร็วยกกำลังสอง; อนุมานความเร็วจากประเภทสายทาง (ทางพิเศษ 100 / ทางหลวง 90 / ชนบท 80) |

**การแบ่งระดับ** (คาลิเบรตจากการกระจายจริง: min 27, มัธยฐาน 45.8, max 83.5):

- 🟥 **สูง** — score ≥ 55 (ควอร์ไทล์บน) *หรือ* เสียชีวิต ≥ 2 ราย (KSI override)
- 🟧 **ปานกลาง** — score ≥ 40 *หรือ* เสียชีวิต ≥ 1 ราย
- 🟩 **ต่ำ** — ที่เหลือ

เหตุผลไม่ใช้ 70/40 ตายตัว: คะแนนจริงเกาะกลุ่ม 27-83 การตัดที่ 70 จะทำให้แทบไม่มีจุด "สูง"
เลย จึงตัดที่ควอร์ไทล์บน (~55) เพื่อคุมสัดส่วนจุดสีแดงไว้ ~25% ลด alert fatigue
และมี safety override ตามหลัก KSI ไม่ให้จุดที่เคยมีผู้เสียชีวิตถูกจัดระดับต่ำ

**Dynamic Alert** (`js/riskrules.js`): ข้อความเตือนประกอบจากกติกาตามเงื่อนไขจริงของจุด
เช่น ทางแยก/ทางโค้ง/จุดกลับรถ/ถนนความเร็วสูง/ประวัติผู้เสียชีวิต/ชนท้ายบ่อย
พร้อมคำแนะนำการขับขี่เฉพาะกรณี — ใช้ร่วมกันทั้งเสียงพูด แบนเนอร์ และ popup

## การทดสอบ

```bash
node tests/distance.test.js     # unit test ระยะทาง (9 เคส)
```

ทดสอบรวมทั้งระบบ: เปิด `http://localhost:8123/?mock=1` — ระบบจะวาดเส้นทางจำลอง
แล้วขับตามถนนเส้นเดียวผ่านจุดเสี่ยงจริงติดกัน 4–5 จุด (แนวเหนือ ถ.รามอินทรา-บางพลี)
ต้องได้ยินเสียงเตือน **หนึ่งครั้งต่อจุด** ตอนเข้าเขต 500 ม. และไม่เตือนจุดเดิมซ้ำ
จนกว่าจะออกนอกเขตแล้วกลับเข้ามาใหม่ ปรับจังหวะช้า/เร็วได้ด้วย `?mock=1&mockpace=12`
(วินาทีต่อกิโลเมตร — ค่ามากยิ่งช้า)
