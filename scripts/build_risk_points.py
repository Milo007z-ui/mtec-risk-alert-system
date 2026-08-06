"""
build_risk_points.py — สร้างไฟล์จุดเสี่ยง data/risk_points_bkk_metro.geojson (โมเดล v2)

Batch calibration job: รันตามรอบ Fixed-Schedule ที่กำหนดเท่านั้น (แนะนำทุก 6 เดือน)
ห้ามรันใหม่ทุกครั้งที่มี request — ผลคะแนนต้องถูก "ล็อก" เป็นเวอร์ชัน calibration
เพื่อให้เปรียบเทียบข้ามช่วงเวลาได้ ไม่ลอยขึ้นลง
(หลักการ: Srinivasan & Carter 2011, NCDOT — Fixed-Schedule Recalibration หน้า 49-51)

ขั้นตอน:
  1. อ่านข้อมูลอุบัติเหตุจาก Excel 6 ชีต (กรุงเทพฯ+ปริมณฑล ปี 2568, 1 ชีตต่อจังหวัด)
  2. จัดกลุ่มเหตุการณ์ที่เกิดใกล้กันเป็น "จุดเสี่ยง" ด้วย DBSCAN (eps 400 ม., min 3)
  3. คำนวณ 4 เกณฑ์ต่อจุด แล้วแปลงเป็น Percentile Rank 0-100 (อันดับเทียบจุดอื่นในรอบ):
       - ความถี่อุบัติเหตุ           (จำนวนครั้ง)
       - มูลค่าความเสียหายเศรษฐกิจ   (บาท — ต้นทุน/ราย: TDRI 2565)
       - Single-Vehicle Crash Ratio (% เหตุที่มีรถ ≤1 คัน)
       - ลักษณะถนน                   (% เหตุที่เกิดบริเวณทางแยก/ทางโค้ง/ทางร่วม/ต่างระดับ)
  4. Risk Score = 0.25×(รวม 4 เกณฑ์) เต็ม 100 แบ่ง 3 ระดับ: ต่ำ ≤40 / กลาง ≤60 / สูง >60
  5. บันทึก GeoJSON + snapshot calibration (data/calibrations/<version>.json)

ใช้: py scripts/build_risk_points.py            # สร้างไฟล์
     py scripts/build_risk_points.py --selftest # ตรวจสูตรทั้งหมด
"""

import json
import sys
from datetime import datetime, timezone
from math import radians
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.cluster import DBSCAN

# ---------------------------------------------------------------- ค่าคงที่รอบ calibration

CALIB_VERSION = "v2568-r5"          # แท็กรอบข้อมูล — เปลี่ยนเมื่อ recalibrate รอบถัดไป
RECALIB_POLICY = "ทุก 6 เดือน"      # รอบที่กำหนดล่วงหน้า (Fixed-Schedule)

# จุดตัดระดับต่ำ/กลาง/สูง — เลขกลมคงที่ (ตั้งแต่ v2568-r3)
# เดิม (r1, r2) ใช้ Jenks Natural Breaks คำนวณจาก Risk Score จริงทุกรอบ (ยังเก็บฟังก์ชัน
# jenks_breaks() ไว้อ้างอิง/self-test) แต่ผู้ใช้ต้องการเกณฑ์ที่อธิบายง่ายกว่าสำหรับพรีเซนต์
# จึงเปลี่ยนมาใช้เลขกลมคงที่แทน — ข้อแลกเปลี่ยน: อธิบายง่าย ("ต่ำกว่า 40 คือต่ำ") แต่ไม่มี
# หลักฐานทางสถิติรองรับตัวเลข 40/60 เจาะจง (ต่างจาก Jenks ที่หาจุดตัดจากความแปรปรวนจริง)
LEVEL_BREAKS = [40.0, 60.0]

