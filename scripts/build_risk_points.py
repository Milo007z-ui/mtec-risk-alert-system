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
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# ---------------------------------------------------------------- ค่าคงที่รอบ calibration

CALIB_VERSION = "v2568-r12"          # แท็กรอบข้อมูล — เปลี่ยนเมื่อ recalibrate รอบถัดไป
RECALIB_POLICY = "ทุก 6 เดือน"      # รอบที่กำหนดล่วงหน้า (Fixed-Schedule)

# จุดตัดระดับ ต่ำ/ปานกลาง/สูง บนค่า SI — เลขกลมคงที่ ไม่ใช่เปอร์เซ็นไทล์
#
# ที่มา: การกระจายของ SI มีค่าคงที่เป็นช่วงยาว ("ที่ราบ") พาดผ่าน SI=1 และ SI=2
# จุดตัดจึงตกบนรอยต่อธรรมชาติของข้อมูล ไม่ใช่เลขที่ตั้งขึ้นลอยๆ
#     ที่ราบ SI=1.000 : รอบ 1 ปี P74-P80  ·  รอบ 3 ปี P71-P80
#     ที่ราบ SI=2.000 : รอบ 1 ปี P98      ·  รอบ 3 ปี P95-P96
# (เอกสารรุ่นก่อนอ้าง P56-P84 / P88-P90 ซึ่งเป็นค่าของรอบ eps=200 ม. 1,234 หน่วย
#  ไม่ใช่ค่าของโมเดลปัจจุบัน — ดู docs/risk-score-criteria.md หัวข้อ 4)
#
# ทำไมไม่ใช้เปอร์เซ็นไทล์: ค่า SI ซ้ำกันหนามาก (รอบ 3 ปี SI=1.000 ค่าเดียวกิน 10.3%
# ของทั้งชุด) จุดตัดเชิงเปอร์เซ็นไทล์จะตกกลางกองค่าซ้ำ ทำให้วงที่มี SI เท่ากันเป๊ะ
# ถูกจัดคนละระดับ · และเกณฑ์เปอร์เซ็นไทล์ไม่เสถียรข้ามรอบข้อมูล: พอข้อมูลเพิ่มจาก
# 1 ปีเป็น 3 ปี จุดตัดที่ P95 ขยับจาก SI 1.667 -> 2.000 (+20%) ขณะที่จุดตัดคงที่
# SI=1/SI=2 ขยับตำแหน่งเพียง ~3 จุดเปอร์เซ็นไทล์ จึงเทียบข้ามรอบเวลาได้
#
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

    def _code(v):
        """รหัสสายทางมาเป็นตัวเลข — ตัด .0 ท้ายทิ้งให้จับคู่กันได้ ("9" ไม่ใช่ "9.0")"""
        if isinstance(v, float) and not np.isnan(v) and v.is_integer():
            v = int(v)
        return _text(v)

    def _km(v):
        try:
            km = float(v)
        except (TypeError, ValueError):
            return None
        return None if np.isnan(km) else km

    return {
        "lat": lat, "lng": lng,
        "province": _text(r.get("จังหวัด")),
        "road": _text(r.get("สายทาง")),
        # รหัสสายทาง + หลัก กม. เก็บไว้เติม "ชื่อสายทางสำหรับแสดงผล" ให้แถวที่ต้นทาง
        # ไม่ได้กรอกคอลัมน์ "สายทาง" (ดู fill_road_labels) — ไม่ได้ใช้จัดกลุ่มหรือคิด SI
        "route_code": _code(r.get("รหัสสายทาง")),
        "km": _km(r.get("KM")),
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
        props = {
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
        }
        # ชื่อที่เติมให้พ่วงมาเฉพาะจุดที่ต้นทางไม่ได้กรอก "สายทาง" มา — ไฟล์นี้มีหลักหมื่น
        # ฟีเจอร์ ทุกฟิลด์ที่เพิ่มคือขนาดที่เบราว์เซอร์ต้องโหลด จึงไม่เขียนค่าที่ซ้ำกับ road
        # (ฝั่งหน้าเว็บอ่านเป็น road_label ?? road)
        if e["road_label_source"] != "record":
            props["road_label"] = e["road_label"]
            props["road_label_source"] = e["road_label_source"]
        features.append({
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [round(e["lng"], 6), round(e["lat"], 6)]},
            "properties": props,
        })
    return {"type": "FeatureCollection", "calibration": calibration, "features": features}


