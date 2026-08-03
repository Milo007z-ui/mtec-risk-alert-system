import requests
import json
from math import radians, log
from pathlib import Path
from sklearn.cluster import DBSCAN
import numpy as np

RESOURCE_ID_2025 = "64089b01-29ae-4cff-8115-c1e65894c5a6"
XLSX_FILE_2026 = None

BANGKOK_METRO_PROVINCES = [
    "กรุงเทพมหานคร", "นนทบุรี", "ปทุมธานี",
    "สมุทรปราการ", "นครปฐม", "สมุทรสาคร"
]

EPS_METERS = 400
MIN_SAMPLES = 3
API_BASE = "https://datagov.mot.go.th/api/3/action/datastore_search"
OUTPUT_FILE = Path(__file__).resolve().parent.parent / "data" / "risk_points_bkk_metro.geojson"

EPDO_DEATH = 10
EPDO_SERIOUS = 4
EPDO_MINOR = 1

SPEED_LIMIT_BY_ROADTYPE = {
    "การทางพิเศษ": 100,
    "ทางหลวง": 90,
    "ทางหลวงชนบท": 80,
}
SPEED_LIMIT_DEFAULT = 80

GEOMETRY_FULL_SCORE = 20
CP_MAX = 32
CONFLICT_POINTS = {
    "4leg": 32,
    "3leg": 9,
    "roundabout": 8,
    "uturn": 4,
    "straight": 0,
}
CURVE_SCORE_PROVISIONAL = 10.0

SPEED_FULL_SCORE = 15
NILSSON_FATALITY_EXPONENT = 4

LOSS_SD_MULTIPLIER = 0.5
KSI_BLACKSPOT_COUNT = 3


def geometry_score_for_type(location_type):
    t = location_type or ""
    if "วงเวียน" in t:
        return GEOMETRY_FULL_SCORE * CONFLICT_POINTS["roundabout"] / CP_MAX
    if "สามแยก" in t or "3 แยก" in t:
        return GEOMETRY_FULL_SCORE * CONFLICT_POINTS["3leg"] / CP_MAX
    if "แยก" in t or "ทางร่วม" in t:
        return GEOMETRY_FULL_SCORE * CONFLICT_POINTS["4leg"] / CP_MAX
    if "กลับรถ" in t:
        return GEOMETRY_FULL_SCORE * CONFLICT_POINTS["uturn"] / CP_MAX
    if "เชื่อมเข้า" in t:
        return GEOMETRY_FULL_SCORE * CONFLICT_POINTS["3leg"] / CP_MAX
    if "โค้ง" in t:
        return CURVE_SCORE_PROVISIONAL
    return GEOMETRY_FULL_SCORE * CONFLICT_POINTS["straight"] / CP_MAX


def _log_norm_score(value, max_value, full_score):
    if max_value <= 0:
        return 0.0
    return full_score * min(1.0, log(1 + value) / log(1 + max_value))


def compute_risk_score(members, deaths, serious, minor, speed_limit, v_ref,
                       freq_max, epdo_max):
    freq = _log_norm_score(len(members), freq_max, 30)

    epdo = deaths * EPDO_DEATH + serious * EPDO_SERIOUS + minor * EPDO_MINOR
    severity = _log_norm_score(epdo, epdo_max, 35)

    geometry = sum(geometry_score_for_type(m["location_type"]) for m in members) / len(members)

    speed = SPEED_FULL_SCORE * (speed_limit / v_ref) ** NILSSON_FATALITY_EXPONENT

    total = freq + severity + geometry + speed
    return round(total, 1), {
        "frequency": round(freq, 1),
        "severity": round(severity, 1),
        "geometry": round(geometry, 1),
        "speed": round(speed, 1),
    }


