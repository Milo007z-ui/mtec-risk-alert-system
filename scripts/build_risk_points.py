"""
build_risk_points.py — สร้างไฟล์จุดเสี่ยง data/risk_points_bkk_metro.geojson (โมเดล v3)

Batch calibration job: รันตามรอบ Fixed-Schedule ที่กำหนดเท่านั้น (แนะนำทุก 6 เดือน)
ห้ามรันใหม่ทุกครั้งที่มี request — ผลต้องถูก "ล็อก" เป็นเวอร์ชัน calibration
เพื่อให้เปรียบเทียบข้ามช่วงเวลาได้ ไม่ลอยขึ้นลง
(หลักการ: Srinivasan & Carter 2011, NCDOT — Fixed-Schedule Recalibration หน้า 49-51)

ขั้นตอน:
  1. อ่านข้อมูลอุบัติเหตุจาก Excel 6 ชีต (กรุงเทพฯ+ปริมณฑล ปี 2568, 1 ชีตต่อจังหวัด)
  2. จัดกลุ่มจุดเสี่ยงด้วย DBSCAN สองชั้น (eps 400 ม., min 3)
     ชั้นแรกทั้งพื้นที่ ชั้นสองแยกตามสายทาง -> ทุกคลัสเตอร์อยู่บนสายทางเดียว
     หน่วยวิเคราะห์ = คลัสเตอร์เท่านั้น — จุดเสี่ยงเดี่ยว (noise) ไม่เข้านิยาม
     Black Spot ที่ต้องเกิดซ้ำ >= 3 ครั้ง จึงไม่นำมาจัดระดับ แต่ยังนับใน
     สถิติภาพรวม (calibration.overall) เพื่อไม่ให้ความสูญเสียหายไปจากรายงาน
  3. คำนวณดัชนีความรุนแรงอุบัติเหตุต่อจุด  SI = (F + PI) / Total Accident
       F  = จำนวน "ครั้ง" ของอุบัติเหตุที่มีผู้เสียชีวิต (ไม่ใช่จำนวนผู้เสียชีวิต)
       PI = จำนวน "คน" ที่บาดเจ็บรวม (สาหัส + เล็กน้อย)
       Total Accident = จำนวนจุดเสี่ยงทั้งหมดในหน่วยนั้น
  4. จำแนก 3 ระดับด้วยจุดตัดคงที่: ต่ำ SI < 1 · ปานกลาง 1 ≤ SI < 2 · สูง SI ≥ 2
  5. บันทึก GeoJSON + snapshot calibration (data/calibrations/<version>.json)

โมเดลนี้แทนที่โมเดล v2 (คะแนน 4 เกณฑ์ × 25% เต็ม 100) ทั้งหมดตั้งแต่ v2568-r7
เพื่อให้ตรงกับรายงานโครงงานที่ใช้ Severity Index เป็นเกณฑ์จำแนกระดับ
โค้ดและ snapshot ของโมเดล v2 ยังอยู่ใน git history และ data/calibrations/v2568-r1..r5

ใช้: py scripts/build_risk_points.py            # สร้างไฟล์
     py scripts/build_risk_points.py --selftest # ตรวจสูตรทั้งหมด
"""

import json
import sys
from datetime import datetime, timezone
from math import asin, ceil, cos, radians, sin, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN, KMeans

# ---------------------------------------------------------------- ค่าคงที่รอบ calibration

CALIB_VERSION = "v2568-r11"          # แท็กรอบข้อมูล — เปลี่ยนเมื่อ recalibrate รอบถัดไป
RECALIB_POLICY = "ทุก 6 เดือน"      # รอบที่กำหนดล่วงหน้า (Fixed-Schedule)

# จุดตัดระดับ ต่ำ/ปานกลาง/สูง บนค่า SI — เลขกลมคงที่
# ที่มา: การกระจายของ SI มีค่าคงที่เป็นช่วงยาวรอบ SI=1 และ SI=2 (เปอร์เซ็นไทล์ P56-P84
# ให้ค่า SI=1.000 เท่ากัน และ P88-P90 ให้ค่า SI=2.000 เท่ากัน) จุดตัดสองค่านี้จึงตรงกับ
# รอยต่อธรรมชาติของข้อมูล ไม่ใช่เลขที่ตั้งขึ้นลอยๆ
# ข้อแลกเปลี่ยนที่ต้องระบุในรายงาน: ยังเป็นเลขที่เลือกด้วยดุลพินิจ ไม่มีทฤษฎีกำหนดตายตัว
SI_BREAK_LOW = 1.0
SI_BREAK_HIGH = 2.0

BASE_DIR = Path(__file__).resolve().parent.parent
XLSX_FILE = BASE_DIR / "data" / "accident2025_1.xlsx"
OUTPUT_FILE = BASE_DIR / "data" / "risk_points_bkk_metro.geojson"   # หน่วยวิเคราะห์ 847
ACCIDENT_FILE = BASE_DIR / "data" / "accident_points.geojson"       # จุดเสี่ยง 4,460
CALIB_DIR = BASE_DIR / "data" / "calibrations"