# ---- ตารางเกณฑ์ให้คะแนน (banded rubric) — ตั้งแต่ v2568-r4
# รูปแบบ: (ค่าดิบสูงสุดของช่วง, คะแนน) เรียงจากน้อยไปมาก; ค่าที่เกินช่วงสุดท้าย = 25 คะแนน
#
# เดิม (r1-r3) normalize ด้วย Percentile Rank ซึ่งทนต่อ outlier ได้ดีมาก แต่ต้องอธิบายว่า
# "คะแนนคืออันดับเทียบกับจุดอื่น" ซึ่งผู้ใช้เห็นว่าเข้าใจยากเกินไปสำหรับการนำเสนอ
# ตารางเกณฑ์อ่านค่าดิบได้ตรงๆ ("156 ครั้ง เกิน 20 -> 25 คะแนน") และยังทนต่อ outlier
# เพราะช่วงบนสุดเป็นปลายเปิด (จุดที่มี 994 ครั้ง กับ 25 ครั้ง ได้ 25 คะแนนเท่ากัน)
#
# ข้อแลกเปลี่ยนที่ต้องระบุในรายงาน: คะแนนหยาบกว่าเดิมมาก (รวมกันได้เพียง 13 ค่า)
# จุดจำนวนมากจึงได้คะแนนเท่ากันเป๊ะ เรียงลำดับละเอียดไม่ได้เท่า Percentile Rank
# และขีดแบ่งช่วงทั้ง 16 ตัวเป็นดุลพินิจผู้ออกแบบ (expert judgment) อิงการกระจายจริง
# ของข้อมูลรอบนี้ ไม่ใช่ค่าที่มีทฤษฎีกำหนดตายตัว
SCORE_BANDS = {
    # จำนวนอุบัติเหตุ (ครั้ง) — ขั้นต่ำของจุดเสี่ยงคือ 3 ครั้งตามนิยาม Black Spot
    "frequency": [(3, 5), (5, 10), (10, 15), (20, 20)],
    # มูลค่าความเสียหาย (บาท) — 5 แสน ≈ ระดับบาดเจ็บเล็กน้อยหลายราย,
    # 2 ล้าน = สาหัส 1 ราย, 10 ล้าน > เสียชีวิต 1 ราย (TDRI 6.7 ล้าน)
    "economic_loss": [(100_000, 5), (500_000, 10), (2_000_000, 15), (10_000_000, 20)],
    # สัดส่วนอุบัติเหตุรถคันเดียว (%) — สูง = ปัญหาไหล่ทาง/ทางโค้ง (FHWA Roadway Departure)
    "single_vehicle": [(20, 5), (35, 10), (50, 15), (70, 20)],
    # เกณฑ์ 4 ลักษณะถนน: สัดส่วนเหตุที่เกิดบริเวณทางแยก/ทางโค้ง/ทางร่วม/ต่างระดับ (%)
    # 0% = ทางตรงล้วน (TxDOT Conflict Points: ยิ่งมีจุดที่กระแสจราจรตัดกันมาก ยิ่งเสี่ยงชน)
    "geometry": [(0, 5), (5, 10), (15, 15), (30, 20)],
}
BAND_TOP_SCORE = 25                 # คะแนนของช่วงบนสุด (ปลายเปิด) และคะแนนเต็มต่อเกณฑ์

BASE_DIR = Path(__file__).resolve().parent.parent
XLSX_FILE = BASE_DIR / "data" / "accident2025_1.xlsx"
OUTPUT_FILE = BASE_DIR / "data" / "risk_points_bkk_metro.geojson"
CALIB_DIR = BASE_DIR / "data" / "calibrations"

BANGKOK_METRO_PROVINCES = [
    "กรุงเทพมหานคร", "นนทบุรี", "ปทุมธานี",
    "สมุทรปราการ", "นครปฐม", "สมุทรสาคร",
]

# DBSCAN: รัศมี 400 ม. ครอบคลุมช่วงถนนหนึ่งช่วง (จุดเสี่ยงระดับ "ช่วงทาง" ไม่ใช่รายจุด)
# ขั้นต่ำ 3 เหตุการณ์ตามนิยาม Black Spot
EPS_METERS = 400
MIN_SAMPLES = 3
EARTH_RADIUS_M = 6371000

# ต้นทุนความสูญเสียต่อราย (บาท) — TDRI, ความสูญเสียทางเศรษฐกิจของอุบัติเหตุทางถนน
# ปีงบประมาณ 2565 (เผยแพร่โดยกรมควบคุมโรค กระทรวงสาธารณสุข)
COST_DEATH = 6_700_000
COST_SERIOUS = 2_000_000
COST_MINOR = 58_000

