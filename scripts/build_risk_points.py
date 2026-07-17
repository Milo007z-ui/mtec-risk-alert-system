import requests
import json
from math import radians, log
from pathlib import Path
from sklearn.cluster import DBSCAN
import numpy as np

# ---------- ตั้งค่า ----------
RESOURCE_ID_2025 = "64089b01-29ae-4cff-8115-c1e65894c5a6"   # ปี 2568 (มี API)
XLSX_FILE_2026 = None   # ตั้งเป็น "accident2026.xlsx" ถ้าดาวน์โหลดไฟล์ปี 2569 มาแล้ว

# 6 จังหวัดที่นับเป็น "กรุงเทพฯ และปริมณฑล"
BANGKOK_METRO_PROVINCES = [
    "กรุงเทพมหานคร", "นนทบุรี", "ปทุมธานี",
    "สมุทรปราการ", "นครปฐม", "สมุทรสาคร"
]

EPS_METERS = 400          # รัศมีกลุ่ม (เมตร) - ปรับกว้างขึ้นเพราะเขตเมืองถนนหนาแน่น
MIN_SAMPLES = 3            # จำนวนอุบัติเหตุขั้นต่ำถึงจะนับเป็นจุดเสี่ยง
API_BASE = "https://datagov.mot.go.th/api/3/action/datastore_search"
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "risk_points_bkk_metro.geojson"

# ---------- Road Risk Assessment Model (คะแนนเต็ม 100) ----------
# 4 ปัจจัย: ความถี่ 30 + ความรุนแรง 35 + ลักษณะถนน 20 + ความเร็วถนน 15
#
# น้ำหนัก EPDO (Equivalent Property Damage Only — แนวปฏิบัติของ FHWA/HSIP):
# แปลงเหยื่อแต่ละระดับเป็น "หน่วยความสูญเสียเทียบเท่า" เสียชีวิตหนักสุด
EPDO_DEATH = 10
EPDO_SERIOUS = 4
EPDO_MINOR = 1

# จุดอิ่มตัวของสเกล log (เกินนี้ได้คะแนนเต็ม) — ใช้ log เพราะจำนวนอุบัติเหตุ
# มีการแจกแจงหางยาว (จุดส่วนใหญ่ 3-20 ครั้ง แต่จุดสูงสุด 364 ครั้ง)
FREQ_SATURATION = 50       # อุบัติเหตุ 50 ครั้ง/ปี = ความถี่เต็ม 30 คะแนน
EPDO_SATURATION = 120      # EPDO 120 (≈เสียชีวิต 12) = ความรุนแรงเต็ม 35 คะแนน

# ความเร็วตามกฎหมาย (กม./ชม.) อนุมานจากประเภทสายทางของหน่วยงานรับผิดชอบ
# (ชุดข้อมูลไม่มีป้ายจำกัดความเร็วรายจุด — ใช้ค่าแทนตามกฎกระทรวงฯ พ.ศ. 2564)
SPEED_LIMIT_BY_ROADTYPE = {
    "การทางพิเศษ": 100,     # ทางพิเศษ/ทางด่วน
    "ทางหลวง": 90,          # ทางหลวงแผ่นดินนอกเขตเทศบาล
    "ทางหลวงชนบท": 80,
}
SPEED_LIMIT_DEFAULT = 80

# เกณฑ์แบ่งระดับ (คาลิเบรตจากการกระจายคะแนนจริง — ดู print ใน main)
THRESHOLD_HIGH = 55
THRESHOLD_MEDIUM = 40


def geometry_weight(location_type):
    """
    น้ำหนักอันตรายเชิงกายภาพของถนน (0-1) ตามจำนวนจุดขัดแย้งกระแสจราจร
    (conflict points): ทางแยกมีจุดตัดกระแสมากสุด รองลงมาคือจุดกลับรถ/ทางโค้ง
    """
    t = location_type or ""
    if "แยก" in t or "ทางร่วม" in t:
        return 1.0   # ทางแยก/ทางร่วม — จุดตัดกระแสจราจรสูงสุด
    if "กลับรถ" in t:
        return 0.9   # จุดกลับรถ — ตัดกระแสสวนทาง + รถชะลอ
    if "โค้ง" in t:
        return 0.9 if "ลาดชัน" in t else 0.8   # ระยะมองเห็นจำกัด
    if "เชื่อมเข้า" in t:
        return 0.7   # ทางเชื่อมเข้าพื้นที่ — รถเข้าออกไม่คาดคิด
    if "ลาดชัน" in t:
        return 0.5
    if "ทางตรง" in t:
        return 0.3   # ฐานความเสี่ยงของถนนปกติ
    return 0.4       # ไม่ระบุ/อื่นๆ