BANGKOK_METRO_PROVINCES = [
    "กรุงเทพมหานคร", "นนทบุรี", "ปทุมธานี",
    "สมุทรปราการ", "นครปฐม", "สมุทรสาคร",
]

# DBSCAN: รัศมี 400 ม. — ค่าฐานจากข้อมูลจริงคือค่ามัธยฐานระยะเพื่อนบ้านลำดับที่ 3
# เท่ากับ 97.08 ม. แล้วปรับกว้างขึ้นตามตำแหน่งจุดข้อศอกของ sorted k-distance graph
# (Ester, Kriegel, Sander & Xu 1996) — ผู้ใช้เลือก 400 ม. เพื่อให้หน่วยวิเคราะห์
# ครอบคลุมช่วงถนนหนึ่งช่วง (ระดับ "ช่วงทาง" ไม่ใช่รายจุด)
# ขั้นต่ำ 3 เหตุการณ์ตามนิยาม Black Spot
EPS_METERS = 400
MIN_SAMPLES = 3
EARTH_RADIUS_M = 6371000

# ต้นทุนความสูญเสียต่อราย (บาท) — TDRI, ความสูญเสียทางเศรษฐกิจของอุบัติเหตุทางถนน
# ปีงบประมาณ 2565 (เผยแพร่โดยกรมควบคุมโรค กระทรวงสาธารณสุข)
# ค่าชุดนี้คือน้ำหนัก EPDO 6.7 / 2.0 / 0.058 (ล้านบาทต่อคน) ในหน่วยบาท
# EPDO = 6.7F + 2.0S + 0.058M (ล้านบาท) จึงเท่ากับ economic_loss หารด้วยหนึ่งล้านพอดี
COST_DEATH = 6_700_000
COST_SERIOUS = 2_000_000
COST_MINOR = 58_000

# ระยะห่างระหว่างหมุดตัวแทนของคลัสเตอร์เดียวกัน (เมตร)
# ไม่ใช่พารามิเตอร์ของ DBSCAN และไม่สร้างคลัสเตอร์ใหม่ — เป็นเรื่องการแสดงผลล้วน
# ที่มา: ระบบแจ้งเตือนใช้รัศมี 500 ม. ถ้าปักหมุดห่างกัน 800 ม. วงเตือนของหมุด
# ที่อยู่ติดกันจะต่อเนื่องกันพอดี ไม่เหลือช่องว่างให้รถแล่นผ่านโดยไม่ถูกเตือน
#
# เหตุผลที่ต้องมี: คลัสเตอร์ที่ยืดยาวตามถนน (chaining) มีหมุดจุดกึ่งกลางเพียงจุดเดียว
# ทำให้สมาชิกส่วนใหญ่อยู่นอกรัศมีแจ้งเตือน — รอบ r10 ครอบคลุมเพียง 37.9%
# ของจุดเสี่ยงในคลัสเตอร์ทั้งหมด
MARKER_SPACING_M = 800

# เพดานความเร็วโดยประเภทสายทาง (ใช้แสดงผล/คำแนะนำเท่านั้น ไม่อยู่ในสูตร SI)
SPEED_LIMIT_RULES = [("พิเศษ", 100), ("ชนบท", 80), ("ทางหลวง", 90)]
SPEED_LIMIT_DEFAULT = 80

# ---------------------------------------------------------------- โหลด + ทำความสะอาดข้อมูล


def load_excel_records(path):
    """อ่านทุกชีต (1 ชีตต่อจังหวัด) รวมเป็นรายการเดียว"""
    xl = pd.ExcelFile(path)
    frames = []
    for sheet in xl.sheet_names:
        df = xl.parse(sheet)
        frames.append(df)
    merged = pd.concat(frames, ignore_index=True)
    return merged.to_dict(orient="records")


def clean_points(records):
    """กรองเฉพาะ 6 จังหวัด + มีพิกัด และแปลงเป็นโครงสร้างที่ใช้คำนวณ"""
    points = []
    for r in records:
        if r.get("จังหวัด") not in BANGKOK_METRO_PROVINCES:
            continue
        try:
            lat = float(r["LATITUDE"])
            lng = float(r["LONGITUDE"])
        except (TypeError, ValueError, KeyError):
            continue
        if not lat or not lng or np.isnan(lat) or np.isnan(lng):
            continue
        points.append(_event_from_record(r, lat, lng))
    return points


def _event_from_record(r, lat=None, lng=None):
    def _int(v):
        try:
            n = int(v)
            return n if n >= 0 else 0
        except (TypeError, ValueError):
            return 0

    def _text(v, default="ไม่ระบุ"):
        if v is None or (isinstance(v, float) and np.isnan(v)):
            return default
        s = str(v).strip()
        return s if s else default

    return {
        "lat": lat, "lng": lng,
        "province": _text(r.get("จังหวัด")),
        "road": _text(r.get("สายทาง")),
        "cause": _text(r.get("มูลเหตุสันนิษฐาน")),
        "location_type": _text(r.get("บริเวณที่เกิดเหตุ")),
        "road_type": _text(r.get("สายทางหน่วยงาน")),
        "crash_pattern": _text(r.get("ลักษณะการเกิดเหตุ")),
        "vehicles": _int(r.get("รถที่เกิดเหตุ")),
        "deaths": _int(r.get("ผู้เสียชีวิต")),
        "serious": _int(r.get("ผู้บาดเจ็บสาหัส")),
        "minor": _int(r.get("ผู้บาดเจ็บเล็กน้อย")),
    }