# น้ำหนักรวมคะแนน: เท่ากัน 4 × 25% (OECD/JRC 2008 — equal weighting)
W_FREQ = W_ECON = W_SINGLE = W_GEOM = 0.25

# เพดานความเร็วโดยประเภทสายทาง (ใช้แสดงผล/คำแนะนำเท่านั้น ไม่อยู่ในสูตรคะแนน v2)
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


# ---------------------------------------------------------------- เกณฑ์ 4: Geometric Complexity

# จัดกลุ่ม "บริเวณที่เกิดเหตุ" เป็นกลุ่ม conflict ตามสเปก v2
# (mapped=False คือค่าที่ไม่เข้าเงื่อนไข ใช้ fallback NCP อย่างระมัดระวัง
#  และไม่ถูกนับตอนประมาณค่า FI Rate)
GROUP_LABELS = {
    "ncp": "ทางตรง (ไม่มีจุดที่กระแสจราจรตัดกัน)",
    "merging": "ทางโค้ง/ทางร่วม/ทางเชื่อม (Merging)",
    "diverging": "ทางต่างระดับ/Ramps (Diverging)",
    "crossing": "ทางสามแยก/สี่แยก (Crossing)",
}


def conflict_group(location_type):
    """คืน (กลุ่ม, mapped) — ลำดับการเช็กสำคัญ: ต่างระดับ ต้องมาก่อน แยก"""
    t = location_type or ""
    if "ต่างระดับ" in t or "ramp" in t.lower():
        return "diverging", True
    if "สามแยก" in t or "สี่แยก" in t:
        return "crossing", True
    if "โค้ง" in t or "ทางร่วม" in t or "เชื่อม" in t:
        return "merging", True
    if "ทางตรง" in t:
        return "ncp", True
    return "ncp", False  # อื่นๆ / ไม่ระบุ -> fallback ระมัดระวัง


def compute_fi_weights(events):
    """
    น้ำหนักแต่ละกลุ่ม conflict จาก FI Rate ของข้อมูลจริงในไฟล์เอง
    FI = เหตุที่มีผู้บาดเจ็บ/เสียชีวิตอย่างน้อย 1 ราย, weight = FI_rate กลุ่ม / FI_rate NCP
    ประมาณจากเฉพาะเหตุที่ map กลุ่มได้จริง (ไม่รวม 'อื่นๆ/ไม่ระบุ' ที่เป็น fallback)
    """
    tally = {g: {"n": 0, "fi": 0} for g in GROUP_LABELS}
    for e in events:
        group, mapped = conflict_group(e["location_type"])
        if not mapped:
            continue
        tally[group]["n"] += 1
        if e["deaths"] > 0 or e["serious"] > 0 or e["minor"] > 0:
            tally[group]["fi"] += 1

    base_rate = tally["ncp"]["fi"] / tally["ncp"]["n"]
    weights, table = {}, {}
    for g, t in tally.items():
        rate = (t["fi"] / t["n"]) if t["n"] else base_rate
        weights[g] = round(rate / base_rate, 3)
        table[g] = {"n": t["n"], "fi_rate_pct": round(rate * 100, 1), "weight": weights[g]}
    return weights, table


# ---------------------------------------------------------------- ให้คะแนน + จัดระดับ


def band_score(value, bands):
    """
    คะแนนจากตารางเกณฑ์: คืนคะแนนของช่วงแรกที่ value ไม่เกินขีดบน
    ค่าที่เกินทุกช่วง = BAND_TOP_SCORE (ช่วงบนสุดเป็นปลายเปิด จึงทนต่อ outlier)
    """
    for upper, points in bands:
        if value <= upper:
            return points
    return BAND_TOP_SCORE


def percentile_rank(series):
    """
    Percentile Rank 0-100, จัดการ tie ด้วย average rank (OECD/JRC 2008 — Ranking)
    เก็บไว้อ้างอิง/เปรียบเทียบวิธี — ไม่ได้ใช้ใน pipeline แล้วตั้งแต่ v2568-r4
    """
    return series.rank(pct=True, method="average") * 100