def compute_risk_score(members, deaths, serious, minor, speed_limit):
    """คืน (risk_score, breakdown) ตามโมเดล 4 ปัจจัย คะแนนเต็ม 100"""
    # 1) Accident Frequency (30) — สเกล log อิ่มตัวที่ FREQ_SATURATION
    freq = 30 * min(1.0, log(1 + len(members)) / log(1 + FREQ_SATURATION))

    # 2) Accident Severity (35) — EPDO สเกล log อิ่มตัวที่ EPDO_SATURATION
    epdo = deaths * EPDO_DEATH + serious * EPDO_SERIOUS + minor * EPDO_MINOR
    severity = 35 * min(1.0, log(1 + epdo) / log(1 + EPDO_SATURATION))

    # 3) Road Geometry (20) — ค่าเฉลี่ยถ่วงน้ำหนักจากทุกเหตุการณ์ในกลุ่ม
    #    (ไม่ใช้แค่ค่าฐานนิยม เพื่อให้จุดที่มีทั้งทางแยก+ทางตรงได้คะแนนกลางๆ)
    geometry = 20 * (sum(geometry_weight(m["location_type"]) for m in members) / len(members))

    # 4) Speed Limit (15) — พลังงานจลน์ ∝ ความเร็ว² จึงใช้กำลังสอง ไม่ใช่เชิงเส้น
    speed = 15 * (speed_limit / 120) ** 2

    total = freq + severity + geometry + speed
    return round(total, 1), {
        "frequency": round(freq, 1),
        "severity": round(severity, 1),
        "geometry": round(geometry, 1),
        "speed": round(speed, 1),
    }


def classify(risk_score, deaths):
    """
    แบ่ง 3 ระดับด้วยเกณฑ์คะแนน + safety override ตามหลัก KSI
    (Killed or Seriously Injured — จุดที่เคยมีผู้เสียชีวิตต้องไม่ถูกจัดต่ำ)
    """
    if risk_score >= THRESHOLD_HIGH or deaths >= 2:
        return "high"
    if risk_score >= THRESHOLD_MEDIUM or deaths >= 1:
        return "medium"
    return "low"


def fetch_accidents(resource_id, limit=10000):
    records, offset = [], 0
    while True:
        resp = requests.get(API_BASE, params={
            "resource_id": resource_id, "limit": limit, "offset": offset
        }, timeout=30)
        resp.raise_for_status()
        batch = resp.json()["result"]["records"]
        if not batch:
            break
        records.extend(batch)
        offset += limit
        if len(batch) < limit:
            break
    return records


def load_xlsx_records(path):
    import pandas as pd
    return pd.read_excel(path).to_dict(orient="records")


def clean_points(records):
    """กรองเฉพาะปริมณฑล + พิกัดถูกต้อง"""
    points = []
    for r in records:
        if r.get("จังหวัด") not in BANGKOK_METRO_PROVINCES:
            continue
        try:
            lat = float(r["LATITUDE"])
            lng = float(r["LONGITUDE"])
        except (TypeError, ValueError, KeyError):
            continue
        if not lat or not lng:
            continue
        points.append({
            "lat": lat, "lng": lng,
            "province": r.get("จังหวัด"),
            "road": r.get("สายทาง") or "ไม่ระบุ",
            "cause": r.get("มูลเหตุสันนิษฐาน") or "ไม่ระบุ",
            "location_type": r.get("บริเวณที่เกิดเหตุ") or "ไม่ระบุ",
            "road_type": r.get("สายทางหน่วยงาน") or "ไม่ระบุ",
            "crash_pattern": r.get("ลักษณะการเกิดเหตุ") or "ไม่ระบุ",
            "deaths": int(r.get("ผู้เสียชีวิต") or 0),
            "serious": int(r.get("ผู้บาดเจ็บสาหัส") or 0),
            "minor": int(r.get("ผู้บาดเจ็บเล็กน้อย") or 0),
        })
    return points


