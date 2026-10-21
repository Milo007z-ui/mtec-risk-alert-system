"""รวมระดับความเสี่ยง 2 ปัจจัยรายคลัสเตอร์ สำหรับแดชบอร์ด

ปัจจัยที่ 1  Accident Severity  — ระดับจาก SI (จุดตัด 1 และ 2) อยู่ใน risk_points_bkk_metro_3y.geojson
ปัจจัยที่ 2  Accident Rate      — ระดับจาก Rate Quality Control (ต่ำ R ≤ Ra · ปานกลาง Ra < R ≤ Rc · สูง R > Rc)
            คำนวณไว้แล้วใน analysis/accident-rate/outputs/ค่า-R-Ra-Rc-598คลัสเตอร์.csv (598 วงที่มี AADT)
ระดับรวม = ระดับที่สูงกว่าระหว่างสองปัจจัย · 32 วงที่ไม่มี AADT ใช้ระดับจาก SI

    python scripts/build_combined_levels.py
"""
import collections
import csv
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, "..")
GEO = os.path.join(ROOT, "data", "risk_points_bkk_metro_3y.geojson")
RATE = os.path.join(ROOT, "analysis", "accident-rate", "outputs", "ค่า-R-Ra-Rc-598คลัสเตอร์.csv")
OUT = os.path.join(ROOT, "data", "combined_levels_3y.json")

RANK = {"low": 0, "medium": 1, "high": 2}
AGENCY = {"ทล.": "กรมทางหลวง", "กทพ.": "การทางพิเศษแห่งประเทศไทย", "ทช.": "กรมทางหลวงชนบท"}

zones = [f["properties"] for f in json.load(open(GEO, encoding="utf-8"))["features"]]
rate = {r["id"]: r for r in csv.DictReader(open(RATE, encoding="utf-8-sig"))}

clusters = {}
for z in zones:
    r = rate.get(z["id"])
    item = {"si_level": z["level"]}
    if r:
        assert r["ระดับ SI"] == z["level"], z["id"]
        item.update({
            "agency": AGENCY[r["หน่วยงาน"]],
            "V": round(float(r["V = AADT เฉลี่ย 3 ปี"])),
            "R": round(float(r["R (ครั้ง/ล้านคัน)"]), 4),
            "Ra": round(float(r["Ra ของกลุ่ม"]), 4),
            "Rc": round(float(r["Rc"]), 4),
            "DF": round(float(r["DF = R/Rc"]), 2),
            "rate_level": r["ระดับ Rate"],
            "level": r["ระดับรวม"],
        })
        assert item["level"] == max(item["si_level"], item["rate_level"], key=RANK.get)
    else:
        item.update({"agency": None, "rate_level": None, "level": z["level"]})
    clusters[z["id"]] = item

ra = {}
for r in rate.values():
    ra[AGENCY[r["หน่วยงาน"]]] = round(float(r["Ra ของกลุ่ม"]), 4)
count = lambda key: dict(collections.Counter(c[key] for c in clusters.values() if c[key]))
out = {
    "method": {
        "severity": "SI = (F + PI) / Total Accident · ต่ำ SI < 1 · ปานกลาง 1 ≤ SI < 2 · สูง SI ≥ 2",
        "rate": "Accident Rate จำแนกด้วย Rate Quality Control · ต่ำ R ≤ Ra · ปานกลาง Ra < R ≤ Rc · สูง R > Rc",
        "combine": "ระดับรวม = ระดับที่สูงกว่าระหว่างสองปัจจัย · คลัสเตอร์ที่ไม่มี AADT ใช้ระดับจาก SI",
    },
    "with_aadt": len(rate),
    "without_aadt": len(clusters) - len(rate),
    "ra_by_agency": ra,
    "counts": {"si": count("si_level"), "rate": count("rate_level"), "combined": count("level")},
    "clusters": clusters,
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
print(out["counts"], "· มี AADT", out["with_aadt"], "· ไม่มี", out["without_aadt"], "->", OUT)
