# -*- coding: utf-8 -*-
"""
build_nstda_test_site.py — สร้างชุดข้อมูล "สนามทดสอบ" ในอุทยานวิทยาศาสตร์ประเทศไทย (สวทช.)
คลองหนึ่ง คลองหลวง ปทุมธานี สำหรับทดสอบ GPS จริง + กล้อง EMMA

ผลลัพธ์ 2 ไฟล์:
  data/risk_points_nstda_test.geojson  จุดเสี่ยงสมมติ 8 จุด ครบ 3 ระดับ (ต่ำ/ปานกลาง/สูง)
  data/mock_route_nstda.geojson        เส้นทางวนรอบอุทยานฯ 1 รอบ ผ่านครบ 3 จุดตามลำดับ

⚠️ ข้อมูลในไฟล์นี้เป็น "ข้อมูลสมมติ" ที่แต่งขึ้นเพื่อทดสอบระบบเท่านั้น
   ไม่ใช่สถิติอุบัติเหตุจริงของถนนในอุทยานวิทยาศาสตร์ฯ ห้ามนำไปรายงานปนกับชุด MOT

ทำไมต้องมีชุดนี้แยก:
  ชุดข้อมูลจริง (กทม.+ปริมณฑล) ไม่มีจุดเสี่ยงในเขตอุทยานฯ เลย ออกไปขับทดสอบก็ไม่มีอะไรเตือน
  จึงวางจุดสมมติไว้บนถนนวงรอบของอุทยานฯ เอง ให้ขับวนทดสอบได้ครบทั้งสามระดับในรอบเดียว

เรขาคณิตถนน: ดึงจาก OpenStreetMap (Overpass API) เมื่อ 2026-08-26 แล้ว inline ไว้ที่นี่
  ให้สคริปต์รันซ้ำได้แบบ offline — way id 260103518 (ขาลงฝั่งตะวันตก + ด้านใต้),
  242048982 (ขาขึ้นฝั่งตะวันออก), 256137578 (ขาไปทางตะวันตกด้านเหนือ)
  ถนนในอุทยานฯ เป็น one-way คู่ขนาน เส้นทางนี้จึงวิ่งตามทิศทางที่กฎหมายอนุญาตทั้งรอบ

ระยะเตือน: ถนนวงรอบยาวแค่ ~1.4 กม. รัศมีเตือนของระบบจริง (500 ม.) กว้างกว่าทั้งอุทยานฯ
  ถ้าใช้ค่านั้นทุกจุดจะร้องพร้อมกันตั้งแต่ยังไม่ออกรถ หน้าทดสอบจึงลดเหลือ 60 ม. (ออกที่ 80 ม.)
  รอบแรกมี 3 จุดห่างกัน 277 ม. ใช้ 120 ม. ได้สบาย — รอบนี้เพิ่มอีก 5 จุดบนถนนฝั่งตะวันตก
  ที่ห่างกันเพียง 71-125 ม. จึงต้องลดรัศมีลงตาม
  - รัศมีที่ "วงไม่ซ้อนกันเลย" ต้องแคบกว่าครึ่งหนึ่งของระยะห่างคู่ที่ใกล้สุด = 35 ม.
    ซึ่งที่ 30 กม./ชม. เหลือเวลาแค่ 4 วินาที พูดประโยคเตือนไม่ทันจบก่อนถึงจุด
  - จึงเลือก 60 ม. (~7 วินาทีที่ 30 กม./ชม.) ยอมให้วงซ้อนกันบ้าง แล้วให้กติกากันพูดทับ
    ใน alert.js จัดคิวเสียงเอง (เตือนจุดใกล้สุดก่อน จุดถัดไปรอจนพูดจบ ระดับสูงกว่าตัดคิวได้)
  - ยังรับประกันว่า "ตอนรถอยู่ตรงจุดใด ไม่มีจุดอื่นอยู่ในรัศมี" เพราะ 60 < 71
  ปรับสดหน้างานได้จาก URL: test-nstda.html?alert=40&exit=60

รันซ้ำ:  python scripts/build_nstda_test_site.py
"""

import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSION = "nstda-test-r1"
GENERATED_AT = "2026-08-26"