# ---------------------------------------------------------------- ดัชนีความรุนแรง + จัดระดับ


def severity_index(members):
    """
    ดัชนีความรุนแรงอุบัติเหตุ (Severity Index)
      SI = (F + PI) / Total Accident        — ณัฐพงศ์ ซื่อสัตย์ (2558)
      F  = จำนวน "ครั้ง" ของอุบัติเหตุที่มีผู้เสียชีวิตอย่างน้อย 1 ราย
      PI = จำนวน "คน" ที่บาดเจ็บรวม (สาหัส + เล็กน้อย)
    จุดสำคัญที่มักสับสน: F นับเป็นครั้ง แต่ PI นับเป็นคน ตามนิยามต้นฉบับ
    """
    n = len(members)
    fatal_crashes = sum(1 for m in members if m["deaths"] > 0)
    injured = sum(m["serious"] + m["minor"] for m in members)
    return (fatal_crashes + injured) / n, fatal_crashes, injured


def classify_si(si):
    """ต่ำ SI < 1 · ปานกลาง 1 <= SI < 2 · สูง SI >= 2 (ขอบล่างรวมอยู่ในชั้นบน)"""
    if si < SI_BREAK_LOW:
        return "low"
    if si < SI_BREAK_HIGH:
        return "medium"
    return "high"


# ---------------------------------------------------------------- จัดกลุ่ม


def mode_of(values, exclude=()):
    counts = {}
    for v in values:
        if v in exclude:
            continue
        counts[v] = counts.get(v, 0) + 1
    if not counts:
        return "ไม่ระบุ"
    return max(counts, key=counts.get)


def speed_limit_for(road_type):
    for keyword, limit in SPEED_LIMIT_RULES:
        if keyword in (road_type or ""):
            return limit
    return SPEED_LIMIT_DEFAULT


def _dbscan_labels(events, idx, eps_meters, min_samples):
    """รัน DBSCAN บนสมาชิกชุดย่อย คืน labels (-1 = noise)"""
    coords = np.array([[radians(events[i]["lat"]), radians(events[i]["lng"])] for i in idx])
    return DBSCAN(
        eps=eps_meters / EARTH_RADIUS_M, min_samples=min_samples, metric="haversine"
    ).fit(coords).labels_


def cluster_units(events, eps_meters, min_samples):
    """
    DBSCAN สองชั้น -> หน่วยวิเคราะห์ทั้งหมด

    คำศัพท์ที่ต้องแยกให้ชัด (ผู้ใช้กำหนด):
      - **จุดเสี่ยง** = 1 จุด : 1 อุบัติเหตุ  -> ทั้งชุดมี 4,460 จุด
      - **คลัสเตอร์** = วงที่ DBSCAN รวมจุดเสี่ยง >= min_samples จุดเข้าด้วยกัน
      - **หน่วยวิเคราะห์** = คลัสเตอร์เท่านั้น (จุดเสี่ยงเดี่ยวไม่นำมาจัดระดับ)

    ทำไมต้องสองชั้น (ตั้งแต่ v2568-r10):
      ชั้นเดียวทำให้เกิด chaining ข้ามถนน — DBSCAN ใช้ density-connectivity แบบส่งต่อ
      ถ้า A ใกล้ B และ B ใกล้ C จะรวมเป็นกลุ่มเดียวแม้ A กับ C ห่างกันหลายสิบกิโลเมตร
      ย่านที่ถนนขนาน/ตัดกันหนาแน่นจึงถูกรวมเป็นวงเดียวข้ามถนนได้ถึง 11 สายทาง
      (รอบ r9 วงใหญ่สุดมี 994 จุดเสี่ยง รัศมี 21 กม. คร่อม 10 สายทาง และหมุดตัวแทน
      ไปตกนอกแนวถนนของสมาชิกเอง ทำให้ระบบเตือนมีช่องโหว่ยาว 18 กม.)

      ชั้นที่ 1: DBSCAN ทั้งพื้นที่ -> จับบริเวณที่จุดเสี่ยงหนาแน่น
      ชั้นที่ 2: แยกสมาชิกของแต่ละกลุ่มตาม "สายทาง" แล้วรัน DBSCAN ซ้ำในแต่ละสายทาง
                -> ทุกคลัสเตอร์อยู่บนสายทางเดียวเท่านั้น ชื่อถนนในป๊อปอัปจึงตรงกับ
                   สมาชิกทุกจุด ไม่ใช่แค่ฐานนิยม และหมุดตัวแทนอยู่บนแนวถนนจริง

    ข้อจำกัดที่ยังเหลือ: ถนนสายเดียวที่ยาวมากและมีเหตุต่อเนื่องยังลามเป็นโซ่ได้
    (ดูหัวข้อข้อจำกัดใน docs/risk-score-criteria.md)

    คืน (units, assignments) โดย assignments[i] = id ของหน่วยวิเคราะห์ที่จุดเสี่ยง
    ลำดับที่ i สังกัดอยู่ ใช้ผูกจุดเสี่ยงรายอุบัติเหตุกลับเข้าหน่วยวิเคราะห์
    """
    all_idx = list(range(len(events)))
    first = _dbscan_labels(events, all_idx, eps_meters, min_samples)

    assignments = [None] * len(events)
    groups = []
    seq = 0

    for cluster_id in sorted(set(first) - {-1}):
        member_idx = [i for i, l in enumerate(first) if l == cluster_id]

        # ชั้นที่ 2 — แยกตามสายทางแล้วรัน DBSCAN ซ้ำในแต่ละสายทาง
        by_road = {}
        for i in member_idx:
            by_road.setdefault(events[i]["road"], []).append(i)

        for road in sorted(by_road):
            idx = by_road[road]
            if len(idx) < min_samples:
                continue  # เหลือน้อยเกินนิยาม Black Spot -> ตกเป็นจุดเสี่ยงเดี่ยว
            second = _dbscan_labels(events, idx, eps_meters, min_samples)
            for sub_id in sorted(set(second) - {-1}):
                uid = f"zone_{seq}"
                seq += 1
                members = []
                for pos, l in enumerate(second):
                    if l == sub_id:
                        i = idx[pos]
                        members.append(events[i])
                        assignments[i] = uid
                groups.append((uid, "cluster", members))

    # จุดที่ไม่ได้เข้าคลัสเตอร์ใดเลย (noise ชั้นแรก หรือหลุดตอนแยกสายทาง/ชั้นสอง)
    for i in all_idx:
        if assignments[i] is None:
            uid = f"spot_{i}"
            assignments[i] = uid
            groups.append((uid, "noise", [events[i]]))

    units = [_unit_from_members(uid, kind, members) for uid, kind, members in groups]
    return units, assignments


