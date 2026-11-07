# -*- coding: utf-8 -*-
"""build_tiwanon_test_site.py — สร้างชุดข้อมูล "ขับทดสอบบนถนนจริง" วงรอบติวานนท์ นนทบุรี

ตำแหน่งจุดมาจากวงกลมที่ผู้ใช้วาดบนภาพหน้าจอแผนที่ (Image (1).pdf) สีของวงคือระดับความเสี่ยง
แปลงเป็นพิกัดโดยเทียบภาพกับแผ่นแผนที่ OSM ซูม 17 (ตรวจกับหมุด zone_279 ในภาพ คลาด 0.8 ม.)
เส้นทางขอจาก OSRM ต้องต่อเน็ตตอนรันสคริปต์นี้
"""

import json
import math
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "tiwanon-test-r1"
GENERATED_AT = "2026-11-08"
REAL_DATA = ROOT / "data" / "risk_points_bkk_metro_3y.geojson"
OSRM_URL = "https://router.project-osrm.org/route/v1/driving/"

# --------------------------------------------------------------------------
# จุดบังคับเส้นทาง (lat, lng, ทิศรถ, ช่วงทิศที่ยอมรับ) — ใส่ทิศกัน OSRM เกาะผิดฝั่งถนนคู่ขนาน
WAYPOINTS = [
    (13.870949, 100.517595, 160, 40),   # จุดเริ่ม ถนนติวานนท์ ขาลงใต้ ก่อนจุดแรก 870 ม.
    (13.863608, 100.520420, 165, 50),
    (13.859399, 100.521798, 195, 70),
    (13.847968, 100.514516, 215, 45),
    (13.836550, 100.506176, 250, 50),   # นครอินทร์ มุ่งตะวันตก
    (13.823174, 100.503973, 150, 70),   # พิบูลสงคราม มุ่งใต้
    (13.825165, 100.524742, 45, 45),    # วงศ์สว่าง มุ่งตะวันออกเฉียงเหนือ
    (13.833922, 100.521551, 315, 45),   # กรุงเทพ-นนทบุรี มุ่งตะวันตกเฉียงเหนือ
    (13.842573, 100.511276, 315, 45),
    (13.847968, 100.514516, 35, 45),    # ติวานนท์ ขากลับขึ้นเหนือ
    (13.859399, 100.521798, 15, 70),
    (13.863608, 100.520420, 345, 50),
    (13.870949, 100.517595, 340, 40),   # จบที่จุดเริ่ม ฝั่งขาขึ้น
]

