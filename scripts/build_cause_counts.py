"""สรุปจำนวนอุบัติเหตุตามมูลเหตุสันนิษฐาน สำหรับกราฟสาเหตุในแดชบอร์ด

นับรายจุดเสี่ยง (1 จุด = 1 อุบัติเหตุ) เฉพาะจุดที่อยู่ในคลัสเตอร์ แบบเดียวกับตารางที่ 4-7 ในรายงาน
และรวมคำที่ความหมายตรงกันแต่สะกดต่างกันระหว่างปี (ข้อมูลปี 2566 ใช้ถ้อยคำต่างจากปี 2567–2568)

    python scripts/build_cause_counts.py
"""
import collections
import json
import os

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "..", "data", "accident_points_3y.geojson")
OUT = os.path.join(HERE, "..", "data", "cause_counts_3y.json")

MERGE = {
    "ขับรถเร็วเกินอัตราที่กำหนด": "ขับรถเร็วเกินอัตรากำหนด",
    "มีการตัดหน้าระยะกระชั้นชิด": "คน/รถ/สัตว์ตัดหน้ากระชั้นชิด",
    "ยางรถยนต์ชำรุด": "ยางเสื่อมสภาพ/ยางแตก",
    "ขับรถกระชั้นชิด": "ขับรถตามกระชั้นชิด",
    "ไม่ให้สัญญาณชะลอ / เลี้ยว": "ไม่ให้สัญญาณชะลอ/เลี้ยว",
    "ฝ่าฝืนสัญญาณไฟ / เครื่องหมายจราจร": "ฝ่าฝืนสัญญาณไฟ/เครื่องหมายจราจร",
}
UNSPECIFIED = "ไม่ระบุ"

points = [f["properties"] for f in json.load(open(SRC, encoding="utf-8"))["features"]]
inc = [p for p in points if p["unit_type"] == "cluster"]
counts = collections.Counter(MERGE.get(p["cause"], p["cause"]) for p in inc)
unspecified = counts.pop(UNSPECIFIED, 0)

out = {
    "source": "accident_points_3y.geojson",
    "scope": "cluster",
    "risk_points": len(inc),
    "unspecified": unspecified,
    "merged": MERGE,
    "causes": [{"cause": c, "count": n} for c, n in counts.most_common()],
}
with open(OUT, "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
print(f"{len(inc)} จุดเสี่ยงในคลัสเตอร์ · ไม่ระบุ {unspecified} · {len(counts)} สาเหตุ -> {OUT}")
for c, n in counts.most_common(8):
    print(f"  {n:6,}  {c}")