def accident_points_geojson(events, assignments, units, calibration):
    """
    จุดเสี่ยงรายอุบัติเหตุ — 1 feature : 1 อุบัติเหตุ (ทั้งชุด 4,460 จุด)

    จุดที่อยู่ในคลัสเตอร์พ่วง `unit_id` และ `level` ของคลัสเตอร์นั้นมาด้วย เพื่อให้
    แผนที่ระบายสีได้โดยไม่ต้องคำนวณซ้ำฝั่งเบราว์เซอร์

    ส่วนจุดเสี่ยงเดี่ยว (noise) ได้ `level = null` และ `classified = false`
    เพราะไม่เข้านิยาม Black Spot จึงไม่ถูกจัดระดับตั้งแต่ v2568-r9
    """
    by_id = {u["id"]: u for u in units}
    features = []
    for i, (e, uid) in enumerate(zip(events, assignments)):
        u = by_id[uid]
        epdo = (e["deaths"] * COST_DEATH + e["serious"] * COST_SERIOUS
                + e["minor"] * COST_MINOR) / 1_000_000
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(e["lng"], 6), round(e["lat"], 6)]},
            "properties": {
                "id": f"acc_{i}",
                "unit_id": uid if u["unit_type"] == "cluster" else None,
                "unit_type": u["unit_type"],
                # ระดับของคลัสเตอร์ที่สังกัด — จุดเสี่ยงเดี่ยวไม่ถูกจัดระดับ (null)
                "level": u["level"] if u["unit_type"] == "cluster" else None,
                "classified": u["unit_type"] == "cluster",
                "province": e["province"],
                "road": e["road"],
                "cause": e["cause"],
                "road_feature": e["location_type"],
                "crash_pattern": e["crash_pattern"],
                "vehicles": e["vehicles"],
                "deaths": e["deaths"],
                "serious_injury": e["serious"],
                "minor_injury": e["minor"],
                "epdo_million": round(epdo, 4),
            },
        })
    return {"type": "FeatureCollection", "calibration": calibration, "features": features}