def jenks_breaks(values, n_classes=3):
    """
    Jenks Natural Breaks (Fisher's optimal partition แบบ dynamic programming)
    คืนจุดตัด [b1, b2, ...] = ค่าสูงสุดของชั้นที่ 1..k-1 (คลาสเรียงจากค่าน้อยไปมาก)
    """
    v = sorted(float(x) for x in values)
    n = len(v)
    k = min(n_classes, n)
    if k <= 1:
        return []

    csum = [0.0]
    csum2 = [0.0]
    for x in v:
        csum.append(csum[-1] + x)
        csum2.append(csum2[-1] + x * x)

    def sse(i, j):  # ความแปรปรวนรวมของช่วง v[i:j]
        m = j - i
        s = csum[j] - csum[i]
        return (csum2[j] - csum2[i]) - s * s / m

    INF = float("inf")
    dp = [[INF] * (n + 1) for _ in range(k + 1)]
    cut = [[0] * (n + 1) for _ in range(k + 1)]
    dp[0][0] = 0.0
    for c in range(1, k + 1):
        for j in range(c, n + 1):
            for i in range(c - 1, j):
                cand = dp[c - 1][i] + sse(i, j)
                if cand < dp[c][j]:
                    dp[c][j] = cand
                    cut[c][j] = i

    starts = []
    j = n
    for c in range(k, 0, -1):
        starts.append(cut[c][j])
        j = starts[-1]
    starts = starts[::-1]  # [0, เริ่มชั้น2, เริ่มชั้น3, ...]
    return [round(v[s - 1], 2) for s in starts[1:]]


def classify(score, breaks):
    """breaks = [b1, b2]: score<=b1 ต่ำ, <=b2 กลาง, มากกว่านั้น สูง"""
    if score <= breaks[0]:
        return "low"
    if score <= breaks[1]:
        return "medium"
    return "high"


# ---------------------------------------------------------------- จัดกลุ่ม + ให้คะแนน


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


def cluster_zones(events, eps_meters, min_samples):
    """DBSCAN บนพิกัด (haversine) -> รายการจุดเสี่ยงพร้อมสถิติดิบต่อจุด"""
    coords = np.array([[radians(e["lat"]), radians(e["lng"])] for e in events])
    labels = DBSCAN(
        eps=eps_meters / EARTH_RADIUS_M, min_samples=min_samples, metric="haversine"
    ).fit(coords).labels_

    zones = []
    for cluster_id in sorted(set(labels)):
        if cluster_id == -1:  # noise = เหตุกระจัดกระจาย ไม่เกาะกลุ่มเป็นจุดเสี่ยง
            continue
        members = [events[i] for i, l in enumerate(labels) if l == cluster_id]
        n = len(members)
        deaths = sum(m["deaths"] for m in members)
        serious = sum(m["serious"] for m in members)
        minor = sum(m["minor"] for m in members)
        single_cnt = sum(1 for m in members if m["vehicles"] <= 1)
        road_type = mode_of([m["road_type"] for m in members], exclude=("ไม่ระบุ",))
        # เกณฑ์ 4 ลักษณะถนน: เหตุที่เกิดบริเวณทางแยก/ทางโค้ง/ทางร่วม/ต่างระดับ
        # (ทางแยก/ทางโค้ง/ทางร่วม/ทางเชื่อม/ต่างระดับ) — ค่าดิบของเกณฑ์ที่ 4
        conflict_cnt = sum(
            1 for m in members if conflict_group(m["location_type"])[0] != "ncp"
        )

        zones.append({
            "id": f"zone_{cluster_id}",
            "lat": round(sum(m["lat"] for m in members) / n, 6),
            "lng": round(sum(m["lng"] for m in members) / n, 6),
            "province": mode_of([m["province"] for m in members]),
            "road": mode_of([m["road"] for m in members], exclude=("ไม่ระบุ",)),
            "accident_count": n,
            "deaths": deaths,
            "serious_injury": serious,
            "minor_injury": minor,
            "economic_loss": deaths * COST_DEATH + serious * COST_SERIOUS + minor * COST_MINOR,
            "single_count": single_cnt,
            "multi_count": n - single_cnt,
            "single_pct": round(single_cnt / n * 100, 1),
            "multi_pct": round((n - single_cnt) / n * 100, 1),
            "conflict_count": conflict_cnt,
            "conflict_pct": round(conflict_cnt / n * 100, 1),
            "top_cause": mode_of([m["cause"] for m in members], exclude=("ไม่ระบุ",)),
            "road_feature": mode_of([m["location_type"] for m in members], exclude=("ไม่ระบุ",)),
            "crash_pattern": mode_of([m["crash_pattern"] for m in members], exclude=("ไม่ระบุ",)),
            "road_type": road_type,
            "speed_limit": speed_limit_for(road_type),
            "_members": members,
        })
    return zones