def haversine_m(lat1, lng1, lat2, lng2):
    p1, p2 = radians(lat1), radians(lat2)
    dp, dl = radians(lat2 - lat1), radians(lng2 - lng1)
    a = sin(dp / 2) ** 2 + cos(p1) * cos(p2) * sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_M * asin(sqrt(a))


def _unit_from_members(uid, kind, members):
    n = len(members)
    deaths = sum(m["deaths"] for m in members)
    serious = sum(m["serious"] for m in members)
    minor = sum(m["minor"] for m in members)
    single_cnt = sum(1 for m in members if m["vehicles"] <= 1)
    road_type = mode_of([m["road_type"] for m in members], exclude=("ไม่ระบุ",))
    kms = [m["km"] for m in members if m["km"] is not None]
    si, fatal_crashes, injured = severity_index(members)
    economic_loss = deaths * COST_DEATH + serious * COST_SERIOUS + minor * COST_MINOR

    if single_cnt / n * 100 >= 60:
        pattern = "single"
    elif (n - single_cnt) / n * 100 >= 60:
        pattern = "multiple"
    else:
        pattern = "mixed"

    # ตำแหน่งหมุดของคลัสเตอร์ = medoid คือ "จุดอุบัติเหตุจริงที่อยู่ใกล้จุดกึ่งกลางที่สุด"
    # ไม่ใช่จุดกึ่งกลางเลขคณิต (centroid) ตรง ๆ
    #
    # เหตุผล: centroid เป็นค่าเฉลี่ยของพิกัด เมื่อกลุ่มทอดยาวตามถนนที่โค้ง ค่าเฉลี่ย
    # จะตกลงไปใน "ช่องว่างในเส้นโค้ง" ซึ่งไม่ใช่ตำแหน่งบนถนน (เหมือนหาจุดกึ่งกลาง
    # ของเกือกม้าแล้วได้จุดที่ลอยอยู่กลางอากาศ) — คลัสเตอร์ ดาวคะนอง-แสมดำ ที่โค้ง
    # 8.3 x 6.7 กม. เคยได้หมุดที่ห่างจากจุดอุบัติเหตุที่ใกล้ที่สุดถึง 134 เมตร
    #
    # medoid แก้ปัญหานี้เพราะเลือกจากจุดอุบัติเหตุจริง หมุดจึงอยู่บนถนนเสมอ
    # (ระยะจากหมุดถึงสมาชิกที่ใกล้ที่สุด = 0 ม. ทุกคลัสเตอร์ตามนิยาม)
    lat_c = sum(m["lat"] for m in members) / n
    lng_c = sum(m["lng"] for m in members) / n
    medoid = min(members, key=lambda m: haversine_m(lat_c, lng_c, m["lat"], m["lng"]))
    lat_m, lng_m = medoid["lat"], medoid["lng"]

    # รัศมีของคลัสเตอร์ = ระยะจากหมุดถึงสมาชิกที่ไกลที่สุด
    # วัดจากหมุดจริงที่วาดบนแผนที่ ตัวเลขในป๊อปอัปจึงตรงกับสิ่งที่ผู้ใช้เห็น
    radius_m = round(max(haversine_m(lat_m, lng_m, m["lat"], m["lng"]) for m in members), 1)

    return {
        "id": uid,
        "unit_type": kind,
        "lat": round(lat_m, 6),
        "lng": round(lng_m, 6),
        # จุดกึ่งกลางเลขคณิตเก็บไว้เทียบ/ตรวจย้อนหลัง ไม่ได้ใช้วาดหรือแจ้งเตือน
        "centroid": [round(lat_c, 6), round(lng_c, 6)],
        "radius_m": radius_m,
        "province": mode_of([m["province"] for m in members]),
        "road": mode_of([m["road"] for m in members], exclude=("ไม่ระบุ",)),
        # อ้างอิงตำแหน่งบนสายทางของสมาชิก — ใช้เติม road_label เมื่อ road = "ไม่ระบุ"
        # และใช้บอกช่วง กม. ในป๊อปอัป
        "route_code": mode_of([m["route_code"] for m in members], exclude=("ไม่ระบุ",)),
        "km_min": round(min(kms), 3) if kms else None,
        "km_max": round(max(kms), 3) if kms else None,
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


# ---------------------------------------------------------------- ชื่อสายทางสำหรับแสดงผล

# ข้อมูลต้นทางมีแถวที่คอลัมน์ "สายทาง" ว่าง (3 ปี 2566-2568: 3,938 จาก 13,525 แถว)
# ทั้งที่แถวเดียวกันกรอก "รหัสสายทาง" กับ "KM" มาครบ คลัสเตอร์ที่สมาชิกเป็นแถวแบบนี้
# ทั้งวงจึงขึ้นหัวป๊อปอัปว่า "ไม่ระบุ" ทั้งที่รู้อยู่ว่าอยู่บนสายทางไหน หลัก กม. เท่าไร
#
# วิธีเติม: ยืมชื่อจาก "จุดที่ใกล้ที่สุดซึ่งอยู่บนรหัสสายทางเดียวกันและมีชื่อกรอกไว้"
# ในชุดข้อมูลเดียวกัน — ไม่ได้ดึงชื่อจากแหล่งภายนอกและไม่ได้ตั้งชื่อขึ้นเอง ชื่อที่ได้
# จึงเป็นชื่อตอนของสายทางตามที่ต้นทางกรอกไว้ในระเบียนอื่นของสายทางเดียวกัน
#
# ทำไมต้องใช้ "จุดที่ใกล้ที่สุด" ไม่ใช่ฐานนิยมของรหัสสายทาง: หนึ่งรหัสมีหลายตอนและ
# คนละชื่อ (ทล.9 มีทั้ง "บางปะอิน - แขวงรามอินทรา" และ "แขวงรามอินทรา - บางพลี")
# ถ้าใช้ฐานนิยมจะติดชื่อตอนผิดให้ครึ่งหนึ่งของสายทาง
#
# ข้อจำกัดที่ต้องระบุในรายงาน: ชื่อที่เติมเป็นค่าอนุมาน ไม่ใช่ค่าที่ต้นทางกรอกมา
# จึงแยกเก็บเป็น road_label (สำหรับแสดงผล) ต่างหากจาก road (ค่าดิบที่ใช้จัดกลุ่ม)
# และติดที่มาไว้ใน road_label_source ทุกจุด

# ระยะไกลสุดที่ยังยอมยืมชื่อจากจุดอื่นบนรหัสสายทางเดียวกัน
# 2 กม. มาจากการกระจายจริงของข้อมูล 3 ปี: จุดที่ยืมชื่อได้มีระยะถึงจุดอ้างอิงมัธยฐาน
# 63 ม. และเกือบทั้งหมดต่ำกว่า 300 ม. ไกลกว่านี้ถือว่าเป็นคนละตอนของสายทางเดียวกัน
# จึงเลิกเดาชื่อแล้วถอยไปใช้ "รหัสสายทาง + หลัก กม." ซึ่งเป็นค่าที่ต้นทางกรอกมาจริง
ROAD_LABEL_MAX_DIST_M = 2000

# คำนำหน้ารหัสสายทางตามหน่วยงานเจ้าของทาง — เรียงจากคำที่เจาะจงกว่าไปหากว้างกว่า
# ("ทางหลวงชนบท" ต้องมาก่อน "ทางหลวง" เหมือนกฎเพดานความเร็ว)
ROUTE_PREFIX_RULES = [("ชนบท", "ทช."), ("พิเศษ", "ทางพิเศษสาย"), ("ทางหลวง", "ทล.")]


def route_ref(route_code, road_type, km_min=None, km_max=None):
    """ป้ายอ้างอิงตำแหน่งบนสายทาง เช่น "ทล.9 กม.9-35" — None เมื่อไม่มีรหัสสายทาง"""
    if not route_code or route_code == "ไม่ระบุ":
        return None
    prefix = "สายทาง "
    for keyword, p in ROUTE_PREFIX_RULES:
        if keyword in (road_type or ""):
            prefix = p
            break
    ref = f"{prefix}{route_code}"
    if km_min is None:
        return ref
    # ทศนิยม 1 ตำแหน่งพอสำหรับบอกตำแหน่งบนสายทาง และตัด .0 ทิ้งให้อ่านง่าย
    # (ปัดเป็นจำนวนเต็มจะทำให้ช่วงสั้น ๆ กลายเป็น "กม.1-1" ซึ่งไม่ได้บอกอะไร)
    lo = f"{km_min:.1f}".rstrip("0").rstrip(".")
    hi = lo if km_max is None else f"{km_max:.1f}".rstrip("0").rstrip(".")
    return f"{ref} กม.{lo}" if lo == hi else f"{ref} กม.{lo}-{hi}"


def build_road_name_index(events):
    """
    ดัชนี "รหัสสายทาง -> จุดที่มีชื่อสายทางกรอกไว้" สำหรับค้นจุดที่ใกล้ที่สุด

    เก็บเป็น numpy array เพราะต้องวัดระยะจากทุกจุดที่ยังไม่มีชื่อไปยังทุกจุดอ้างอิง
    ของรหัสเดียวกัน (หลักพันคู่ต่อรหัส) — วนทีละคู่ด้วย haversine_m จะช้าเกินไป
    """
    by_code = {}
    for e in events:
        if e["road"] != "ไม่ระบุ" and e["route_code"] != "ไม่ระบุ":
            by_code.setdefault(e["route_code"], []).append(e)
    return {
        code: (np.array([m["lat"] for m in ms]), np.array([m["lng"] for m in ms]),
               [m["road"] for m in ms])
        for code, ms in by_code.items()
    }


def _nearest_named(index, route_code, lat, lng):
    """(ชื่อสายทาง, ระยะเป็นเมตร) ของจุดที่มีชื่อซึ่งใกล้ที่สุดบนรหัสสายทางเดียวกัน"""
    entry = index.get(route_code)
    if entry is None:
        return None, None
    lats, lngs, names = entry
    p1, p2 = radians(lat), np.radians(lats)
    dp, dl = p2 - p1, np.radians(lngs - lng)
    a = np.sin(dp / 2) ** 2 + cos(p1) * np.cos(p2) * np.sin(dl / 2) ** 2
    dist = 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))
    i = int(np.argmin(dist))
    return names[i], float(dist[i])


