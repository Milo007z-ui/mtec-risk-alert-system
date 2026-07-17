import requests
import json
from math import radians
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

        # หาสาเหตุที่พบบ่อยที่สุดในกลุ่มนี้ (ใช้บอกลักษณะจุดเสี่ยง)
        causes = {}
        for m in members:
            causes[m["cause"]] = causes.get(m["cause"], 0) + 1
        top_cause = max(causes, key=causes.get)

        location_types = {}
        for m in members:
            location_types[m["location_type"]] = location_types.get(m["location_type"], 0) + 1
        top_location_type = max(location_types, key=location_types.get)

        severity_score = deaths * 3 + serious * 2 + minor
        if deaths > 0 or severity_score >= 15:
            level = "high"
        elif severity_score >= 6:
            level = "medium"
        else:
            level = "low"

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

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(to_geojson(zones), f, ensure_ascii=False, indent=2)
    print(f"บันทึกไฟล์ {OUTPUT_FILE} เรียบร้อย")


if __name__ == "__main__":
    main()