def score_zones(zones, fi_weights):
    """ให้คะแนน 4 เกณฑ์จากตารางเกณฑ์ -> Risk Score (เต็ม 100) -> จัด 3 ระดับ"""
    for z in zones:
        # gc_score/geom_group เก็บไว้เป็นข้อมูลประกอบ (FI Rate ของข้อมูลไทยเอง)
        # ไม่ได้ใช้ในสูตรคะแนนแล้วตั้งแต่ v2568-r4 — เกณฑ์ที่ 4 ใช้ conflict_pct แทน
        weights = [fi_weights[conflict_group(m["location_type"])[0]] for m in z["_members"]]
        z["gc_score"] = round(sum(weights) / len(weights), 4)
        z["geom_group"] = mode_of(
            [conflict_group(m["location_type"])[0] for m in z["_members"]]
        )
        # รูปแบบปัญหาเด่น ใช้เลือกคำแนะนำเชิงวิศวกรรม (สเปก: เก็บ Single/Multiple คู่กัน)
        if z["single_pct"] >= 60:
            z["pattern"] = "single"
        elif z["multi_pct"] >= 60:
            z["pattern"] = "multiple"
        else:
            z["pattern"] = "mixed"
        del z["_members"]

    # Percentile Rank: แปลงค่าดิบทุกเกณฑ์เป็นอันดับเทียบกับจุดอื่นในรอบเดียวกัน (0-100)
    # ทนต่อ outlier เพราะสนใจเฉพาะ "อันดับ" ไม่สนใจว่าค่าสูงสุดทิ้งห่างแค่ไหน
    # (OECD/JRC 2008 — Ranking: "not affected by outliers")
    df = pd.DataFrame(zones)
    df["s_freq"] = percentile_rank(df["accident_count"])
    df["s_econ"] = percentile_rank(df["economic_loss"])
    df["s_single"] = percentile_rank(df["single_pct"])
    df["s_geom"] = percentile_rank(df["conflict_pct"])
    df["risk_score"] = (
        W_FREQ * df["s_freq"] + W_ECON * df["s_econ"]
        + W_SINGLE * df["s_single"] + W_GEOM * df["s_geom"]
    ).round(1)

    for z, (_, row) in zip(zones, df.iterrows()):
        # เก็บเป็น Percentile Rank 0-100 (หน้าเว็บคูณ 0.25 เองตอนแสดงเป็นแต้ม/25)
        z["score_breakdown"] = {
            "frequency": round(row["s_freq"], 1),
            "economic_loss": round(row["s_econ"], 1),
            "single_vehicle": round(row["s_single"], 1),
            "geometry": round(row["s_geom"], 1),
        }
        z["risk_score"] = float(row["risk_score"])
        z["level"] = classify(z["risk_score"], LEVEL_BREAKS)

    return zones, LEVEL_BREAKS


# ---------------------------------------------------------------- ผลลัพธ์


def to_geojson(zones, calibration):
    return {
        "type": "FeatureCollection",
        "calibration": calibration,  # foreign member: ระบุเวอร์ชันที่ใช้คำนวณคะแนนชุดนี้
        "features": [{
            "type": "Feature",
            "geometry": {"type": "Point", "coordinates": [z["lng"], z["lat"]]},
            "properties": {k: v for k, v in z.items() if k not in ("lat", "lng")},
        } for z in zones],
    }