# --------------------------------------------------------------------------
# lat/lng = จุดศูนย์กลางวงที่ผู้ใช้วาด ก่อน snap เข้าเส้นทาง · page = หน้าใน Image (1).pdf
SITES = [
    {
        "id": "tw_01", "page": 1, "lat": 13.863608, "lng": 100.520420, "level": "low",
        "road": "ถนนติวานนท์", "province": "นนทบุรี",
        "landmark": "ถนนติวานนท์ ปากซอยติวานนท์ 20 หน้าสถาบันโรคทรวงอก",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 0, "minor_injury": 2, "single_count": 3, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด", "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนท้ายในทางตรง",
    },
    {
        "id": "tw_02", "page": 2, "lat": 13.859399, "lng": 100.521798, "level": "high",
        "road": "ถนนติวานนท์", "province": "นนทบุรี",
        "landmark": "สี่แยกแคราย ฝั่งถนนติวานนท์",
        "accident_count": 3, "fatal_crashes": 2, "deaths": 2,
        "serious_injury": 2, "minor_injury": 2, "single_count": 1, "multi_count": 2,
        "top_cause": "ฝ่าฝืนสัญญาณไฟจราจร", "road_feature": "ทางแยก+ทางร่วม",
        "crash_pattern": "ชนด้านข้างบริเวณทางแยก",
    },
    {
        "id": "tw_03", "page": 4, "lat": 13.847968, "lng": 100.514516, "level": "medium",
        "road": "ถนนติวานนท์", "province": "นนทบุรี",
        "landmark": "สามแยกศรีธัญญา",
        "accident_count": 5, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 3, "minor_injury": 4, "single_count": 1, "multi_count": 4,
        "top_cause": "ตัดหน้ากระชั้นชิด", "road_feature": "ทางแยก+ทางร่วม",
        "crash_pattern": "ชนด้านข้างบริเวณทางแยก",
    },
    {
        "id": "tw_05", "page": 7, "lat": 13.836550, "lng": 100.506176, "level": "low",
        "road": "ถนนนครอินทร์", "province": "นนทบุรี",
        "landmark": "ถนนนครอินทร์ ช่วงป้าย นบ.1020",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 0, "minor_injury": 2, "single_count": 3, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด", "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนท้ายในทางตรง",
    },
    {
        "id": "tw_06", "page": 9, "lat": 13.823174, "lng": 100.503973, "level": "low",
        "road": "ถนนพิบูลสงคราม", "province": "นนทบุรี",
        "landmark": "ทางโค้งถนนพิบูลสงคราม หน้าโรงเรียนวัดเขมาภิรตาราม",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 1, "minor_injury": 2, "single_count": 3, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด", "road_feature": "ทางโค้ง",
        "crash_pattern": "เสียหลักออกนอกทางในทางโค้ง",
    },
    {
        "id": "tw_07", "page": 13, "lat": 13.825165, "lng": 100.524742, "level": "low",
        "road": "ถนนวงศ์สว่าง", "province": "กรุงเทพมหานคร",
        "landmark": "ถนนวงศ์สว่าง ใกล้ธนาคารกรุงเทพ สาขาวงศ์สว่าง",
        "accident_count": 5, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 1, "minor_injury": 2, "single_count": 2, "multi_count": 3,
        "top_cause": "ขับตามกระชั้นชิด", "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนท้ายในทางตรง",
    },
    {
        "id": "tw_08", "page": 15, "lat": 13.833922, "lng": 100.521551, "level": "low",
        "road": "ถนนกรุงเทพ-นนทบุรี", "province": "นนทบุรี",
        "landmark": "ถนนกรุงเทพ-นนทบุรี ช่วงรอยต่อจังหวัดนนทบุรี",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 0, "minor_injury": 2, "single_count": 3, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด", "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนท้ายในทางตรง",
    },
    {
        "id": "tw_09", "page": 5, "lat": 13.842573, "lng": 100.511276, "level": "medium",
        "road": "ถนนกรุงเทพ-นนทบุรี", "province": "นนทบุรี",
        "landmark": "ถนนกรุงเทพ-นนทบุรี ก่อนถึงแยกติวานนท์",
        "accident_count": 4, "fatal_crashes": 1, "deaths": 1,
        "serious_injury": 1, "minor_injury": 2, "single_count": 2, "multi_count": 2,
        "top_cause": "ตัดหน้ากระชั้นชิด", "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนด้านข้าง",
    },
]

# คลัสเตอร์จริงวงเดียวบนเส้นทาง ไม่ได้วงไว้แต่เห็นในภาพหน้า 10–11 — คัดลอกจากชุดหลักทั้งก้อน
REAL_ZONE_IDS = ["zone_279"]

COST = {"death": 6_700_000, "serious": 2_000_000, "minor": 58_000}


def haversine_m(lat1, lng1, lat2, lng2):
    r = 6371000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def line_length_m(coords):
    return sum(
        haversine_m(coords[i][1], coords[i][0], coords[i + 1][1], coords[i + 1][0])
        for i in range(len(coords) - 1)
    )


def fetch_route():
    """ขอเส้นทางจาก OSRM คืน [[lng, lat], ...]"""
    coords = ";".join(f"{lng},{lat}" for lat, lng, _, _ in WAYPOINTS)
    bearings = ";".join(f"{b},{tol}" for _, _, b, tol in WAYPOINTS)
    url = (f"{OSRM_URL}{coords}?overview=full&geometries=geojson"
           f"&continue_straight=true&bearings={bearings}")
    req = urllib.request.Request(url, headers={"User-Agent": "mtec-field-test/1.0"})
    with urllib.request.urlopen(req, timeout=30) as r:
        data = json.load(r)
    if data.get("code") != "Ok":
        raise SystemExit(f"OSRM ตอบ {data.get('code')}")
    return [[round(c[0], 6), round(c[1], 6)] for c in data["routes"][0]["geometry"]["coordinates"]]