# --------------------------------------------------------------------------
# เรขาคณิตถนนวงรอบอุทยานวิทยาศาสตร์ฯ  [lng, lat] เรียงตามทิศทางเดินรถ (one-way)
# --------------------------------------------------------------------------

# ฝั่งตะวันตก มุ่งลงใต้ แล้วเลี้ยวไปตามถนนด้านใต้ มุ่งตะวันออก (OSM way 260103518)
WEST_SOUTH = [
    [100.600870, 14.080431], [100.600886, 14.080355], [100.600927, 14.080113],
    [100.600917, 14.079849], [100.600884, 14.079460], [100.600852, 14.078821],
    [100.600808, 14.078172], [100.600785, 14.077699], [100.600779, 14.077602],
    [100.600725, 14.076747], [100.600736, 14.076687], [100.600766, 14.076627],
    [100.600822, 14.076564], [100.600906, 14.076538], [100.601339, 14.076511],
    [100.601574, 14.076500], [100.601675, 14.076498], [100.601901, 14.076486],
    [100.602376, 14.076465], [100.603403, 14.076403],
]

# ฝั่งตะวันออก มุ่งขึ้นเหนือ (OSM way 242048982)
EAST_NORTH = [
    [100.603469, 14.076460], [100.603518, 14.077593], [100.603519, 14.077835],
    [100.603519, 14.077906], [100.603515, 14.078145], [100.603518, 14.078292],
    [100.603520, 14.078361], [100.603521, 14.078698], [100.603492, 14.078931],
    [100.603451, 14.079132], [100.603397, 14.079480], [100.603275, 14.080267],
]

# ด้านเหนือ มุ่งตะวันตก จนบรรจบหัวถนนฝั่งตะวันตกที่ (100.600886, 14.080355)
# (OSM way 256137578 — ตัดที่ node ร่วม ไม่เอาส่วนหางที่วนออกนอกวงรอบ)
NORTH_WEST = [
    [100.603202, 14.080351], [100.602734, 14.080411], [100.601492, 14.080482],
    [100.601466, 14.080484], [100.600886, 14.080355],
]

# จุดเริ่มขับ: ถนนฝั่งตะวันออก ช่วงหน้า Multi Purpose Building (index 1 ของ EAST_NORTH)
#
# รอบแรกเริ่มที่กลางถนนฝั่งตะวันตก แต่พอเพิ่ม 5 จุดลงถนนเส้นนั้น ทุก node บนถนน
# ฝั่งตะวันตกก็อยู่ห่างจุดเสี่ยงไม่ถึง 70 ม. — จอดตั้งต้นตรงไหนก็โดนเตือนทันทีที่กดเริ่ม
# ช่องว่างที่ยาวพอเหลืออยู่บนถนนฝั่งตะวันออกเท่านั้น (node นี้ห่างจุดใกล้สุด 123 ม.)
START_INDEX = 1

