"""เขียนระดับรวม 2 ปัจจัยลงไฟล์ข้อมูลที่แผนที่ API และอุปกรณ์ใช้ร่วมกัน

รันหลัง scripts/build_combined_levels.py ทุกครั้ง (รวมถึงหลังคำนวณรอบใหม่ด้วย build_risk_points_3y.py)
รันซ้ำได้: ระดับจาก SI คำนวณใหม่จาก severity_index ทุกครั้ง ไม่อ่านจากฟิลด์ level เดิม

    python scripts/build_combined_levels.py
    python scripts/apply_combined_levels.py

ฟิลด์ต่อคลัสเตอร์ที่เขียน:
    level       ระดับรวม = ระดับที่สูงกว่าระหว่าง si_level กับ rate_level (ไม่มี AADT = si_level)
    si_level    ระดับจาก Accident Severity (SI จุดตัด 1 และ 2)
    rate_level  ระดับจาก Accident Rate จำแนกด้วย Rate Quality Control (null = ไม่มี AADT)
    agency, aadt_v, accident_rate, rate_ra, rate_rc, rate_df
"""
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, "..", "data")
RISK = os.path.join(DATA, "risk_points_bkk_metro_3y.geojson")
POINTS = os.path.join(DATA, "accident_points_3y.geojson")
LEVELS = os.path.join(DATA, "combined_levels_3y.json")

combined = json.load(open(LEVELS, encoding="utf-8"))
risk = json.load(open(RISK, encoding="utf-8"))
cal = risk["calibration"]
b1, b2 = cal["level_breaks"]


def si_level(si):
    return "high" if si >= b2 else "medium" if si >= b1 else "low"


level_of = {}
for f in risk["features"]:
    p = f["properties"]
    c = combined["clusters"][p["id"]]
    p["si_level"] = si_level(p["severity_index"])
    assert p["si_level"] == c["si_level"], p["id"]
    p["rate_level"] = c["rate_level"]
    p["level"] = c["level"]
    p["agency"] = c["agency"]
    for src, dst in [("V", "aadt_v"), ("R", "accident_rate"), ("Ra", "rate_ra"), ("Rc", "rate_rc"), ("DF", "rate_df")]:
        p[dst] = c.get(src)
    level_of[p["id"]] = p["level"]

# สรุประดับใน calibration ให้ตรงกับระดับที่แสดงจริง
counts = {k: 0 for k in ("high", "medium", "low")}
epdo = {k: [0, 0.0] for k in counts}
for f in risk["features"]:
    p = f["properties"]
    counts[p["level"]] += 1
    epdo[p["level"]][0] += 1
    epdo[p["level"]][1] += p["epdo_million"]
if "levels_si" not in cal:
    cal["levels_si"] = cal["levels"]
    cal["epdo_by_si_level"] = cal["epdo_by_level"]
cal["levels"] = counts
cal["levels_rate"] = combined["counts"]["rate"]
cal["epdo_by_level"] = {
    k: {"points": n, "epdo_total_million": round(s, 2), "epdo_mean_million": round(s / n, 2) if n else 0}
    for k, (n, s) in epdo.items()
}
cal["level_method"] = "combined_si_rate"
cal["level_method_note"] = (
    "ระดับรวม = ระดับที่สูงกว่าระหว่าง Accident Severity (SI จุดตัด 1/2) กับ Accident Rate "
    "จำแนกด้วย Rate Quality Control (ต่ำ R ≤ Ra · ปานกลาง Ra < R ≤ Rc · สูง R > Rc) · "
    f"{combined['with_aadt']} วงมี AADT · {combined['without_aadt']} วงไม่มี AADT ใช้ระดับจาก SI"
)
cal["ra_by_agency"] = combined["ra_by_agency"]
with open(RISK, "w", encoding="utf-8") as fh:
    json.dump(risk, fh, ensure_ascii=False)

# จุดเสี่ยงรายจุด: สีตามระดับของคลัสเตอร์ที่สังกัด
pts = json.load(open(POINTS, encoding="utf-8"))
changed = 0
for f in pts["features"]:
    p = f["properties"]
    if p.get("unit_type") == "cluster":
        new = level_of[p["unit_id"]]
        changed += p.get("level") != new
        p["level"] = new
if "calibration" in pts:
    pts["calibration"] = cal
with open(POINTS, "w", encoding="utf-8") as fh:
    json.dump(pts, fh, ensure_ascii=False, separators=(",", ":"))
print("ระดับรวม", counts, "· จุดเสี่ยงรายจุดเปลี่ยนสี", changed)
