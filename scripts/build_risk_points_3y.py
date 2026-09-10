"""build_risk_points_3y.py — รันโมเดลเดิม (v2568-r12) กับข้อมูล 3 ปี 2566-2568"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build_risk_points as m

BASE_DIR = m.BASE_DIR

# เปลี่ยนเฉพาะ 4 ค่านี้ — ที่เหลือใช้ของโมเดลเดิมทั้งหมด
m.CALIB_VERSION = "v2569-r1-3y"
m.XLSX_FILE = BASE_DIR / "data" / "accident2023-2025.xlsx"
m.OUTPUT_FILE = BASE_DIR / "data" / "risk_points_bkk_metro_3y.geojson"
m.ACCIDENT_FILE = BASE_DIR / "data" / "accident_points_3y.geojson"

if __name__ == "__main__":
    m.main()