# --------------------------------------------------------------------------
# จุดเสี่ยงสมมติ 8 จุด — พิกัดทุกจุดเป็น node จริงบนถนน (ไม่ใช่กลางสนามหญ้า)
#   3 จุดแรก (low/medium/high) = รอบแรก กระจายรอบวง
#   5 จุด w1-w5 = ผู้ใช้วาดตำแหน่งมาเองบนถนนฝั่งตะวันตก (เรียงเหนือ -> ใต้)
#     สีที่วาดมา: w1 เขียว w2 ส้ม w3 เขียว w4 เขียว w5 ส้ม
#     snap เข้า node ถนนที่ใกล้ที่สุดของเลนขาลง (OSM way 260103518) คลาดจากที่วาด 7-28 ม.
#     ยกเว้น w1 กับ w5 ที่ผู้ใช้วงขอให้ย้ายไปอีกฝั่งถนน = เลนขาขึ้น (OSM way 242045242)
#     ถนนคู่ขนานห่างกันแค่ 8-11 ม. รถบนเลนขาลงจึงยังเข้ารัศมี 60 ม. เตือนได้เหมือนเดิม
# ตัวเลขอุบัติเหตุตั้งให้ SI ตกคนละช่วงของจุดตัดจริง: <1 ต่ำ, 1-2 ปานกลาง, >=2 สูง
# --------------------------------------------------------------------------
SITES = [
    {
        "id": "nstda_low",
        "lng": 100.602376, "lat": 14.076465,
        "level": "low",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศใต้",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศใต้ (หน้าอาคาร สวทช.)",
        "landmark": "หน้าอาคาร สวทช. / ศูนย์หนังสือ",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 0, "minor_injury": 2,
        "single_count": 3, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด",
        "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "พลิกคว่ำ/ตกถนนในทางตรง",
        "speed_limit": 30,
    },
    {
        "id": "nstda_medium",
        "lng": 100.603521, "lat": 14.078698,
        "level": "medium",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันออก",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันออก (หน้าศูนย์ประชุมฯ)",
        "landmark": "ทางแยกเข้าศูนย์ประชุมอุทยานวิทยาศาสตร์ประเทศไทย",
        "accident_count": 5, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 3, "minor_injury": 4,
        "single_count": 1, "multi_count": 4,
        "top_cause": "ตัดหน้ากระชั้นชิด",
        "road_feature": "ทางแยก+ทางร่วม",
        "crash_pattern": "ชนด้านข้างบริเวณทางแยก",
        "speed_limit": 30,
    },
    {
        "id": "nstda_high",
        "lng": 100.601492, "lat": 14.080482,
        "level": "high",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศเหนือ",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศเหนือ (หน้า MTEC Pilot Plant)",
        "landmark": "หน้าโรงงานต้นแบบ MTEC / BIOTEC Pilot Plant",
        "accident_count": 3, "fatal_crashes": 2, "deaths": 2,
        "serious_injury": 2, "minor_injury": 3,
        "single_count": 1, "multi_count": 2,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด",
        "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนท้ายในทางตรง",
        "speed_limit": 30,
    },
    # ---- 5 จุดบนถนนฝั่งตะวันตก ตามที่ผู้ใช้วาดมา (เรียงเหนือ -> ใต้) ----
    {
        "id": "nstda_w1",
        # ย้ายมาเลนขาขึ้น (ฝั่งตรงข้าม) ตามที่ผู้ใช้วงมา — ห่างจากจุดเดิม 8.2 ม.
        "lng": 100.600852, "lat": 14.080101,
        "level": "low",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก เลนขาขึ้น (หน้า NECTEC Pilot Plant)",
        "landmark": "หน้าโรงงานต้นแบบ NECTEC ปลายถนนฝั่งตะวันตก",
        "accident_count": 3, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 0, "minor_injury": 2,
        "single_count": 2, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด",
        "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "พลิกคว่ำ/ตกถนนในทางตรง",
        "speed_limit": 30,
    },
    {
        "id": "nstda_w2",
        "lng": 100.600884, "lat": 14.079460,
        "level": "medium",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก (ข้าง Betagro Science Center)",
        "landmark": "ทางเข้าออก Betagro Science Center / อาคาร MTEC",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 2, "minor_injury": 3,
        "single_count": 1, "multi_count": 3,
        "top_cause": "ตัดหน้ากระชั้นชิด",
        "road_feature": "ทางเชื่อมเข้าออกพื้นที่ข้างทาง",
        "crash_pattern": "ชนด้านข้างขณะเลี้ยวเข้าออก",
        "speed_limit": 30,
    },
    {
        "id": "nstda_w3",
        "lng": 100.600852, "lat": 14.078821,
        "level": "low",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก (หน้าอาคาร MTEC)",
        "landmark": "หน้าอาคาร MTEC ฝั่งถนนตะวันตก",
        "accident_count": 5, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 0, "minor_injury": 3,
        "single_count": 2, "multi_count": 3,
        "top_cause": "ขับตามกระชั้นชิด",
        "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "ชนท้ายในทางตรง",
        "speed_limit": 30,
    },
    {
        "id": "nstda_w4",
        "lng": 100.600785, "lat": 14.077699,
        "level": "low",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก (หน้าอาคาร BIOTEC)",
        "landmark": "หน้าอาคาร BIOTEC / ศูนย์ฝึกอบรม",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 1, "minor_injury": 1,
        "single_count": 3, "multi_count": 1,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด",
        "road_feature": "ทางตรง+ไม่มีความลาดชัน",
        "crash_pattern": "พลิกคว่ำ/ตกถนนในทางตรง",
        "speed_limit": 30,
    },
    {
        "id": "nstda_w5",
        # ย้ายมาเลนขาขึ้น (ฝั่งตรงข้าม) ตามที่ผู้ใช้วงมา — ห่างจากจุดเดิม 10.6 ม.
        "lng": 100.600650, "lat": 14.076685,
        "level": "medium",
        "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก",
        "road_label": "ถนนวงรอบอุทยานวิทยาศาสตร์ ด้านทิศตะวันตก เลนขาขึ้น (โค้งมุมตะวันตกเฉียงใต้)",
        "landmark": "ทางโค้งมุมตะวันตกเฉียงใต้ ก่อนเลี้ยวเข้าถนนด้านใต้",
        "accident_count": 4, "fatal_crashes": 0, "deaths": 0,
        "serious_injury": 2, "minor_injury": 3,
        "single_count": 1, "multi_count": 3,
        "top_cause": "ขับรถเร็วเกินอัตรากำหนด",
        "road_feature": "ทางโค้ง",
        "crash_pattern": "เสียหลักออกนอกทางในทางโค้ง",
        "speed_limit": 30,
    },
]

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