def road_label_for(index, item, km_min=None, km_max=None):
    """
    คืน (ชื่อสำหรับแสดงผล, ที่มา) ของจุดหนึ่ง ไล่ตามลำดับความน่าเชื่อถือ

      record        - ต้นทางกรอกชื่อสายทางมาเอง (ใช้ตามนั้น ไม่แตะ)
      nearest_road  - ยืมชื่อจากจุดที่ใกล้ที่สุดบนรหัสสายทางเดียวกัน (<= 2 กม.)
      route_ref     - ไม่มีจุดอ้างอิงใกล้พอ ใช้ "รหัสสายทาง + หลัก กม." แทนชื่อ
      unknown       - ไม่มีแม้แต่รหัสสายทาง -> คงคำว่า "ไม่ระบุ" ไว้ตามเดิม
    """
    if item["road"] != "ไม่ระบุ":
        return item["road"], "record"
    name, dist = _nearest_named(index, item["route_code"], item["lat"], item["lng"])
    if name is not None and dist <= ROAD_LABEL_MAX_DIST_M:
        return name, "nearest_road"
    ref = route_ref(item["route_code"], item["road_type"], km_min, km_max)
    if ref:
        return ref, "route_ref"
    return "ไม่ระบุ", "unknown"


def fill_road_labels(events, units):
    """
    เติม road_label / road_label_source ให้ทุกเหตุการณ์และทุกหน่วยวิเคราะห์

    ต้องเรียก **หลัง** cluster_units เสมอ — การจัดกลุ่มชั้นที่ 2 แยกกลุ่มด้วยค่าดิบ
    road ถ้าเติมชื่อก่อนจัดกลุ่ม สมาชิกของแต่ละกลุ่มจะเปลี่ยน ผลทั้งชุด (จำนวน
    คลัสเตอร์, SI, ระดับ) จะไม่ตรงกับ calibration ที่ล็อกไว้แล้ว ฟังก์ชันนี้จึงเป็น
    การ "ติดป้ายชื่อ" อย่างเดียว ไม่แตะตัวเลขใด ๆ
    """
    index = build_road_name_index(events)

    for e in events:
        e["road_label"], e["road_label_source"] = road_label_for(index, e, e["km"], e["km"])

    for u in units:
        u["road_label"], u["road_label_source"] = road_label_for(
            index, u, u["km_min"], u["km_max"])
        u["road_ref"] = route_ref(u["route_code"], u["road_type"], u["km_min"], u["km_max"])


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

    # ติดป้ายชื่อสายทางหลังจัดกลุ่มเสร็จแล้วเท่านั้น (ดูเหตุผลใน fill_road_labels)
    fill_road_labels(events, all_units)

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
    unnamed = [u for u in clusters if u["road"] == "ไม่ระบุ"]
    by_src = {k: sum(1 for u in unnamed if u["road_label_source"] == k)
              for k in ("nearest_road", "route_ref", "unknown")}
    print(f"ชื่อสายทาง: ต้นทางไม่ได้กรอก {len(unnamed)} คลัสเตอร์ -> "
          f"ยืมชื่อจากจุดข้างเคียงรหัสเดียวกัน {by_src['nearest_road']} · "
          f"ใช้รหัสสายทาง+กม. {by_src['route_ref']} · "
          f"เหลือ 'ไม่ระบุ' {by_src['unknown']}")
    if clusters:
        print(f"  คลัสเตอร์ใหญ่ที่สุด {max(u['accident_count'] for u in clusters)} จุดเสี่ยง")

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
        print(f"  SI {u['severity_index']:>6.2f}  {u['road_label'][:40]:<40} ({u['province']}) "
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
        "level_breaks": [SI_BREAK_LOW, SI_BREAK_HIGH],
        "level_break_method": "fixed_si_cutoff",
        "marker_position": "medoid",
        # การเติมชื่อสายทางเป็นขั้นตอนติดป้ายหลังจัดกลุ่ม ไม่กระทบตัวเลขชุดใดในนี้
        "road_label_fill": {
            "max_borrow_dist_m": ROAD_LABEL_MAX_DIST_M,
            "by_source": {k: sum(1 for u in units if u["road_label_source"] == k)
                          for k in ("record", "nearest_road", "route_ref", "unknown")},
        },
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
    def ev(deaths=0, serious=0, minor=0, vehicles=2, road="ถนน ก", code="9", km=10.0):
        return {"lat": 13.7, "lng": 100.5, "province": "กรุงเทพมหานคร", "road": road,
                "cause": "ขับเร็ว", "location_type": "ทางตรง", "road_type": "ทางหลวง",
                "crash_pattern": "ชนท้าย", "vehicles": vehicles,
                "route_code": code, "km": km,
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

    # 10) หมุดต้องตรงกับพิกัดของสมาชิกจริงเสมอ (medoid ไม่ใช่ centroid)
    def at(lat, lng):
        e = ev()
        e["lat"], e["lng"] = lat, lng
        return e

    # สามจุดวางเป็นมุมฉาก — centroid จะตกกลางช่องว่าง ไม่ตรงกับจุดใดเลย
    corner = [at(13.700, 100.500), at(13.700, 100.520), at(13.720, 100.500)]
    u2 = _unit_from_members("t", "cluster", corner)
    coords = {(m["lat"], m["lng"]) for m in corner}
    assert (u2["lat"], u2["lng"]) in coords, (u2["lat"], u2["lng"])
    # centroid ที่เก็บไว้ต้องไม่ตรงกับหมุด (ยืนยันว่าสองค่านี้ต่างกันจริง)
    assert u2["centroid"] != [u2["lat"], u2["lng"]]
    # รัศมีต้องวัดจากหมุด ไม่ใช่จาก centroid
    far = max(haversine_m(u2["lat"], u2["lng"], m["lat"], m["lng"]) for m in corner)
    assert abs(u2["radius_m"] - round(far, 1)) < 0.2, (u2["radius_m"], far)

    # 11) เพดานความเร็วตามประเภทสายทาง
    assert speed_limit_for("ทางหลวงพิเศษระหว่างเมือง") == 100   # 'พิเศษ' ต้องมาก่อน 'ทางหลวง'
    assert speed_limit_for("ทางหลวงแผ่นดิน") == 90
    assert speed_limit_for("ทางหลวงชนบท") == 80
    assert speed_limit_for("ไม่ระบุ") == SPEED_LIMIT_DEFAULT

    # 12) ช่วง กม. ของคลัสเตอร์มาจากสมาชิกจริง และรหัสสายทางใช้ฐานนิยม
    u3 = _unit_from_members("t", "cluster", [ev(km=5.0), ev(km=9.5), ev(km=7.0)])
    assert (u3["km_min"], u3["km_max"]) == (5.0, 9.5), (u3["km_min"], u3["km_max"])
    assert u3["route_code"] == "9"

    # 13) ป้ายอ้างอิงสายทาง — คำนำหน้าตามหน่วยงาน และย่อเมื่อเป็น กม. เดียว
    assert route_ref("9", "ทางหลวง", 9.2, 35.4) == "ทล.9 กม.9.2-35.4"
    assert route_ref("9", "ทางหลวงชนบท", 5.0, 5.0) == "ทช.9 กม.5"
    assert route_ref("3481", "ทางหลวง", 1.031, 1.4) == "ทล.3481 กม.1-1.4"
    assert route_ref("ไม่ระบุ", "ทางหลวง", 1.0, 2.0) is None

    # 14) เติมชื่อสายทาง — จุดที่ต้นทางกรอกชื่อมาแล้วต้องไม่ถูกแตะ
    def at(lat, lng, **kw):
        e = ev(**kw)
        e["lat"], e["lng"] = lat, lng
        return e

    named = at(13.700, 100.500, road="ทล.9 ตอนหนึ่ง")
    near = at(13.7005, 100.500, road="ไม่ระบุ")          # ห่าง ~55 ม. รหัสเดียวกัน
    far = at(13.900, 100.500, road="ไม่ระบุ")            # ห่าง ~22 กม. เกินเพดาน
    other = at(13.7005, 100.500, road="ไม่ระบุ", code="ไม่ระบุ")
    idx = build_road_name_index([named])
    assert road_label_for(idx, named) == ("ทล.9 ตอนหนึ่ง", "record")
    assert road_label_for(idx, near) == ("ทล.9 ตอนหนึ่ง", "nearest_road")
    assert road_label_for(idx, far, 40.0, 41.25) == ("ทล.9 กม.40-41.2", "route_ref")
    assert road_label_for(idx, other) == ("ไม่ระบุ", "unknown")

    # 15) ติดป้ายแล้วต้องไม่แตะค่าดิบ road ที่ใช้จัดกลุ่ม
    events = [named, near, far, other]
    units = [_unit_from_members("t", "cluster", [near, near, near])]
    fill_road_labels(events, units)
    assert [e["road"] for e in events] == ["ทล.9 ตอนหนึ่ง", "ไม่ระบุ", "ไม่ระบุ", "ไม่ระบุ"]
    assert near["road_label"] == "ทล.9 ตอนหนึ่ง"
    assert units[0]["road"] == "ไม่ระบุ" and units[0]["road_label"] == "ทล.9 ตอนหนึ่ง"
    assert units[0]["road_ref"] == "ทล.9 กม.10"

    print("self-test ผ่านทั้งหมด")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _self_test()
    else:
        main()