def main():
    print(f"อ่านข้อมูลจาก {XLSX_FILE.name} ...")
    records = load_excel_records(XLSX_FILE)
    print(f"  ทั้งหมด {len(records)} เหตุการณ์ (6 จังหวัด)")

    # FI weights ประมาณจากทุกแถว (รวมแถวไม่มีพิกัด — ความรุนแรงยังเป็นข้อมูลจริง)
    all_events = [_event_from_record(r) for r in records
                  if r.get("จังหวัด") in BANGKOK_METRO_PROVINCES]
    fi_weights, fi_table = compute_fi_weights(all_events)
    print("FI Rate ของข้อมูลเอง (ข้อมูลประกอบ ไม่อยู่ในสูตรคะแนน):")
    for g, t in fi_table.items():
        print(f"  {GROUP_LABELS[g]:<40} n={t['n']:<5} FI {t['fi_rate_pct']}%  weight {t['weight']}")

    events = clean_points(records)
    print(f"มีพิกัดใช้ได้ {len(events)} เหตุการณ์")

    zones = cluster_zones(events, EPS_METERS, MIN_SAMPLES)
    clustered = sum(z["accident_count"] for z in zones)
    print(f"DBSCAN (eps {EPS_METERS} ม., min {MIN_SAMPLES}) -> จุดเสี่ยง {len(zones)} จุด "
          f"(ครอบคลุม {clustered} เหตุการณ์, noise {len(events) - clustered})")

    zones, breaks = score_zones(zones, fi_weights)
    counts = {lv: sum(1 for z in zones if z["level"] == lv) for lv in ("high", "medium", "low")}
    print(f"จุดตัดระดับ (คงที่): ต่ำ ≤ {breaks[0]} < ปานกลาง ≤ {breaks[1]} < สูง")
    print(f"  ระดับสูง {counts['high']} | ปานกลาง {counts['medium']} | ต่ำ {counts['low']}")

    top = sorted(zones, key=lambda z: z["risk_score"], reverse=True)[:5]
    print("Top 5 จุดเสี่ยง:")
    for z in top:
        print(f"  {z['risk_score']:>5.1f}  {z['road'][:44]} ({z['province']}) "
              f"n={z['accident_count']} ตาย={z['deaths']}")

    calibration = {
        "version": CALIB_VERSION,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "recalibration_policy": RECALIB_POLICY,
        "source": XLSX_FILE.name,
        "events_total": len(records),
        "events_with_coords": len(events),
        "dbscan": {"eps_m": EPS_METERS, "min_samples": MIN_SAMPLES},
        "scoring_method": "percentile_rank",
        "criteria_weights": {"frequency": W_FREQ, "economic_loss": W_ECON,
                             "single_vehicle": W_SINGLE, "geometry": W_GEOM},
        "cost_per_person_thb": {"death": COST_DEATH, "serious": COST_SERIOUS,
                                "minor": COST_MINOR},
        "fi_weights": fi_table,
        "level_breaks": breaks,
        "level_break_method": "fixed",
        "zones": len(zones),
        "levels": counts,
        "score_distribution": {
            str(s): sum(1 for z in zones if z["risk_score"] == s)
            for s in sorted({z["risk_score"] for z in zones})
        },
    }

    OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(to_geojson(zones, calibration), f, ensure_ascii=False, indent=1)
    print(f"บันทึก {OUTPUT_FILE.relative_to(BASE_DIR)}")

    # เก็บ log ทุกเวอร์ชัน calibration ไว้ตรวจสอบย้อนหลัง (สเปกข้อ 4)
    CALIB_DIR.mkdir(parents=True, exist_ok=True)
    snap = CALIB_DIR / f"{CALIB_VERSION}.json"
    with open(snap, "w", encoding="utf-8") as f:
        json.dump(calibration, f, ensure_ascii=False, indent=2)
    print(f"บันทึก snapshot {snap.relative_to(BASE_DIR)}")


# ---------------------------------------------------------------- self-test


