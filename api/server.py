"""
server.py — REST API สำหรับให้อุปกรณ์ (เช่น Raspberry Pi บนรถเมล์) ดึงข้อมูลจุดเสี่ยง

Endpoints:
  GET /api/health                      สถานะเซิร์ฟเวอร์ + จำนวนจุดเสี่ยง
  GET /api/risk-points                 จุดเสี่ยงทั้งหมด (กรอง level / province / min_score ได้)
  GET /api/risk-points/nearby          จุดเสี่ยงในรัศมีจากพิกัดที่ส่งมา พร้อมระยะห่าง
                                       และข้อความเตือนภาษาไทยสำเร็จรูป (alert_message)
  GET /api/risk-points/{point_id}      รายละเอียดจุดเดียว

รันเซิร์ฟเวอร์:  uvicorn api.server:app --host 0.0.0.0 --port 8000
(เสิร์ฟหน้าเว็บ index.html ที่รากโปรเจกต์ให้ด้วย จึงใช้เซิร์ฟเวอร์เดียวได้ทั้งเว็บและ API)
"""

import json
import os
import re
import urllib.error
import urllib.request
from math import asin, cos, pi, radians, sin, sqrt
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = PROJECT_ROOT / "data" / "risk_points_bkk_metro.geojson"

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

# เปิด CORS ทุก origin — ข้อมูลเป็นสาธารณะแบบอ่านอย่างเดียว
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["GET"],
    allow_headers=["*"],
)


# ---------- โหลดข้อมูล ----------

def load_points():
    """อ่าน GeoJSON แล้ว flatten เป็น [{id, lat, lng, ...properties}] แบบเดียวกับ riskpoints.js"""
    with open(DATA_FILE, encoding="utf-8") as f:
        geojson = json.load(f)
    points = []
    for feat in geojson["features"]:
        lng, lat = feat["geometry"]["coordinates"]
        points.append({"lat": lat, "lng": lng, **feat["properties"]})
    return points


POINTS = load_points()
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
        lambda p: f"เคยมีผู้เสียชีวิต {p['deaths']} ราย",
        lambda p: "ลดความเร็วและใช้ความระมัดระวังสูงสุด",
    ),
    (
        "junction",
        lambda p: re.search(r"แยก|ทางร่วม", p.get("road_feature") or ""),
        lambda p: "บริเวณทางแยก/ทางร่วม",
        lambda p: "ชะลอความเร็ว ระวังรถตัดกระแสจราจร",
    ),
    (
        "u-turn",
        lambda p: re.search(r"กลับรถ", p.get("road_feature") or ""),
        lambda p: "บริเวณจุดกลับรถ",
        lambda p: "ระวังรถชะลอเพื่อกลับรถ เว้นระยะห่าง",
    ),
    (
        "curve",
        lambda p: re.search(r"โค้ง", p.get("road_feature") or ""),
        lambda p: "บริเวณทางโค้ง",
        lambda p: "ลดความเร็วก่อนเข้าโค้ง งดแซง",
    ),
    (
        "access-road",
        lambda p: re.search(r"เชื่อมเข้า", p.get("road_feature") or ""),
        lambda p: "ทางเชื่อมเข้าพื้นที่ข้างทาง",
        lambda p: "ระวังรถเข้า-ออกกะทันหัน",
    ),
    (
        "speeding-cause",
        lambda p: re.search(r"เร็ว", p.get("top_cause") or ""),
        lambda p: "สถิติชี้ว่าสาเหตุหลักคือการขับเร็วเกินกำหนด",
        lambda p: f"ใช้ความเร็วไม่เกิน {p['speed_limit']} กิโลเมตรต่อชั่วโมง",
    ),
    (
        "rear-end",
        lambda p: re.search(r"ชนท้าย", p.get("crash_pattern") or ""),
        lambda p: "จุดนี้เกิดเหตุชนท้ายบ่อย",
        lambda p: "เว้นระยะห่างจากรถคันหน้าให้มากขึ้น",
    ),
    (
        "rollover",
        lambda p: re.search(r"พลิกคว่ำ|ตกถนน", p.get("crash_pattern") or ""),
        lambda p: "จุดนี้เกิดเหตุรถเสียหลัก/พลิกคว่ำบ่อย",
        lambda p: "ลดความเร็ว จับพวงมาลัยให้มั่นคง",
    ),
    (
        "high-speed-road",
        lambda p: (p.get("speed_limit") or 0) >= 90,
        lambda p: f"ถนนความเร็วสูง (จำกัด {p['speed_limit']} กม./ชม.)",
        lambda p: "เว้นระยะห่างและไม่เปลี่ยนช่องทางกะทันหัน",
    ),
]


def evaluate_rules(point):
    return [
        {"id": rid, "cause": cause(point), "advice": advice(point)}
        for rid, when, cause, advice in RULES
        if when(point)
    ]


def build_alert_message(point, distance_m):
    """ข้อความเตือนภาษาไทย (แบบเดียวกับ riskrules.buildAlertMessage) พร้อมให้ TTS พูด"""
    dist = round(distance_m / 50) * 50
    matched = evaluate_rules(point)
    top = matched[0] if matched else None

    if point["level"] == "high":
        tail = (
            f" {top['cause']} โปรด{top['advice']}"
            if top
            else " โปรดลดความเร็วและใช้ความระมัดระวังสูงสุด"
        )
        return f"โปรดทราบ ข้างหน้าประมาณ {dist} เมตร เป็นจุดเสี่ยงอุบัติเหตุระดับสูง{tail}"
    if point["level"] == "medium":
        tail = (
            f" {top['cause']} โปรด{top['advice']}"
            if top
            else " โปรดขับขี่ด้วยความระมัดระวัง"
        )
        return f"ข้างหน้าประมาณ {dist} เมตร เป็นจุดเสี่ยงอุบัติเหตุระดับปานกลาง{tail}"
    return f"ข้างหน้าประมาณ {dist} เมตร มีจุดเฝ้าระวังอุบัติเหตุ โปรดขับขี่ด้วยความระมัดระวัง"


# ---------- Endpoints ----------

@app.get("/api/health")
def health():
    return {"status": "ok", "total_points": len(POINTS)}


@app.get("/api/risk-points")
def list_risk_points(
    level: str | None = Query(None, description="กรองระดับ: high / medium / low"),
    province: str | None = Query(None, description="กรองชื่อจังหวัด เช่น นนทบุรี"),
    min_score: float | None = Query(None, ge=0, le=100, description="คะแนนความเสี่ยงขั้นต่ำ"),
):
    result = POINTS
    if level:
        result = [p for p in result if p["level"] == level]
    if province:
        result = [p for p in result if province in p["province"]]
    if min_score is not None:
        result = [p for p in result if p["risk_score"] >= min_score]
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


# เสิร์ฟหน้าเว็บเดิม (index.html, dashboard.html, js/, css/, data/) จากรากโปรเจกต์
# ต้อง mount ท้ายสุดเพื่อไม่ให้ทับเส้นทาง /api ด้านบน
app.mount("/", StaticFiles(directory=PROJECT_ROOT, html=True), name="static")