def haversine_m(lat1, lng1, lat2, lng2):
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def place_markers(members, spacing_m=MARKER_SPACING_M):
    """
    ตำแหน่งหมุดตัวแทนของคลัสเตอร์ -> [[lat, lng], ...]

    **ไม่ได้แบ่งคลัสเตอร์ใหม่** — คลัสเตอร์ยังเป็นหน่วยเดียว SI/ระดับ/EPDO คิดจาก
    สมาชิกทั้งกลุ่มเหมือนเดิมทุกประการ ฟังก์ชันนี้ตอบแค่คำถามว่า "ควรวาดกลุ่มนี้
    ลงแผนที่ที่ตำแหน่งไหนบ้าง" เพื่อให้ระยะแจ้งเตือนครอบคลุมทั้งกลุ่ม

    กลุ่มที่กระชับ (ความยาวไม่เกิน spacing) ได้หมุดเดียวที่จุดกึ่งกลางเหมือนเดิม
    กลุ่มที่ยืดยาวได้หมุดเพิ่มตามสัดส่วนความยาว โดยใช้ KMeans แบ่งสมาชิกเป็น k ส่วน
    แล้ววางหมุดที่จุดกึ่งกลางของแต่ละส่วน — หมุดจึงเกาะกลุ่มก้อนจริงของอุบัติเหตุ
    ไม่ใช่หารระยะเท่า ๆ กันแบบไม่สนใจการกระจายตัว
    """
    lat_c = sum(m["lat"] for m in members) / len(members)
    lng_c = sum(m["lng"] for m in members) / len(members)
    span = 2 * max(haversine_m(lat_c, lng_c, m["lat"], m["lng"]) for m in members)

    k = max(1, min(len(members), int(ceil(span / spacing_m))))
    if k == 1:
        return [[round(lat_c, 6), round(lng_c, 6)]]

    # แปลงเป็นระยะเมตรรอบจุดกึ่งกลางก่อน เพื่อให้ KMeans วัดระยะได้ถูกสัดส่วน
    scale_lng = cos(radians(lat_c)) * 111_320
    xy = np.array([[(m["lng"] - lng_c) * scale_lng, (m["lat"] - lat_c) * 110_540]
                   for m in members])
    labels = KMeans(n_clusters=k, n_init=4, random_state=0).fit_predict(xy)

    spots = []
    for c in range(k):
        part = [m for m, l in zip(members, labels) if l == c]
        if not part:
            continue
        spots.append([round(sum(m["lat"] for m in part) / len(part), 6),
                      round(sum(m["lng"] for m in part) / len(part), 6)])
    return spots


def _unit_from_members(uid, kind, members):
    n = len(members)
    deaths = sum(m["deaths"] for m in members)
    serious = sum(m["serious"] for m in members)
    minor = sum(m["minor"] for m in members)
    single_cnt = sum(1 for m in members if m["vehicles"] <= 1)
    road_type = mode_of([m["road_type"] for m in members], exclude=("ไม่ระบุ",))
    si, fatal_crashes, injured = severity_index(members)
    economic_loss = deaths * COST_DEATH + serious * COST_SERIOUS + minor * COST_MINOR

    if single_cnt / n * 100 >= 60:
        pattern = "single"
    elif (n - single_cnt) / n * 100 >= 60:
        pattern = "multiple"
    else:
        pattern = "mixed"

    lat_c = sum(m["lat"] for m in members) / n
    lng_c = sum(m["lng"] for m in members) / n
    # รัศมีจริงของคลัสเตอร์ = ระยะจากจุดกึ่งกลางถึงสมาชิกที่ไกลที่สุด
    # ใช้วาด "วง" ครอบจุดอุบัติเหตุบนแผนที่ให้เห็นขอบเขตกลุ่มจริง ไม่ใช่หมุดขนาดคงที่
    radius_m = round(max(haversine_m(lat_c, lng_c, m["lat"], m["lng"]) for m in members), 1)

    return {
        "id": uid,
        "unit_type": kind,
        "lat": round(lat_c, 6),
        "lng": round(lng_c, 6),
        "radius_m": radius_m,
        # ตำแหน่งวาด/แจ้งเตือนของกลุ่มนี้ (1 กลุ่มอาจมีหลายหมุด) — ดู place_markers()
        "markers": place_markers(members) if kind == "cluster" else [[round(lat_c, 6), round(lng_c, 6)]],
        "province": mode_of([m["province"] for m in members]),
        "road": mode_of([m["road"] for m in members], exclude=("ไม่ระบุ",)),
        "accident_count": n,
        "deaths": deaths,
        "serious_injury": serious,
        "minor_injury": minor,
        # ตัวตั้งของสูตร SI เก็บไว้ให้ตรวจย้อนได้ว่าคำนวณมาจากอะไร
        "fatal_crashes": fatal_crashes,
        "injured_total": injured,
        "severity_index": round(si, 4),
        "level": classify_si(si),
        "economic_loss": economic_loss,
        "epdo_million": round(economic_loss / 1_000_000, 4),
        "single_count": single_cnt,
        "multi_count": n - single_cnt,
        "single_pct": round(single_cnt / n * 100, 1),
        "multi_pct": round((n - single_cnt) / n * 100, 1),
        "pattern": pattern,
        "top_cause": mode_of([m["cause"] for m in members], exclude=("ไม่ระบุ",)),
        "road_feature": mode_of([m["location_type"] for m in members], exclude=("ไม่ระบุ",)),
        "crash_pattern": mode_of([m["crash_pattern"] for m in members], exclude=("ไม่ระบุ",)),
        "road_type": road_type,
        "speed_limit": speed_limit_for(road_type),
    }


# ---------------------------------------------------------------- ผลลัพธ์


def to_geojson(units, calibration):
    return {
        "type": "FeatureCollection",
        "calibration": calibration,  # foreign member: ระบุเวอร์ชันที่ใช้คำนวณชุดนี้
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [u["lng"], u["lat"]]},
            "properties": {k: v for k, v in u.items() if k not in ("lat", "lng")},
        } for u in units],
    }