def _self_test():
    # 1) การจัดกลุ่ม conflict — ลำดับเช็ก ต่างระดับ > แยก สำคัญ
    assert conflict_group("ทางแยกต่างระดับ/Ramps") == ("diverging", True)
    assert conflict_group("จุดกลับรถต่างระดับ") == ("diverging", True)
    assert conflict_group("ทางสามแยก (Y)") == ("crossing", True)
    assert conflict_group("ทางสี่แยก") == ("crossing", True)
    assert conflict_group("ทางโค้งกว้าง+ที่ลาดชัน") == ("merging", True)
    assert conflict_group("ทางร่วม") == ("merging", True)
    assert conflict_group("ทางเชื่อมเข้าพื้นที่สาธารณะ/เชิงพาณิชย์") == ("merging", True)
    assert conflict_group("ทางตรง+ไม่มีความลาดชัน") == ("ncp", True)
    assert conflict_group("อื่นๆ") == ("ncp", False)
    assert conflict_group(None) == ("ncp", False)

    # 2) Percentile Rank — tie ใช้ average rank: [10,20,20,30] -> [25, 62.5, 62.5, 100]
    got = percentile_rank(pd.Series([10, 20, 20, 30])).tolist()
    assert got == [25.0, 62.5, 62.5, 100.0], got

    # 3) Jenks — สามกลุ่มชัดเจน ต้องตัดที่ท้ายกลุ่ม 1 และ 2
    assert jenks_breaks([1, 2, 3, 10, 11, 12, 100, 101, 102], 3) == [3.0, 12.0]

    # 4) จัดระดับจาก breaks
    assert classify(40.0, [40.0, 57.0]) == "low"
    assert classify(40.1, [40.0, 57.0]) == "medium"
    assert classify(57.1, [40.0, 57.0]) == "high"

    # 5) มูลค่าความเสียหาย TDRI: 1 ตาย + 1 สาหัส + 1 เล็กน้อย = 8,758,000 บาท
    assert COST_DEATH + COST_SERIOUS + COST_MINOR == 8_758_000

    # 6) FI weights — กลุ่มที่ FI สูงกว่า NCP ต้องได้ weight > 1
    ev = (
        [{"location_type": "ทางตรง", "deaths": 0, "serious": 0, "minor": 0}] * 8
        + [{"location_type": "ทางตรง", "deaths": 1, "serious": 0, "minor": 0}] * 2
        + [{"location_type": "ทางสี่แยก", "deaths": 0, "serious": 1, "minor": 0}] * 3
        + [{"location_type": "ทางสี่แยก", "deaths": 0, "serious": 0, "minor": 0}] * 1
    )
    w, _ = compute_fi_weights(ev)
    assert w["ncp"] == 1.0 and w["crossing"] == round((3 / 4) / (2 / 10), 3), w

    # 7) mode_of เว้นค่า 'ไม่ระบุ' เมื่อมีค่าจริงให้เลือก
    assert mode_of(["ไม่ระบุ", "ไม่ระบุ", "ถนน ก"], exclude=("ไม่ระบุ",)) == "ถนน ก"
    assert mode_of(["ไม่ระบุ"], exclude=("ไม่ระบุ",)) == "ไม่ระบุ"

    # 8) ตารางเกณฑ์ — ค่าที่ขีดพอดีต้องอยู่ช่วงล่าง (ใช้ <=), เกินทุกช่วง = 25
    fb = SCORE_BANDS["frequency"]           # [(3,5),(5,10),(10,15),(20,20)] -> เกิน 20 = 25
    assert band_score(3, fb) == 5 and band_score(4, fb) == 10
    assert band_score(5, fb) == 10 and band_score(6, fb) == 15
    assert band_score(10, fb) == 15 and band_score(11, fb) == 20
    assert band_score(20, fb) == 20 and band_score(21, fb) == 25
    # ปลายเปิด: outlier สุดขั้วได้คะแนนเท่ากับจุดที่แค่เกินขีด (ทนต่อ outlier)
    assert band_score(994, fb) == band_score(21, fb) == 25

    gb = SCORE_BANDS["geometry"]            # [(0,5),(5,10),(15,15),(30,20)]
    assert band_score(0, gb) == 5           # ทางตรงล้วน
    assert band_score(0.1, gb) == 10 and band_score(100, gb) == 25

    # 9) คะแนนรวมต้องอยู่ในช่วง 20-100 เสมอ (4 เกณฑ์ × 5..25)
    lo = sum(band_score(-1, SCORE_BANDS[k]) for k in SCORE_BANDS)
    hi = sum(band_score(10**12, SCORE_BANDS[k]) for k in SCORE_BANDS)
    assert (lo, hi) == (20, 100), (lo, hi)

    # 10) ทุกเกณฑ์ต้องมี 4 ขีด (= 5 ช่วง) และคะแนนเรียงขึ้น 5/10/15/20
    for name, bands in SCORE_BANDS.items():
        assert [p for _, p in bands] == [5, 10, 15, 20], (name, bands)
        uppers = [u for u, _ in bands]
        assert uppers == sorted(uppers), (name, uppers)

    print("self-test ผ่านทั้งหมด")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _self_test()
    else:
        main()
