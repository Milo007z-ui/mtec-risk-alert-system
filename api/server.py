"""
server.py — REST API สำหรับให้อุปกรณ์ (เช่น Raspberry Pi บนรถเมล์) ดึงข้อมูลจุดเสี่ยง

Endpoints:
  GET /api/health                      สถานะเซิร์ฟเวอร์ + จำนวนจุดเสี่ยง
  GET /api/risk-points                 จุดเสี่ยงทั้งหมด (กรอง level / province / min_si ได้)
  GET /api/risk-points/nearby          จุดเสี่ยงในรัศมีจากพิกัดที่ส่งมา พร้อมระยะห่าง
                                       และข้อความเตือนภาษาไทยสำเร็จรูป (alert_message)
  GET /api/risk-points/{point_id}      รายละเอียดจุดเดียว
  POST /api/device/location            Pi ส่งพิกัด GPS ปัจจุบันของตัวเองขึ้นมา
  GET  /api/device/location            เว็บดึงพิกัดล่าสุดของ Pi ไปวาดหมุดเรียลไทม์

รันเซิร์ฟเวอร์:  uvicorn api.server:app --host 0.0.0.0 --port 8000
(เสิร์ฟหน้าเว็บ index.html ที่รากโปรเจกต์ให้ด้วย จึงใช้เซิร์ฟเวอร์เดียวได้ทั้งเว็บและ API)
"""

import json
import os
import re
import time
import urllib.error
import urllib.request
from math import asin, cos, pi, radians, sin, sqrt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

PROJECT_ROOT = Path(__file__).resolve().parent.parent

# ชุดข้อมูลที่ API แจกจ่าย — ต้องเป็นชุดเดียวกับที่หน้าเว็บตั้งไว้ใน window.RISK_DATA_URL
# (index.html / dashboard.html) ไม่งั้น buzzer บน Pi จะเตือนคนละคลัสเตอร์กับหมุดบนแผนที่
# สลับกลับไปชุด 1 ปีเพื่อเทียบผลได้โดยไม่ต้องแก้โค้ด:
#   PowerShell:  $env:RISK_DATA_FILE = "data/risk_points_bkk_metro.geojson"
#   bash:        RISK_DATA_FILE=data/risk_points_bkk_metro.geojson uvicorn api.server:app
DEFAULT_DATA_FILE = "data/risk_points_bkk_metro_3y.geojson"  # ชุด 3 ปี (2566-2568) = ชุดหลักของระบบ
DATA_FILE = PROJECT_ROOT / os.environ.get("RISK_DATA_FILE", DEFAULT_DATA_FILE)

EARTH_RADIUS_M = 6371000

# ---------- ตั้งค่า Botnoi Voice (TTS) ----------
# เก็บ token ไว้ใน environment variable เท่านั้น — ห้าม commit key ลงโค้ด
#   PowerShell:  $env:BOTNOI_TOKEN = "xxxx";  uvicorn api.server:app --port 8000
#   bash:        BOTNOI_TOKEN=xxxx uvicorn api.server:app --port 8000
BOTNOI_TOKEN = os.environ.get("BOTNOI_TOKEN", "")
BOTNOI_SPEAKER = os.environ.get("BOTNOI_SPEAKER", "1")  # เลือก speaker id ที่ชอบได้
BOTNOI_URL = "https://api-voice.botnoi.ai/openapi/v1/generate_audio"
_tts_cache: dict[str, bytes] = {}  # (speaker:text) -> ไฟล์เสียง mp3 ที่สร้างแล้ว

app = FastAPI(
    title="EMMA Risk Point API",
    description="API แจกจ่ายข้อมูลจุดเสี่ยงอุบัติเหตุ กรุงเทพฯ และปริมณฑล",
    version="1.0.0",
)

# เปิด CORS ทุก origin — ข้อมูลจุดเสี่ยงเป็นสาธารณะแบบอ่านอย่างเดียว
# ต้องมี POST ด้วยเพราะ Pi ส่งพิกัดตัวเองขึ้น /api/device/location
# (ไม่มี auth เพราะระบบนี้รันในวงแลนเดียวกับ Pi เท่านั้น ถ้าเอาขึ้น public
#  ต้องใส่ token ที่ endpoint นั้นก่อน ไม่งั้นใครก็ปลอมพิกัดรถได้)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)


# ---------- โหลดข้อมูล ----------