def main():
    print(f"อ่านข้อมูลจาก {XLSX_FILE.name} ...")
    records = load_excel_records(XLSX_FILE)
    print(f"  ทั้งหมด {len(records)} เหตุการณ์ (6 จังหวัด)")

    events = clean_points(records)
    print(f"มีพิกัดใช้ได้ {len(events)} เหตุการณ์")

    all_units, assignments = cluster_units(events, EPS_METERS, MIN_SAMPLES)
    clusters = [u for u in all_units if u["unit_type"] == "cluster"]
    noise = [u for u in all_units if u["unit_type"] == "noise"]
    in_cluster = sum(u["accident_count"] for u in clusters)

    # หน่วยวิเคราะห์ = เฉพาะคลัสเตอร์ (ตั้งแต่ v2568-r9)
    # จุดเสี่ยงเดี่ยว (noise) ไม่เข้านิยาม Black Spot ที่ต้องเกิดซ้ำอย่างน้อย 3 ครั้ง
    # จึงไม่นำมาจัดระดับ แต่ยังนับอยู่ในสถิติภาพรวม (ดู overall ใน calibration)
    # ข้อแลกเปลี่ยนที่ต้องระบุในรายงาน: ผู้เสียชีวิตและความสูญเสียของ noise
    # ไม่ปรากฏในผลจำแนกระดับ ต้องรายงานแยกไว้ไม่ให้หายไปจากข้อสรุป
    units = clusters

    print(f"DBSCAN (eps {EPS_METERS} ม., min {MIN_SAMPLES})")
    print(f"  จุดเสี่ยง (1 จุด : 1 อุบัติเหตุ) {len(events)} จุด")
    print(f"  คลัสเตอร์ {len(clusters)} วง (ครอบคลุม {in_cluster} จุดเสี่ยง "
          f"{in_cluster / len(events) * 100:.1f}%)")
    print(f"  จุดเสี่ยงเดี่ยวที่ไม่เข้าคลัสเตอร์ {len(noise)} จุด -> ไม่นำมาจัดระดับ")
    if clusters:
        print(f"  คลัสเตอร์ใหญ่ที่สุด {max(u['accident_count'] for u in clusters)} จุดเสี่ยง")

    n_markers = sum(len(u["markers"]) for u in units)
    multi = sum(1 for u in units if len(u["markers"]) > 1)
    print(f"  หมุดตัวแทนรวม {n_markers} จุด (ห่างกัน ~{MARKER_SPACING_M} ม.) "
          f"— {multi} คลัสเตอร์ได้หมุดมากกว่า 1 จุด")

    si_values = np.array([u["severity_index"] for u in units])
    counts = {lv: sum(1 for u in units if u["level"] == lv) for lv in ("high", "medium", "low")}
    print(f"SI: mean {si_values.mean():.2f} · median {np.median(si_values):.2f} · "
          f"SD {si_values.std(ddof=1):.2f} · min {si_values.min():.2f} · max {si_values.max():.2f}")
    print(f"จุดตัด: ต่ำ SI<{SI_BREAK_LOW} · ปานกลาง {SI_BREAK_LOW}-{SI_BREAK_HIGH} · สูง SI>={SI_BREAK_HIGH}")
    for lv, label in (("low", "ต่ำ"), ("medium", "ปานกลาง"), ("high", "สูง")):
        print(f"  {label:<9} {counts[lv]:>5} จุด ({counts[lv] / len(units) * 100:.1f}%)")

    epdo_total = sum(u["epdo_million"] for u in units)
    print(f"EPDO รวม {epdo_total:,.2f} ล้านบาท")
    epdo_by_level = {}
    for lv in ("low", "medium", "high"):
        group = [u for u in units if u["level"] == lv]
        total = sum(u["epdo_million"] for u in group)
        epdo_by_level[lv] = {
            "points": len(group),
            "epdo_total_million": round(total, 2),
            "epdo_mean_million": round(total / len(group), 2) if group else 0.0,
        }
        print(f"  {lv:<7} {len(group):>5} จุด · รวม {total:>9,.2f} ลบ. · "
              f"เฉลี่ย {total / len(group) if group else 0:.2f} ลบ./จุด")

    print("Top 5 คลัสเตอร์ตาม SI:")
    for u in sorted(units, key=lambda x: x["severity_index"], reverse=True)[:5]:
        print(f"  SI {u['severity_index']:>6.2f}  {u['road'][:40]:<40} ({u['province']}) "
              f"n={u['accident_count']} ตาย={u['deaths']} [{u['unit_type']}]")

    by_province = {}
    for p in BANGKOK_METRO_PROVINCES:
        group = [u for u in units if u["province"] == p]
        if not group:
            continue
        by_province[p] = {
            "points": len(group),
            "low_pct": round(100 * sum(1 for u in group if u["level"] == "low") / len(group), 1),
            "medium_pct": round(100 * sum(1 for u in group if u["level"] == "medium") / len(group), 1),
            "high_pct": round(100 * sum(1 for u in group if u["level"] == "high") / len(group), 1),
        }

    calibration = {
        "version": CALIB_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recalibration_policy": RECALIB_POLICY,
        "source": XLSX_FILE.name,
        "events_total": len(records),
        "events_with_coords": len(events),
        "dbscan": {"eps_m": EPS_METERS, "min_samples": MIN_SAMPLES,
                   "passes": 2, "second_pass_split_by": "road"},
        "scoring_method": "severity_index",
        "si_formula": "(F + PI) / Total Accident",
        "cost_per_person_thb": {"death": COST_DEATH, "serious": COST_SERIOUS,
                                "minor": COST_MINOR},
        "epdo_weights_million_per_person": {"fatal": 6.7, "serious": 2.0, "minor": 0.058},
        "marker_spacing_m": MARKER_SPACING_M,
        "markers_total": sum(len(u["markers"]) for u in units),
        "level_breaks": [SI_BREAK_LOW, SI_BREAK_HIGH],
        "level_break_method": "fixed_si_cutoff",
        # คำศัพท์: จุดเสี่ยง = 1 จุด : 1 อุบัติเหตุ (4,460) · หน่วยวิเคราะห์ = คลัสเตอร์ + เดี่ยว
        "risk_points": len(events),
        "analysis_units": len(units),            # = คลัสเตอร์เท่านั้น
        "zones": len(units),                     # ชื่อเดิม เก็บไว้ให้ของเก่าอ่านได้
        "core_clusters": len(clusters),
        "noise_points": len(noise),
        "noise_excluded_from_levels": True,
        # สถิติภาพรวมของ "ทุกจุดเสี่ยง" รวม noise — ไว้รายงานคู่กันไม่ให้ความสูญเสียหาย
        "overall": {
            "risk_points": len(events),
            "deaths": sum(e["deaths"] for e in events),
            "serious_injury": sum(e["serious"] for e in events),
            "minor_injury": sum(e["minor"] for e in events),
            "epdo_total_million": round(
                sum(e["deaths"] * COST_DEATH + e["serious"] * COST_SERIOUS
                    + e["minor"] * COST_MINOR for e in events) / 1_000_000, 2),
        },
        "excluded_noise": {
            "risk_points": len(noise),
            "deaths": sum(u["deaths"] for u in noise),
            "serious_injury": sum(u["serious_injury"] for u in noise),
            "minor_injury": sum(u["minor_injury"] for u in noise),
            "epdo_total_million": round(sum(u["epdo_million"] for u in noise), 2),
        },
        "events_in_clusters": in_cluster,
        "largest_cluster_events": max((u["accident_count"] for u in clusters), default=0),
        "levels": counts,
        "si_stats": {
            "mean": round(float(si_values.mean()), 4),
            "median": round(float(np.median(si_values)), 4),
            "sd": round(float(si_values.std(ddof=1)), 4),
            "min": round(float(si_values.min()), 4),
            "max": round(float(si_values.max()), 4),
        },
        "epdo_total_million": round(epdo_total, 2),
        "epdo_by_level": epdo_by_level,
        "by_province": by_province,
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(to_geojson(units, calibration), f, ensure_ascii=False, indent=1)
    print(f"บันทึก {OUTPUT_FILE.relative_to(BASE_DIR)} ({len(units)} คลัสเตอร์)")

    # จุดเสี่ยงรายอุบัติเหตุ — ไฟล์นี้คือ "จุดเสี่ยง" ตามนิยาม 1 จุด : 1 อุบัติเหตุ
    with open(ACCIDENT_FILE, "w", encoding="utf-8") as f:
        json.dump(accident_points_geojson(events, assignments, all_units, calibration),
                  f, ensure_ascii=False, separators=(",", ":"))
    size_mb = ACCIDENT_FILE.stat().st_size / 1_048_576
    print(f"บันทึก {ACCIDENT_FILE.relative_to(BASE_DIR)} "
          f"({len(events)} จุดเสี่ยง, {size_mb:.1f} MB)")

    # เก็บ log ทุกเวอร์ชัน calibration ไว้ตรวจสอบย้อนหลัง
    CALIB_DIR.mkdir(parents=True, exist_ok=True)
    snap = CALIB_DIR / f"{CALIB_VERSION}.json"
    with open(snap, "w", encoding="utf-8") as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)
    print(f"บันทึก snapshot {snap.relative_to(BASE_DIR)}")