def snap_to_route(lat, lng, route):
    """จุดบนเส้นทางที่ใกล้ (lat, lng) สุด คืน (lat, lng, ระยะที่ขยับ ม., ระยะตามเส้นทาง ม.)"""
    kx = math.cos(math.radians(lat)) * 111320.0
    ky = 110574.0
    best = None
    along = 0.0
    for a, b in zip(route, route[1:]):
        ax, ay = (a[0] - lng) * kx, (a[1] - lat) * ky
        bx, by = (b[0] - lng) * kx, (b[1] - lat) * ky
        dx, dy = bx - ax, by - ay
        seg2 = dx * dx + dy * dy
        t = 0.0 if seg2 == 0 else max(0.0, min(1.0, -(ax * dx + ay * dy) / seg2))
        d = math.hypot(ax + t * dx, ay + t * dy)
        # เส้นทางผ่านติวานนท์สองรอบ ยึดรอบแรกถ้าระยะพอ ๆ กัน
        if best is None or d < best[2] - 0.01:
            best = (a[1] + t * (b[1] - a[1]), a[0] + t * (b[0] - a[0]), d,
                    along + t * math.sqrt(seg2))
        along += math.sqrt(seg2)
    return best


def si_level(si):
    return "high" if si >= 2 else "medium" if si >= 1 else "low"


def build_points(route):
    """สร้าง feature จุดสมมติ — คิด SI/EPDO ด้วยสูตรเดียวกับ build_risk_points.py"""
    features = []
    for s in SITES:
        total = s["accident_count"]
        pi = s["serious_injury"] + s["minor_injury"]
        si = round((s["fatal_crashes"] + pi) / total, 4)
        # ระดับต้องออกมาจากสูตร และตรงกับสีวงที่ผู้ใช้วาด
        assert si_level(si) == s["level"], f"{s['id']} SI {si} ไม่ตรงกับระดับ {s['level']}"
        loss = (
            s["deaths"] * COST["death"]
            + s["serious_injury"] * COST["serious"]
            + s["minor_injury"] * COST["minor"]
        )
        lat, lng, moved, along = snap_to_route(s["lat"], s["lng"], route)
        lat, lng = round(lat, 6), round(lng, 6)
        pattern = "single" if s["single_count"] > s["multi_count"] else "multiple"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [lng, lat]},
            "properties": {
                "id": s["id"],
                "unit_type": "cluster",
                "centroid": [lat, lng],
                "radius_m": 60.0,
                "province": s["province"],
                "road": s["road"],
                "road_label": s["landmark"],
                "road_label_source": "record",
                "landmark": s["landmark"],
                "accident_count": total,
                "deaths": s["deaths"],
                "serious_injury": s["serious_injury"],
                "minor_injury": s["minor_injury"],
                "fatal_crashes": s["fatal_crashes"],
                "injured_total": pi,
                "severity_index": si,
                "level": s["level"],
                "economic_loss": loss,
                "epdo_million": round(loss / 1_000_000, 3),
                "single_count": s["single_count"],
                "multi_count": s["multi_count"],
                "single_pct": round(100 * s["single_count"] / total, 1),
                "multi_pct": round(100 * s["multi_count"] / total, 1),
                "pattern": pattern,
                "top_cause": s["top_cause"],
                "road_feature": s["road_feature"],
                "crash_pattern": s["crash_pattern"],
                "road_type": "ถนนสายหลัก",
                "speed_limit": 60,
                "synthetic": True,
                "source_page": s["page"],
                "snap_distance_m": round(moved, 1),
                "route_m": round(along),
            },
        })

    real = json.loads(REAL_DATA.read_text(encoding="utf-8"))["features"]
    for f in real:
        if f["properties"]["id"] in REAL_ZONE_IDS:
            lng, lat = f["geometry"]["coordinates"][:2]
            _, _, moved, along = snap_to_route(lat, lng, route)
            f["properties"].update({"synthetic": False, "route_m": round(along),
                                    "route_offset_m": round(moved, 1)})
            features.append(f)

    features.sort(key=lambda f: f["properties"]["route_m"])
    return features