def build_points():
    """สร้าง feature จุดเสี่ยง — คิด SI/EPDO ด้วยสูตรเดียวกับ build_risk_points.py"""
    features = []
    for s in SITES:
        total = s["accident_count"]
        pi = s["serious_injury"] + s["minor_injury"]
        si = round((s["fatal_crashes"] + pi) / total, 4)
        loss = (
            s["deaths"] * COST["death"]
            + s["serious_injury"] * COST["serious"]
            + s["minor_injury"] * COST["minor"]
        )
        pattern = "single" if s["single_count"] > s["multi_count"] else "multiple"
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [s["lng"], s["lat"]]},
            "properties": {
                "id": s["id"],
                "unit_type": "cluster",
                "centroid": [s["lat"], s["lng"]],
                "radius_m": 60.0,
                "province": "ปทุมธานี",
                "road": s["road"],
                "road_label": s["road_label"],
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
                "road_type": "ถนนภายในหน่วยงาน",
                "speed_limit": s["speed_limit"],
                "synthetic": True,
            },
        })
    return features


def build_route():
    """วงรอบอุทยานฯ 1 รอบ เริ่ม-จบที่ถนนฝั่งตะวันออก ตามทิศทาง one-way จริง"""
    coords = (
        EAST_NORTH[START_INDEX:]          # ตะวันออกขึ้นเหนือ (ผ่านจุดปานกลาง)
        + NORTH_WEST                      # ด้านเหนือไปตะวันตก (ผ่านจุดสูง)
        + WEST_SOUTH[2:]                  # ตะวันตกลงใต้ (ผ่าน w1-w5) -> ด้านใต้ (ผ่านจุดต่ำ)
        + EAST_NORTH[:START_INDEX + 1]    # ตะวันออกขึ้นเหนือ กลับถึงจุดเริ่ม
    )
    # ตัด node ซ้ำที่รอยต่อออก กัน mock GPS ค้างพิกัดเดิมสองเฟรม
    dedup = [coords[0]]
    for c in coords[1:]:
        if c != dedup[-1]:
            dedup.append(c)
    return dedup


