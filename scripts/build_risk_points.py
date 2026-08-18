"""
build_risk_points.py — สร้างไฟล์จุดเสี่ยง data/risk_points_bkk_metro.geojson (โมเดล v3)

Batch calibration job: รันตามรอบ Fixed-Schedule ที่กำหนดเท่านั้น (แนะนำทุก 6 เดือน)
ห้ามรันใหม่ทุกครั้งที่มี request — ผลต้องถูก "ล็อก" เป็นเวอร์ชัน calibration
เพื่อให้เปรียบเทียบข้ามช่วงเวลาได้ ไม่ลอยขึ้นลง
(หลักการ: Srinivasan & Carter 2011, NCDOT — Fixed-Schedule Recalibration หน้า 49-51)

ขั้นตอน:
  1. อ่านข้อมูลอุบัติเหตุจาก Excel 6 ชีต (กรุงเทพฯ+ปริมณฑล ปี 2568, 1 ชีตต่อจังหวัด)
  2. จัดกลุ่มเหตุการณ์ที่เกิดใกล้กันด้วย DBSCAN (eps 200 ม., min 3)
     หน่วยวิเคราะห์ = core cluster ทุกกลุ่ม + noise point ทุกจุด (นับเป็นจุดเสี่ยงเดี่ยว)
  3. คำนวณดัชนีความรุนแรงอุบัติเหตุต่อจุด  SI = (F + PI) / Total Accident
       F  = จำนวน "ครั้ง" ของอุบัติเหตุที่มีผู้เสียชีวิต (ไม่ใช่จำนวนผู้เสียชีวิต)
       PI = จำนวน "คน" ที่บาดเจ็บรวม (สาหัส + เล็กน้อย)
       Total Accident = จำนวนอุบัติเหตุทั้งหมดในจุดนั้น
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

CALIB_VERSION = "v2568-r7"          # แท็กรอบข้อมูล — เปลี่ยนเมื่อ recalibrate รอบถัดไป
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
OUTPUT_FILE = BASE_DIR / "data" / "risk_points_bkk_metro.geojson"   # หน่วยวิเคราะห์ 1,234
ACCIDENT_FILE = BASE_DIR / "data" / "accident_points.geojson"       # จุดเสี่ยง 4,460
CALIB_DIR = BASE_DIR / "data" / "calibrations"

BANGKOK_METRO_PROVINCES = [
    "กรุงเทพมหานคร", "นนทบุรี", "ปทุมธานี",
    "สมุทรปราการ", "นครปฐม", "สมุทรสาคร",
]

# DBSCAN: รัศมี 200 ม. — ค่าฐานจากข้อมูลจริงคือค่ามัธยฐานระยะเพื่อนบ้านลำดับที่ 3
# เท่ากับ 97.08 ม. แล้วปรับกว้างขึ้นเป็น 200 ม. ตามตำแหน่งจุดข้อศอกของ sorted
# k-distance graph (Ester, Kriegel, Sander & Xu 1996)
# ขั้นต่ำ 3 เหตุการณ์ตามนิยาม Black Spot
EPS_METERS = 200
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


def cluster_units(events, eps_meters, min_samples):
    """
    DBSCAN บนพิกัด (haversine) -> หน่วยวิเคราะห์ทั้งหมด

    คำศัพท์ที่ต้องแยกให้ชัด (ผู้ใช้กำหนด):
      - **จุดเสี่ยง** = 1 จุด : 1 อุบัติเหตุ  -> ทั้งชุดมี 4,460 จุด
      - **คลัสเตอร์** = วงที่ DBSCAN รวมอุบัติเหตุ >= min_samples ครั้งเข้าด้วยกัน
      - **หน่วยวิเคราะห์** = คลัสเตอร์ทุกกลุ่ม + อุบัติเหตุเดี่ยวที่ไม่เกาะกลุ่ม (noise)
        เป็นหน่วยที่ใช้คำนวณ SI และจัดระดับ ไม่ใช่ "จุดเสี่ยง"

    คืน (units, assignments) โดย assignments[i] = id ของหน่วยวิเคราะห์ที่อุบัติเหตุ
    ลำดับที่ i สังกัดอยู่ ใช้ผูกจุดเสี่ยงรายอุบัติเหตุกลับเข้าหน่วยวิเคราะห์
    """
    coords = np.array([[radians(e["lat"]), radians(e["lng"])] for e in events])
    labels = DBSCAN(
        eps=eps_meters / EARTH_RADIUS_M, min_samples=min_samples, metric="haversine"
    ).fit(coords).labels_

    assignments = [None] * len(events)
    groups = []
    for cluster_id in sorted(set(labels) - {-1}):
        uid = f"zone_{cluster_id}"
        members = []
        for i, l in enumerate(labels):
            if l == cluster_id:
                members.append(events[i])
                assignments[i] = uid
        groups.append((uid, "cluster", members))
    for i, l in enumerate(labels):
        if l == -1:
            uid = f"spot_{i}"
            assignments[i] = uid
            groups.append((uid, "noise", [events[i]]))

    units = [_unit_from_members(uid, kind, members) for uid, kind, members in groups]
    return units, assignments


def accident_points_geojson(events, assignments, units, calibration):
    """
    จุดเสี่ยงรายอุบัติเหตุ — 1 feature : 1 อุบัติเหตุ (ทั้งชุด 4,460 จุด)

    แต่ละจุดพ่วง `unit_id` และ `level` ของหน่วยวิเคราะห์ที่สังกัด เพื่อให้แผนที่
    ระบายสีจุดตามระดับของคลัสเตอร์ที่จุดนั้นอยู่ได้ โดยไม่ต้องคำนวณซ้ำฝั่งเบราว์เซอร์
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
                "unit_id": uid,
                "unit_type": u["unit_type"],
                "level": u["level"],            # ระดับของหน่วยวิเคราะห์ที่สังกัด
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

    units, assignments = cluster_units(events, EPS_METERS, MIN_SAMPLES)
    clusters = [u for u in units if u["unit_type"] == "cluster"]
    noise = [u for u in units if u["unit_type"] == "noise"]
    in_cluster = sum(u["accident_count"] for u in clusters)
    print(f"DBSCAN (eps {EPS_METERS} ม., min {MIN_SAMPLES})")
    print(f"  จุดเสี่ยง (1 จุด : 1 อุบัติเหตุ) {len(events)} จุด")
    print(f"  หน่วยวิเคราะห์รวม {len(units)} หน่วย = คลัสเตอร์ {len(clusters)} กลุ่ม "
          f"(ครอบคลุม {in_cluster} อุบัติเหตุ) + อุบัติเหตุเดี่ยว {len(noise)} จุด")
    if clusters:
        print(f"  กลุ่มใหญ่ที่สุด {max(u['accident_count'] for u in clusters)} ครั้ง")

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

    print("Top 5 จุดเสี่ยงตาม SI:")
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
        "dbscan": {"eps_m": EPS_METERS, "min_samples": MIN_SAMPLES},
        "scoring_method": "severity_index",
        "si_formula": "(F + PI) / Total Accident",
        "cost_per_person_thb": {"death": COST_DEATH, "serious": COST_SERIOUS,
                                "minor": COST_MINOR},
        "epdo_weights_million_per_person": {"fatal": 6.7, "serious": 2.0, "minor": 0.058},
        "level_breaks": [SI_BREAK_LOW, SI_BREAK_HIGH],
        "level_break_method": "fixed_si_cutoff",
        # คำศัพท์: จุดเสี่ยง = 1 จุด : 1 อุบัติเหตุ (4,460) · หน่วยวิเคราะห์ = คลัสเตอร์ + เดี่ยว
        "risk_points": len(events),
        "analysis_units": len(units),
        "zones": len(units),          # ชื่อเดิม เก็บไว้ให้ของเก่าอ่านได้
        "core_clusters": len(clusters),
        "noise_points": len(noise),
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
    print(f"บันทึก {OUTPUT_FILE.relative_to(BASE_DIR)} ({len(units)} หน่วยวิเคราะห์)")

    # จุดเสี่ยงรายอุบัติเหตุ — ไฟล์นี้คือ "จุดเสี่ยง" ตามนิยาม 1 จุด : 1 อุบัติเหตุ
    with open(ACCIDENT_FILE, "w", encoding="utf-8") as f:
        json.dump(accident_points_geojson(events, assignments, units, calibration),
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

    # 10) เพดานความเร็วตามประเภทสายทาง
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