def min_gap(features):
    """ระยะห่างเส้นตรงที่สั้นที่สุดระหว่างจุดเสี่ยงคู่ใด ๆ"""
    best = None
    for i in range(len(features)):
        for j in range(i + 1, len(features)):
            a = features[i]["geometry"]["coordinates"]
            b = features[j]["geometry"]["coordinates"]
            d = haversine_m(a[1], a[0], b[1], b[0])
            if best is None or d < best:
                best = d
    return best


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    route = fetch_route()
    features = build_points(route)
    props = [f["properties"] for f in features]
    gap = min_gap(features)

    totals = {k: sum(p[k] for p in props)
              for k in ("accident_count", "deaths", "serious_injury", "minor_injury")}

    points_fc = {
        "type": "FeatureCollection",
        "calibration": {
            "version": VERSION,
            "generated_at": GENERATED_AT,
            "synthetic": True,
            "warning": "ข้อมูลสมมติสำหรับทดสอบระบบเท่านั้น ไม่ใช่สถิติอุบัติเหตุจริง "
                       "(ยกเว้น zone_279 ซึ่งคัดลอกจากชุดหลัก)",
            "purpose": "ขับทดสอบอุปกรณ์บนถนนจริง วงรอบติวานนท์-นครอินทร์-พิบูลสงคราม-"
                       "วงศ์สว่าง-กรุงเทพนนทบุรี",
            "site": "ถนนติวานนท์และถนนเชื่อมต่อ จังหวัดนนทบุรี",
            "source": "วงกลมที่ผู้ใช้วาดบนภาพหน้าจอแผนที่ snap เข้าเส้นทาง OSRM",
            "scoring_method": "severity_index",
            "si_formula": "(F + PI) / Total Accident",
            "level_breaks": [1.0, 2.0],
            "level_break_method": "fixed_si_cutoff",
            "cost_per_person_thb": COST,
            "epdo_weights_million_per_person": {"fatal": 6.7, "serious": 2.0, "minor": 0.058},
            "marker_position": "on_route",
            "analysis_units": len(features),
            "zones": len(features),
            "risk_points": totals["accident_count"],
            "levels": {lv: sum(1 for p in props if p["level"] == lv)
                       for lv in ("high", "medium", "low")},
            "min_gap_m": round(gap, 1),
            "recommended_alert_radius_m": 500,
            "recommended_exit_radius_m": 600,
            "overall": {
                "risk_points": totals["accident_count"],
                "deaths": totals["deaths"],
                "serious_injury": totals["serious_injury"],
                "minor_injury": totals["minor_injury"],
                "epdo_total_million": round(sum(p["epdo_million"] for p in props), 3),
            },
        },
        "features": features,
    }

    route_fc = {
        "type": "FeatureCollection",
        "name": "tiwanon_test_loop",
        "properties": {
            "description": (
                "วงรอบทดสอบ: ติวานนท์ลงใต้ -> นครอินทร์ -> พิบูลสงคราม ผ่าน มจพ. -> วงศ์สว่าง "
                "-> กรุงเทพ-นนทบุรี -> ติวานนท์ขึ้นเหนือ กลับจุดเริ่ม"
            ),
            "road": "ถนนติวานนท์และถนนเชื่อมต่อ",
            "length_km": round(line_length_m(route) / 1000, 2),
            "calibration": VERSION,
            "targets": [
                {"id": p["id"], "level": p["level"], "landmark": p.get("landmark") or p["road_label"]}
                for p in props
            ],
        },
        "features": [{
            "type": "Feature",
            "properties": {"kind": "route"},
            "geometry": {"type": "LineString", "coordinates": route},
        }],
    }

    out_points = ROOT / "data" / "risk_points_tiwanon_test.geojson"
    out_route = ROOT / "data" / "mock_route_tiwanon.geojson"
    out_points.write_text(json.dumps(points_fc, ensure_ascii=False, indent=1), encoding="utf-8")
    out_route.write_text(json.dumps(route_fc, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"เขียน {out_points.name}: {len(features)} จุด, ระยะห่างต่ำสุด {gap:.0f} ม.")
    print(f"เขียน {out_route.name}: {len(route)} node, ยาว {route_fc['properties']['length_km']} กม.")
    for f in features:
        p = f["properties"]
        lng, lat = f["geometry"]["coordinates"][:2]
        moved = p.get("route_offset_m", p.get("snap_distance_m"))
        print(f"  - {p['id']:<9} {p['level']:<6} SI={p['severity_index']:<6} "
              f"กม.{p['route_m'] / 1000:<6.2f} ขยับ {moved:>5} ม. {lat:.6f},{lng:.6f} "
              f"{p.get('landmark') or p['road_label']}")


if __name__ == "__main__":
    main()