def cluster_risk_zones(points, eps_meters, min_samples):
    if not points:
        return []
    coords = np.array([[radians(p["lat"]), radians(p["lng"])] for p in points])
    eps_rad = eps_meters / 6371000
    labels = DBSCAN(eps=eps_rad, min_samples=min_samples, metric="haversine").fit(coords).labels_

    zones = []
    for cluster_id in set(labels):
        if cluster_id == -1:
            continue
        members = [points[i] for i, l in enumerate(labels) if l == cluster_id]

        lats = [m["lat"] for m in members]
        lngs = [m["lng"] for m in members]
        deaths = sum(m["deaths"] for m in members)
        serious = sum(m["serious"] for m in members)
        minor = sum(m["minor"] for m in members)

        # ค่าฐานนิยม (mode) ของแต่ละมิติ ใช้บรรยายลักษณะเด่นของจุดเสี่ยง
        def mode_of(key):
            counts = {}
            for m in members:
                counts[m[key]] = counts.get(m[key], 0) + 1
            return max(counts, key=counts.get)

        top_cause = mode_of("cause")
        top_location_type = mode_of("location_type")
        top_crash_pattern = mode_of("crash_pattern")
        top_road_type = mode_of("road_type")

        speed_limit = SPEED_LIMIT_BY_ROADTYPE.get(top_road_type, SPEED_LIMIT_DEFAULT)
        risk_score, breakdown = compute_risk_score(members, deaths, serious, minor, speed_limit)
        level = classify(risk_score, deaths)

        zones.append({
            "id": f"zone_{cluster_id}",
            "lat": round(sum(lats) / len(lats), 6),
            "lng": round(sum(lngs) / len(lngs), 6),
            "province": members[0]["province"],
            "road": members[0]["road"],
            "accident_count": len(members),
            "deaths": deaths,
            "serious_injury": serious,
            "minor_injury": minor,
            "top_cause": top_cause,
            "road_feature": top_location_type,
            "crash_pattern": top_crash_pattern,
            "road_type": top_road_type,
            "speed_limit": speed_limit,
            "risk_score": risk_score,
            "score_breakdown": breakdown,
            "level": level,
        })
    return zones


def to_geojson(zones):
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [z["lng"], z["lat"]]},
            "properties": {k: v for k, v in z.items() if k not in ("lat", "lng")}
        } for z in zones]
    }


def main():
    print("กำลังดึงข้อมูลปี 2568 จาก MOT Data Catalog API ...")
    records = fetch_accidents(RESOURCE_ID_2025)
    print(f"ดึงมาได้ {len(records)} แถว (ทุกจังหวัด)")

    if XLSX_FILE_2026:
        try:
            records += load_xlsx_records(XLSX_FILE_2026)
            print(f"รวมข้อมูลปี 2569 แล้ว")
        except FileNotFoundError:
            print(f"ไม่พบไฟล์ {XLSX_FILE_2026} — ข้ามปี 2569")

    points = clean_points(records)
    print(f"กรองเฉพาะกรุงเทพฯ+ปริมณฑล เหลือ {len(points)} จุด")

    zones = cluster_risk_zones(points, EPS_METERS, MIN_SAMPLES)
    print(f"พบจุดเสี่ยง (คลัสเตอร์) ทั้งหมด {len(zones)} จุด")

    high = sum(1 for z in zones if z["level"] == "high")
    medium = sum(1 for z in zones if z["level"] == "medium")
    print(f"  ระดับสูง {high} จุด | ระดับปานกลาง {medium} จุด | ระดับต่ำ {len(zones) - high - medium} จุด")

    # สถิติการกระจาย risk_score ไว้ตรวจสอบ/คาลิเบรต threshold
    scores = sorted(z["risk_score"] for z in zones)
    pct = lambda p: scores[min(len(scores) - 1, int(p / 100 * len(scores)))]
    print(f"  risk_score: min {scores[0]} | P25 {pct(25)} | P50 {pct(50)} | "
          f"P75 {pct(75)} | P90 {pct(90)} | max {scores[-1]}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(to_geojson(zones), f, ensure_ascii=False, indent=2)
    print(f"บันทึกไฟล์ {OUTPUT_FILE} เรียบร้อย")


if __name__ == "__main__":
    main()