def min_gap(features):
    """ระยะห่างเส้นตรงที่สั้นที่สุดระหว่างจุดเสี่ยงคู่ใด ๆ — ใช้ตรวจว่ารัศมีเตือนไม่ซ้อนกัน"""
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
    features = build_points()
    gap = min_gap(features)
    alert_radius = 60
    # เงื่อนไขที่ต้องจริงเสมอ: ตอนรถอยู่ตรงจุดใดจุดหนึ่ง ต้องไม่มีจุดอื่นอยู่ในรัศมีเตือน
    # ไม่งั้นเสียงสองจุดจะชนกันที่พิกัดเดียว แยกไม่ออกว่าเตือนจุดไหน
    assert alert_radius < gap, f"รัศมีเตือน {alert_radius} ม. กว้างเกินระยะห่างจุด {gap:.0f} ม."

    totals = {
        "accident_count": sum(f["properties"]["accident_count"] for f in features),
        "deaths": sum(f["properties"]["deaths"] for f in features),
        "serious_injury": sum(f["properties"]["serious_injury"] for f in features),
        "minor_injury": sum(f["properties"]["minor_injury"] for f in features),
    }

    points_fc = {
        "type": "FeatureCollection",
        "calibration": {
            "version": VERSION,
            "generated_at": GENERATED_AT,
            "synthetic": True,
            "warning": "ข้อมูลสมมติสำหรับทดสอบระบบเท่านั้น ไม่ใช่สถิติอุบัติเหตุจริง",
            "purpose": "สนามทดสอบ GPS + เสียงเตือน + กล้อง EMMA ในอุทยานวิทยาศาสตร์ประเทศไทย",
            "site": "อุทยานวิทยาศาสตร์ประเทศไทย (สวทช.) คลองหนึ่ง คลองหลวง ปทุมธานี",
            "source": "วางจุดเองบน node ถนนจริงจาก OpenStreetMap",
            "scoring_method": "severity_index",
            "si_formula": "(F + PI) / Total Accident",
            "level_breaks": [1.0, 2.0],
            "level_break_method": "fixed_si_cutoff",
            "cost_per_person_thb": COST,
            "epdo_weights_million_per_person": {"fatal": 6.7, "serious": 2.0, "minor": 0.058},
            "marker_position": "on_road_node",
            "analysis_units": len(features),
            "zones": len(features),
            "risk_points": totals["accident_count"],
            "levels": {
                "high": sum(1 for f in features if f["properties"]["level"] == "high"),
                "medium": sum(1 for f in features if f["properties"]["level"] == "medium"),
                "low": sum(1 for f in features if f["properties"]["level"] == "low"),
            },
            "min_gap_m": round(gap, 1),
            "recommended_alert_radius_m": alert_radius,
            "recommended_exit_radius_m": 80,
            "non_overlapping_radius_m": round(gap / 2, 1),
            "overall": {
                "risk_points": totals["accident_count"],
                "deaths": totals["deaths"],
                "serious_injury": totals["serious_injury"],
                "minor_injury": totals["minor_injury"],
                "epdo_total_million": round(
                    sum(f["properties"]["epdo_million"] for f in features), 3
                ),
            },
        },
        "features": features,
    }

    route = build_route()
    route_fc = {
        "type": "FeatureCollection",
        "name": "nstda_test_loop",
        "properties": {
            "description": (
                "เส้นทางทดสอบวนรอบอุทยานวิทยาศาสตร์ประเทศไทย 1 รอบ ตามทิศทาง one-way จริง "
                "เริ่มกลางถนนฝั่งตะวันตก ผ่านจุดเสี่ยงครบทั้ง 8 จุด แล้วกลับจุดเริ่ม"
            ),
            "road": "ถนนวงรอบอุทยานวิทยาศาสตร์ประเทศไทย",
            "length_km": round(line_length_m(route) / 1000, 2),
            "calibration": VERSION,
            "targets": [
                {"id": s["id"], "level": s["level"], "landmark": s["landmark"]} for s in SITES
            ],
        },
        "features": [{
            "type": "Feature",
            "properties": {"kind": "route"},
            "geometry": {"type": "LineString", "coordinates": route},
        }],
    }

    out_points = ROOT / "data" / "risk_points_nstda_test.geojson"
    out_route = ROOT / "data" / "mock_route_nstda.geojson"
    out_points.write_text(json.dumps(points_fc, ensure_ascii=False, indent=1), encoding="utf-8")
    out_route.write_text(json.dumps(route_fc, ensure_ascii=False, indent=1), encoding="utf-8")

    print(f"เขียน {out_points.name}: {len(features)} จุด, ระยะห่างต่ำสุด {gap:.0f} ม. "
          f"(รัศมีที่ใช้ {alert_radius} ม. · วงไม่ซ้อนกันเลยต้อง < {gap / 2:.0f} ม.)")
    print(f"เขียน {out_route.name}: {len(route)} node, ยาว {route_fc['properties']['length_km']} กม.")
    for f in features:
        p = f["properties"]
        print(f"  - {p['id']:<14} {p['level']:<6} SI={p['severity_index']:<6} {p['landmark']}")


if __name__ == "__main__":
    main()