# ---------------------------------------------------------------- self-test


def _self_test():
    def ev(deaths=0, serious=0, minor=0, vehicles=2):
        return {"lat": 13.7, "lng": 100.5, "province": "กรุงเทพมหานคร", "road": "ถนน ก",
                "cause": "ขับเร็ว", "location_type": "ทางตรง", "road_type": "ทางหลวง",
                "crash_pattern": "ชนท้าย", "vehicles": vehicles,
                "deaths": deaths, "serious": serious, "minor": minor}

    # 1) SI — F นับเป็น "ครั้ง" ที่มีคนตาย ไม่ใช่จำนวนศพ
    #    2 เหตุการณ์: (ตาย 3 คน) + (เจ็บสาหัส 1 เล็กน้อย 2) -> F=1, PI=3 -> SI=(1+3)/2=2.0
    si, f, pi = severity_index([ev(deaths=3), ev(serious=1, minor=2)])
    assert (si, f, pi) == (2.0, 1, 3), (si, f, pi)

    # 2) SI ของจุดที่ไม่มีใครบาดเจ็บหรือเสียชีวิตเลย = 0
    assert severity_index([ev(), ev(), ev()])[0] == 0.0

    # 3) noise point (N=1) — SI เท่ากับจำนวนผู้บาดเจ็บในเหตุการณ์นั้นตรงๆ
    #    เป็นที่มาของ SI=54 จากอุบัติเหตุรถโดยสารครั้งเดียวที่มีผู้บาดเจ็บ 54 คน
    assert severity_index([ev(minor=54)])[0] == 54.0

    # 4) จัดระดับ — ขอบล่างรวมอยู่ในชั้นบน (SI=1 คือปานกลาง ไม่ใช่ต่ำ)
    assert classify_si(0.0) == "low"
    assert classify_si(0.999) == "low"
    assert classify_si(1.0) == "medium"
    assert classify_si(1.999) == "medium"
    assert classify_si(2.0) == "high"
    assert classify_si(54.0) == "high"

    # 5) มูลค่าความเสียหาย TDRI: 1 ตาย + 1 สาหัส + 1 เล็กน้อย = 8,758,000 บาท
    assert COST_DEATH + COST_SERIOUS + COST_MINOR == 8_758_000

    # 6) น้ำหนัก EPDO (ล้านบาท/คน) ต้องตรงกับต้นทุน TDRI ในหน่วยบาทพอดี
    #    EPDO = 6.7F + 2.0S + 0.058M  <=>  economic_loss / 1,000,000
    assert (COST_DEATH / 1e6, COST_SERIOUS / 1e6, COST_MINOR / 1e6) == (6.7, 2.0, 0.058)

    # 7) หน่วยวิเคราะห์ — ตรวจว่า epdo_million = economic_loss / 1e6 จริง
    u = _unit_from_members("t", "cluster", [ev(deaths=1), ev(serious=1), ev(minor=10)])
    assert u["accident_count"] == 3 and u["deaths"] == 1
    assert u["epdo_million"] == round(u["economic_loss"] / 1e6, 4)
    assert u["severity_index"] == round((1 + 11) / 3, 4)   # F=1, PI=1+10=11
    assert u["level"] == "high"                            # SI=4.0

    # 8) pattern จากสัดส่วนรถคันเดียว/หลายคัน
    assert _unit_from_members("t", "noise", [ev(vehicles=1)])["pattern"] == "single"
    assert _unit_from_members("t", "noise", [ev(vehicles=3)])["pattern"] == "multiple"
    mixed = _unit_from_members("t", "cluster", [ev(vehicles=1), ev(vehicles=3)])
    assert mixed["pattern"] == "mixed", mixed["pattern"]

    # 9) mode_of เว้นค่า 'ไม่ระบุ' เมื่อมีค่าจริงให้เลือก
    assert mode_of(["ไม่ระบุ", "ไม่ระบุ", "ถนน ก"], exclude=("ไม่ระบุ",)) == "ถนน ก"
    assert mode_of(["ไม่ระบุ"], exclude=("ไม่ระบุ",)) == "ไม่ระบุ"

    # 10) หมุดตัวแทน — กลุ่มกระชับได้หมุดเดียว กลุ่มยืดยาวได้หลายหมุด
    tight = [ev(), ev(), ev()]  # พิกัดเดียวกันหมด -> span = 0
    assert len(place_markers(tight)) == 1

    # กลุ่มยาว ~4 กม. (0.036 องศาละติจูด) ที่ spacing 800 ม. ต้องได้หลายหมุด
    def at(dlat):
        e = ev()
        e["lat"] = 13.7 + dlat
        return e
    spread = [at(i * 0.004) for i in range(10)]   # ~0.036 องศา ≈ 4 กม.
    spots = place_markers(spread)
    assert len(spots) >= 4, len(spots)
    # ทุกหมุดต้องอยู่ในช่วงพิกัดของสมาชิกจริง ไม่หลุดออกนอกกลุ่ม
    assert all(13.7 <= la <= 13.7 + 0.036 + 1e-9 for la, _ in spots), spots

    # 11) เพดานความเร็วตามประเภทสายทาง
    assert speed_limit_for("ทางหลวงพิเศษระหว่างเมือง") == 100   # 'พิเศษ' ต้องมาก่อน 'ทางหลวง'
    assert speed_limit_for("ทางหลวงแผ่นดิน") == 90
    assert speed_limit_for("ทางหลวงชนบท") == 80
    assert speed_limit_for("ไม่ระบุ") == SPEED_LIMIT_DEFAULT

    print("self-test ผ่านทั้งหมด")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _self_test()
    else:
        main()