def load_points():
    """อ่าน GeoJSON แล้ว flatten เป็น [{id, lat, lng, ...properties}] แบบเดียวกับ riskpoints.js

    คืน (points, calibration) — calibration ใช้บอกเวอร์ชันรอบคำนวณผ่าน /api/health
    """
    with open(DATA_FILE, encoding="utf-8") as f:
        geojson = json.load(f)
    points = []
    for feat in geojson["features"]:
        lng, lat = feat["geometry"]["coordinates"]
        points.append({"lat": lat, "lng": lng, **feat["properties"]})
    return points, geojson.get("calibration") or {}


POINTS, CALIBRATION = load_points()
POINTS_BY_ID = {p["id"]: p for p in POINTS}


# ---------- ระยะทาง (port จาก js/distance.js) ----------

def haversine_meters(lat1, lon1, lat2, lon2):
    d_lat = radians(lat2 - lat1)
    d_lon = radians(lon2 - lon1)
    a = (
        sin(d_lat / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    )
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def in_bounding_box(user_lat, user_lon, point_lat, point_lon, radius_m):
    d_lat = radius_m / 111320  # 1 องศาละติจูด ≈ 111.32 กม.
    d_lon = radius_m / (111320 * cos(user_lat * pi / 180))
    return abs(point_lat - user_lat) <= d_lat and abs(point_lon - user_lon) <= d_lon


def find_nearby(user_lat, user_lon, radius_m):
    nearby = []
    for p in POINTS:
        if not in_bounding_box(user_lat, user_lon, p["lat"], p["lng"], radius_m):
            continue
        d = haversine_meters(user_lat, user_lon, p["lat"], p["lng"])
        if d <= radius_m:
            nearby.append((p, d))
    nearby.sort(key=lambda item: item[1])
    return nearby


# ---------- กติกา Dynamic Alert (port จาก js/riskrules.js) ----------
# แต่ละกติกา: (id, เงื่อนไข, สาเหตุ, คำแนะนำ) เรียงตามความสำคัญ —
# ข้อความเสียงหยิบข้อแรกที่เข้าเงื่อนไข

RULES = [
    (
        "fatal-history",
        lambda p: p.get("deaths", 0) >= 1,
        lambda p: f"จุดนี้เคยมีผู้เสียชีวิต {p['deaths']} ราย",
        # "เป็นพิเศษ" สงวนไว้ให้ระดับสูงเท่านั้น ไม่งั้นคำเตือนสองระดับฟังเหมือนกันเป๊ะ
        # 2026-08-25: ตัด "ลดความเร็ว" ออกตามที่ผู้ใช้ขอ ใช้ "เพิ่มสมาธิในการขับขี่"
        # แทน — single-vehicle/rollover ก็ใช้ประโยคเดียวกันนี้ด้วย (ดูด้านล่าง)
        lambda p: (
            "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
            if p["level"] == "high"
            else "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง"
        ),
    ),
    (
        "junction",
        lambda p: re.search(r"แยก|ทางร่วม", p.get("road_feature") or ""),
        lambda p: "เป็นบริเวณทางแยกทางร่วม",
        lambda p: "ลดความเร็ว และระวังรถตัดผ่านทางแยก",
    ),
    (
        "u-turn",
        lambda p: re.search(r"กลับรถ", p.get("road_feature") or ""),
        lambda p: "เป็นบริเวณจุดกลับรถ",
        lambda p: "เว้นระยะห่าง และระวังรถชะลอตัวเพื่อกลับรถ",
    ),
    (
        "curve",
        lambda p: re.search(r"โค้ง", p.get("road_feature") or ""),
        lambda p: "เป็นช่วงทางโค้ง",
        lambda p: "ลดความเร็วก่อนเข้าโค้ง และงดแซงในช่วงนี้",
    ),
    (
        "access-road",
        lambda p: re.search(r"เชื่อมเข้า", p.get("road_feature") or ""),
        lambda p: "มีทางเชื่อมเข้าออกพื้นที่ข้างทาง",
        lambda p: "ระวังรถเข้าออกพื้นที่ข้างทาง",
    ),
    (
        "single-vehicle",
        lambda p: p.get("pattern") == "single",
        lambda p: "จุดนี้มักเกิดเหตุรถเสียหลักออกนอกเส้นทาง",
        # ใช้ประโยคเดียวกับ fatal-history — cause (popup) ยังต่างกันอยู่
        lambda p: (
            "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
            if p["level"] == "high"
            else "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง"
        ),
    ),
    (
        "multi-vehicle",
        lambda p: p.get("pattern") == "multiple",
        lambda p: "จุดนี้มักเกิดเหตุรถหลายคันชนกัน",
        lambda p: "เว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง",
    ),
    (
        "speeding-cause",
        lambda p: re.search(r"เร็ว", p.get("top_cause") or ""),
        lambda p: "สาเหตุหลักมาจากการใช้ความเร็วเกินกำหนด",
        lambda p: f"ใช้ความเร็วไม่เกิน {p['speed_limit']} กิโลเมตรต่อชั่วโมง",
    ),
    (
        "rear-end",
        lambda p: re.search(r"ชนท้าย", p.get("crash_pattern") or ""),
        lambda p: "จุดนี้เกิดเหตุชนท้ายบ่อยครั้ง",
        lambda p: "เว้นระยะห่างจากรถคันหน้าให้มากขึ้น",
    ),
    (
        "rollover",
        lambda p: re.search(r"พลิกคว่ำ|ตกถนน", p.get("crash_pattern") or ""),
        lambda p: "จุดนี้เกิดเหตุรถพลิกคว่ำบ่อยครั้ง",
        lambda p: (
            "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
            if p["level"] == "high"
            else "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง"
        ),
    ),
    (
        "high-speed-road",
        lambda p: (p.get("speed_limit") or 0) >= 90,
        lambda p: "เป็นถนนที่ใช้ความเร็วสูง",
        lambda p: "เว้นระยะห่าง และหลีกเลี่ยงการเปลี่ยนช่องทางกะทันหัน",
    ),
]


def evaluate_rules(point):
    return [
        {"id": rid, "cause": cause(point), "advice": advice(point)}
        for rid, when, cause, advice in RULES
        if when(point)
    ]


def build_alert_message(point, distance_m):
    """ข้อความเตือนภาษาไทย (แบบเดียวกับ riskrules.buildAlertMessage) พร้อมให้ TTS พูด

    ต้องแก้คู่กับ js/riskrules.js เสมอ — ข้อความไม่ตรงกันแล้ว VOICE_CLIPS ใน
    js/tts.js และ device/pi_alert_client.py จะ match ไม่ติด ตกไปใช้ TTS สดทุกครั้ง
    """
    dist = round(distance_m / 50) * 50
    matched = evaluate_rules(point)
    top = matched[0] if matched else None

    if point["level"] == "high":
        advice = top["advice"] if top else "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
        return f"ข้างหน้าอีก {dist} เมตร ใกล้จุดเสี่ยงสูง โปรด{advice}"
    if point["level"] == "medium":
        advice = top["advice"] if top else "ลดความเร็ว และขับขี่ด้วยความระมัดระวัง"
        return f"ข้างหน้าอีก {dist} เมตร ใกล้จุดเสี่ยงปานกลาง โปรด{advice}"
    return f"ข้างหน้าอีก {dist} เมตร ใกล้จุดเสี่ยงต่ำ โปรดขับขี่ด้วยความระมัดระวัง"


# ---------- Endpoints ----------

@app.get("/api/health")
def health():
    """ใช้ตรวจว่าเซิร์ฟเวอร์กำลังแจกข้อมูลชุดไหน/รอบคำนวณอะไร หลัง build ข้อมูลใหม่"""
    return {
        "status": "ok",
        "total_points": len(POINTS),
        "dataset": DATA_FILE.name,
        "version": CALIBRATION.get("version"),
        "generated_at": CALIBRATION.get("generated_at"),
    }


@app.get("/api/risk-points")
def list_risk_points(
    level: str | None = Query(None, description="กรองระดับ: high / medium / low"),
    province: str | None = Query(None, description="กรองชื่อจังหวัด เช่น นนทบุรี"),
    min_si: float | None = Query(None, ge=0, description="ดัชนีความรุนแรง (SI) ขั้นต่ำ"),
):
    result = POINTS
    if level:
        result = [p for p in result if p["level"] == level]
    if province:
        result = [p for p in result if province in p["province"]]
    if min_si is not None:
        result = [p for p in result if p["severity_index"] >= min_si]
    return {"count": len(result), "points": result}


@app.get("/api/risk-points/nearby")
def nearby_risk_points(
    lat: float = Query(..., ge=-90, le=90, description="ละติจูดของอุปกรณ์"),
    lng: float = Query(..., ge=-180, le=180, description="ลองจิจูดของอุปกรณ์"),
    radius: float = Query(600, gt=0, le=20000, description="รัศมีค้นหา (เมตร)"),
    limit: int = Query(10, ge=1, le=100, description="จำนวนจุดสูงสุดที่ตอบกลับ"),
):
    """จุดเสี่ยงในรัศมี เรียงใกล้ -> ไกล พร้อม distance_m และ alert_message ให้อุปกรณ์พูดได้ทันที"""
    nearby = find_nearby(lat, lng, radius)[:limit]
    return {
        "count": len(nearby),
        "points": [
            {
                **p,
                "distance_m": round(d, 1),
                "risk_factors": evaluate_rules(p),
                "alert_message": build_alert_message(p, d),
            }
            for p, d in nearby
        ],
    }


@app.get("/api/risk-points/{point_id}")
def get_risk_point(point_id: str):
    point = POINTS_BY_ID.get(point_id)
    if point is None:
        raise HTTPException(status_code=404, detail=f"ไม่พบจุดเสี่ยง id={point_id}")
    return {**point, "risk_factors": evaluate_rules(point)}


# ---------- TTS proxy (Botnoi Voice) ----------
# เบราว์เซอร์เรียกตรงไป Botnoi ไม่ได้ (CORS + ต้องซ่อน token) จึงผ่านเซิร์ฟเวอร์นี้แทน

def _fetch_botnoi_audio(text: str, speaker: str) -> bytes | None:
    """เรียก Botnoi สร้างเสียง คืน bytes ของ mp3 / None ถ้าล้มเหลว (ให้ frontend fallback)"""
    body = json.dumps(
        {
            "text": text,
            "speaker": speaker,
            "volume": 1,
            "speed": 1,
            "type_media": "mp3",
            "save_file": "true",
            "language": "th",
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        BOTNOI_URL,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json", "botnoi-token": BOTNOI_TOKEN},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            ctype = resp.headers.get("Content-Type", "")
            data = resp.read()
    except urllib.error.HTTPError as e:
        print(f"[botnoi] HTTP {e.code}: {e.read()[:200]!r}")
        return None
    except Exception as e:  # noqa: BLE001 — network/timeout ใดๆ ให้ fallback
        print(f"[botnoi] error: {e}")
        return None

    # Botnoi อาจตอบเป็นไฟล์เสียงตรงๆ หรือ JSON ที่มี URL ของไฟล์เสียง
    if ctype.startswith("audio/"):
        return data
    try:
        obj = json.loads(data)
    except Exception:
        return data or None
    url = obj.get("audio_url") or obj.get("url") or obj.get("data")
    if not isinstance(url, str) or not url:
        print(f"[botnoi] รูปแบบ response ไม่คาดคิด: {str(obj)[:200]}")
        return None
    try:
        with urllib.request.urlopen(url, timeout=30) as r2:
            return r2.read()
    except Exception as e:  # noqa: BLE001
        print(f"[botnoi] โหลดไฟล์เสียงจาก url ไม่สำเร็จ: {e}")
        return None


@app.get("/api/tts")
def tts(
    text: str = Query(..., min_length=1, max_length=300, description="ข้อความที่จะแปลงเป็นเสียง"),
    speaker: str | None = Query(None, description="speaker id ของ Botnoi (ไม่ใส่ = ค่าเริ่มต้น)"),
):
    """คืนไฟล์เสียง mp3 จาก Botnoi ให้ <audio> เล่นได้ตรงๆ — มี cache กันเรียกซ้ำ (ประหยัดพอยท์)"""
    if not BOTNOI_TOKEN:
        raise HTTPException(status_code=503, detail="ยังไม่ได้ตั้งค่า BOTNOI_TOKEN")
    spk = speaker or BOTNOI_SPEAKER
    key = f"{spk}:{text}"
    audio = _tts_cache.get(key)
    if audio is None:
        audio = _fetch_botnoi_audio(text, spk)
        if audio is None:
            raise HTTPException(status_code=502, detail="สร้างเสียงจาก Botnoi ไม่สำเร็จ")
        _tts_cache[key] = audio
    return Response(content=audio, media_type="audio/mpeg", headers={"Cache-Control": "max-age=86400"})


# ---------- ตำแหน่งเรียลไทม์ของอุปกรณ์ (Raspberry Pi + GPS BE-609U) ----------
# Pi ยิง POST เข้ามาทุกรอบโพล (3 วิ) เว็บดึง GET ไปวาดหมุดบนแผนที่
#
# เก็บไว้ในตัวแปรในหน่วยความจำ ไม่ลง DB เพราะ:
#   - เก็บแค่ "ตำแหน่งล่าสุด" จุดเดียว ไม่ต้องการประวัติย้อนหลัง
#   - รีสตาร์ตเซิร์ฟเวอร์แล้วหายไม่เป็นไร Pi ส่งใหม่ภายใน 3 วิอยู่แล้ว
# ถ้าต่อไปอยากได้เส้นทางย้อนหลัง ค่อยเปลี่ยนเป็น deque หรือ SQLite ตรงนี้จุดเดียว
_DEVICE_STALE_AFTER_S = 15  # เกินนี้ = ถือว่าอุปกรณ์หลุด (Pi ส่งทุก 3 วิ เผื่อพลาด 4 รอบ)

# เกินนี้ = ลืมพิกัดไปเลย ไม่ใช่แค่ทำเป็นสีจาง
# ระหว่าง 15 วิ ถึง 10 นาที ยังแสดงหมุดไว้เพราะมีประโยชน์ — บอกได้ว่า 'เห็นครั้งสุดท้ายตรงนี้'
# ตอนรถวิ่งเข้าอุโมงค์หรือสัญญาณตกชั่วคราว
# แต่เกิน 10 นาทีข้อมูลไม่มีประโยชน์แล้ว มีแต่โทษ: เคยเกิดจริงตอนพิกัดค้างจากการรัน
# โหมดจำลอง (--route) ค้างอยู่ 38 นาที แล้วไปโผล่บนแผนที่สนามทดสอบคนละจังหวัด
# ซึ่งถ้าเป็นตอนสาธิตหน้ากรรมการจะอธิบายยากมาก
_DEVICE_FORGET_AFTER_S = 600

_device_location: dict = {
    "lat": None,
    "lng": None,
    "speed_kmh": None,
    "satellites": None,
    "source": None,      # "serial" / "gpsd" / "route" / "fixed" — บอกว่าเป็น GPS จริงหรือโหมดจำลอง
    "updated_at": None,  # epoch seconds ที่ได้ "พิกัด" ล่าสุด
    # เวลาที่ Pi ติดต่อเข้ามาล่าสุด ไม่ว่าจะมีพิกัดหรือไม่ — แยกจาก updated_at เพราะ
    # ระหว่างที่ GPS ยังจับดาวไม่ได้ Pi ทำงานอยู่แต่ไม่มีพิกัดจะส่ง ถ้าดูแค่ updated_at
    # จะแยกไม่ออกระหว่าง "เครื่องดับ" กับ "เครื่องทำงานอยู่ กำลังหาดาว" ซึ่งวิธีแก้ต่างกันมาก
    # (เสียเที่ยวทดสอบไปแล้ว 1 รอบเพราะแยกสองอย่างนี้ไม่ออก — 2026-08-27)
    "seen_at": None,
}


class DeviceLocation(BaseModel):
    """สถานะที่ Pi ส่งขึ้นมา — lat/lng เว้นว่างได้เมื่อยังจับดาวไม่ได้

    ยอมให้ lat/lng เป็น null เพื่อให้ Pi รายงานได้ว่า "ยังทำงานอยู่นะ แค่ยังไม่มีพิกัด"
    เว็บจะได้แสดง "กำลังค้นหาสัญญาณ · เห็นดาว N ดวง" แทนที่จะเงียบเหมือนเครื่องดับ
    """
    lat: float | None = Field(None, ge=-90, le=90)
    lng: float | None = Field(None, ge=-180, le=180)
    speed_kmh: float | None = Field(None, ge=0, le=300)
    satellites: int | None = Field(None, ge=0, le=64)
    source: str | None = Field(None, max_length=20)


@app.post("/api/device/location")
def update_device_location(loc: DeviceLocation):
    """รับสถานะล่าสุดจาก Raspberry Pi (เขียนทับของเดิมเสมอ)"""
    now = time.time()
    # จำนวนดาว/แหล่งพิกัด อัปเดตทุกครั้ง เพราะเป็นข้อมูลของ "ตัวรับ" ไม่ใช่ของพิกัด
    # ตัวเลขดาวที่ขยับระหว่างยังไม่ได้พิกัดคือสิ่งที่บอกว่ากำลังคืบหน้าหรือค้างสนิท
    _device_location.update(satellites=loc.satellites, source=loc.source, seen_at=now)
    # ไม่มีพิกัดก็ไม่แตะพิกัดเดิม — ของเก่ายังมีประโยชน์ตอนสัญญาณตกชั่วคราว
    # (บอกได้ว่า "เห็นครั้งสุดท้ายตรงนี้") และมี _DEVICE_FORGET_AFTER_S คุมอายุอยู่แล้ว
    if loc.lat is not None and loc.lng is not None:
        _device_location.update(
            lat=loc.lat, lng=loc.lng, speed_kmh=loc.speed_kmh, updated_at=now,
        )
    return {"ok": True}


@app.get("/api/device/location")
def get_device_location():
    """พิกัดล่าสุดของอุปกรณ์ + อายุของข้อมูล ให้เว็บรู้ว่ายังออนไลน์อยู่ไหม

    online=False ได้ 2 กรณี: ยังไม่เคยมี Pi ส่งเข้ามาเลย (updated_at=None)
    หรือส่งครั้งสุดท้ายนานเกิน _DEVICE_STALE_AFTER_S (Pi ดับ/เน็ตหลุด/GPS ไม่จับดาว)
    เว็บใช้ค่านี้ตัดสินใจว่าจะแสดงหมุดแบบจางหรือซ่อนไปเลย
    """
    now = time.time()
    updated_at = _device_location["updated_at"]
    seen_at = _device_location["seen_at"]
    age_s = None if updated_at is None else round(now - updated_at, 1)
    seen_age_s = None if seen_at is None else round(now - seen_at, 1)

    # อุปกรณ์ยังติดต่อเข้ามาอยู่ (จะมีพิกัดหรือไม่ก็ตาม) = เครื่องเปิดอยู่ โปรแกรมรันอยู่
    device_up = seen_age_s is not None and seen_age_s <= _DEVICE_STALE_AFTER_S
    online = age_s is not None and age_s <= _DEVICE_STALE_AFTER_S
    # เครื่องทำงานอยู่แต่ยังไม่มีพิกัดสด = กำลังหาดาว ต่างจากเครื่องดับที่เงียบไปเลย
    searching = device_up and not online

    # เก่าเกินกำหนด -> ตอบเหมือนยังไม่เคยมีอุปกรณ์ส่งอะไรมาเลย ให้หมุดหายไปจากแผนที่
    # ไม่ลบ _device_location ทิ้งจริง ๆ เพราะถ้า Pi กลับมาส่งใหม่ค่าจะถูกเขียนทับอยู่แล้ว
    # และการอ่านอย่างเดียวไม่ควรมีผลข้างเคียง (ผู้ใช้เปิดหลายเครื่องพร้อมกันได้)
    #
    # ยังคง satellites/searching ไว้ตรงนี้ด้วย เพราะกรณีที่พบบ่อยที่สุดคือเพิ่งเปิดเครื่อง
    # กลางแจ้ง: ไม่เคยมีพิกัดเลย (หรือของเก่าหมดอายุ) แต่ตัวรับกำลังไล่จับดาวอยู่จริง ๆ
    if age_s is not None and age_s > _DEVICE_FORGET_AFTER_S:
        return {
            "lat": None, "lng": None, "speed_kmh": None,
            "satellites": _device_location["satellites"] if device_up else None,
            "source": None, "updated_at": None, "age_s": None, "online": False,
            "searching": searching, "seen_age_s": seen_age_s,
            "stale_after_s": _DEVICE_STALE_AFTER_S,
            "forgotten_age_s": round(age_s),  # ให้เว็บบอกผู้ใช้ได้ว่าเงียบมานานแค่ไหน
        }

    return {
        **_device_location,
        "age_s": age_s,
        "online": online,
        "searching": searching,
        "seen_age_s": seen_age_s,
        "stale_after_s": _DEVICE_STALE_AFTER_S,
    }


# เสิร์ฟหน้าเว็บเดิม (index.html, dashboard.html, js/, css/, data/) จากรากโปรเจกต์
# ต้อง mount ท้ายสุดเพื่อไม่ให้ทับเส้นทาง /api ด้านบน
app.mount("/", StaticFiles(directory=PROJECT_ROOT, html=True), name="static")
