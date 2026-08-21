"""
build_risk_points_3y.py — รันโมเดลเดิม (v2568-r12) กับข้อมูล 3 ปี 2566-2568

จุดประสงค์: ตอบคำถามเดียว — "ข้อมูลเดิม 1 ปีได้ 192 คลัสเตอร์
พอเพิ่มเป็น 3 ปี จะได้กี่คลัสเตอร์"

สคริปต์นี้ไม่ได้เขียนโมเดลใหม่ แต่ import build_risk_points แล้วเปลี่ยนเฉพาะ
"ไฟล์ต้นทาง" กับ "ชื่อไฟล์ผลลัพธ์" เท่านั้น ค่าพารามิเตอร์ทุกตัว (eps 400 ม.,
min_samples 3, DBSCAN สองชั้นแยกตามสายทาง, SI = (F+PI)/n, จุดตัด 1.0/2.0,
หมุด medoid, ต้นทุน TDRI) ใช้ของเดิมทั้งหมด ผลจึงเทียบกับรอบ r12 ได้ตรง ๆ
โดยตัวแปรที่ต่างกันมีแค่ "ช่วงเวลาของข้อมูล" ตัวเดียว

ไฟล์ผลลัพธ์แยกชื่อจากของเดิม เพื่อไม่ทับ calibration ที่ล็อกไว้ใช้งานจริง

ใช้: py scripts/build_risk_points_3y.py
"""

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