def classify(risk_score, ksi_count, mean_score, sd_score):
    if ksi_count >= KSI_BLACKSPOT_COUNT:
        return "high"
    if risk_score > mean_score + LOSS_SD_MULTIPLIER * sd_score:
        return "high"
    if risk_score < mean_score - LOSS_SD_MULTIPLIER * sd_score:
        return "low"
    return "medium"


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
            "_members": members,
        })

    if not zones:
        return zones

    v_ref = max(z["speed_limit"] for z in zones)
    freq_max = max(z["accident_count"] for z in zones)
    epdo_max = max(
        z["deaths"] * EPDO_DEATH + z["serious_injury"] * EPDO_SERIOUS
        + z["minor_injury"] * EPDO_MINOR
        for z in zones
    )
    for z in zones:
        z["risk_score"], z["score_breakdown"] = compute_risk_score(
            z["_members"], z["deaths"], z["serious_injury"], z["minor_injury"],
            z["speed_limit"], v_ref, freq_max, epdo_max,
        )
        del z["_members"]

    scores = np.array([z["risk_score"] for z in zones])
    mean_score, sd_score = float(scores.mean()), float(scores.std())
    for z in zones:
        ksi_count = z["deaths"] + z["serious_injury"]
        z["level"] = classify(z["risk_score"], ksi_count, mean_score, sd_score)

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

    scores = sorted(z["risk_score"] for z in zones)
    pct = lambda p: scores[min(len(scores) - 1, int(p / 100 * len(scores)))]
    print(f"  risk_score: min {scores[0]} | P25 {pct(25)} | P50 {pct(50)} | "
          f"P75 {pct(75)} | P90 {pct(90)} | max {scores[-1]}")

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(to_geojson(zones), f, ensure_ascii=False, indent=2)
    print(f"บันทึกไฟล์ {OUTPUT_FILE} เรียบร้อย")


def _self_test():
    v_ref = 100
    freq_max, epdo_max = 50, 120

    intersection = [{"location_type": "ทางแยก"}] * 5
    s_int, b_int = compute_risk_score(intersection, deaths=2, serious=1,
                                      minor=2, speed_limit=90, v_ref=v_ref,
                                      freq_max=freq_max, epdo_max=epdo_max)

    straight = [{"location_type": "ทางตรง"}] * 5
    s_str, b_str = compute_risk_score(straight, deaths=0, serious=0,
                                      minor=2, speed_limit=80, v_ref=v_ref,
                                      freq_max=freq_max, epdo_max=epdo_max)

    print(f"สี่แยก+เสียชีวิต : {s_int} {b_int}")
    print(f"ทางตรง+ไม่ตาย    : {s_str} {b_str}")
    assert s_int > s_str, "สี่แยกที่มีผู้เสียชีวิตต้องได้คะแนนสูงกว่าทางตรงที่ไม่มี"

    assert geometry_score_for_type("ทางแยก") == 20.0
    assert round(geometry_score_for_type("สามแยก"), 3) == 5.625
    assert geometry_score_for_type("วงเวียน") == 5.0
    assert geometry_score_for_type("จุดกลับรถ") == 2.5
    assert geometry_score_for_type("ทางโค้ง") == CURVE_SCORE_PROVISIONAL
    assert geometry_score_for_type("ทางตรง") == 0.0

    assert b_int["speed"] == round(15 * 0.9 ** 4, 1)
    assert b_str["speed"] == round(15 * 0.8 ** 4, 1)

    assert _log_norm_score(100, 100, 30) == 30.0
    assert _log_norm_score(0, 100, 30) == 0.0
    assert _log_norm_score(5, 0, 30) == 0.0

    top_freq = [{"location_type": "ทางตรง"}] * 40
    _, b_topf = compute_risk_score(top_freq, deaths=0, serious=0, minor=0,
                                   speed_limit=80, v_ref=v_ref,
                                   freq_max=40, epdo_max=100)
    assert b_topf["frequency"] == 30.0, b_topf

    _, b_tops = compute_risk_score([{"location_type": "ทางตรง"}], deaths=1,
                                   serious=0, minor=0, speed_limit=80,
                                   v_ref=v_ref, freq_max=10, epdo_max=10)
    assert b_tops["severity"] == 35.0, b_tops

    _, b_zero = compute_risk_score([{"location_type": "ทางตรง"}], deaths=0,
                                   serious=0, minor=0, speed_limit=80,
                                   v_ref=v_ref, freq_max=10, epdo_max=0)
    assert b_zero["severity"] == 0.0, b_zero

    assert classify(10.0, ksi_count=3, mean_score=50.0, sd_score=10.0) == "high"
    assert classify(56.0, ksi_count=0, mean_score=50.0, sd_score=10.0) == "high"
    assert classify(50.0, ksi_count=0, mean_score=50.0, sd_score=10.0) == "medium"
    assert classify(44.0, ksi_count=0, mean_score=50.0, sd_score=10.0) == "low"

    print("self-test ผ่านทั้งหมด")


if __name__ == "__main__":
    import sys
    if "--selftest" in sys.argv:
        _self_test()
    else:
        main()
