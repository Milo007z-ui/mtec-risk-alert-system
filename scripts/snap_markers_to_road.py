"""
snap_markers_to_road.py — ดึงหมุดคลัสเตอร์เข้าแนวกึ่งกลางถนนที่ใกล้ที่สุด

ทำไมต้องมี: หมุดของแต่ละคลัสเตอร์คือ medoid = พิกัดอุบัติเหตุจริงจากข้อมูล
กรมทางหลวง ซึ่งมีความคลาดเคลื่อนของ GPS ราว 0-15 เมตร พอซูมเข้าใกล้บนแผนที่
จะเห็นหมุดเยื้องออกจากเส้นถนนเล็กน้อย แม้ตำแหน่งจะถูกต้องในเชิงข้อมูลก็ตาม

สคริปต์นี้ยิง OSRM /nearest เพื่อหาจุดบนแนวถนนที่ใกล้หมุดที่สุด แล้วย้ายหมุดไปที่นั่น

หลักการที่ยึดไว้ (สำคัญต่อความน่าเชื่อถือของข้อมูล):
  - เก็บพิกัดเดิมไว้เสมอในฟิลด์ `medoid_raw` — ย้อนกลับได้ ตรวจสอบได้
  - บันทึกระยะที่ย้ายไว้ใน `snap_distance_m` ให้ตรวจทานได้ว่าย้ายไปไกลแค่ไหน
  - ถ้าต้องย้ายไกลเกิน MAX_SNAP_M ถือว่า OSRM จับถนนผิดเส้น -> ไม่ย้าย คงพิกัดเดิม
  - เป็นการปรับ "เพื่อการแสดงผล" เท่านั้น ระยะที่ขยับ (ไม่กี่เมตร) เล็กกว่ารัศมี
    แจ้งเตือน 500 เมตรมาก จึงไม่กระทบผลการเตือนหรือค่าที่คำนวณไว้แล้ว

ใช้:
  py scripts/snap_markers_to_road.py                      # ชุด 3 ปี (ค่าเริ่มต้น)
  py scripts/snap_markers_to_road.py --dry-run            # ดูผลโดยยังไม่เขียนไฟล์
  py scripts/snap_markers_to_road.py --file data/xxx.geojson

ต้องรันใหม่ทุกครั้งหลัง build_risk_points.py เพราะ build จะเขียนไฟล์ทับด้วยพิกัดดิบ
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from math import asin, cos, radians, sin, sqrt
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
DEFAULT_FILE = BASE_DIR / "data" / "risk_points_bkk_metro_3y.geojson"

OSRM = "https://router.project-osrm.org/nearest/v1/driving"
MAX_SNAP_M = 30.0     # ไกลกว่านี้ถือว่าจับถนนผิดเส้น ไม่ย้าย
REQUEST_GAP_S = 0.12  # เว้นจังหวะไม่ให้ยิงถี่เกินไปใส่เซิร์ฟเวอร์สาธารณะ
TIMEOUT_S = 15
RETRIES = 3


def haversine_m(lat1, lon1, lat2, lon2):
    d_lat, d_lon = radians(lat2 - lat1), radians(lon2 - lon1)
    a = sin(d_lat / 2) ** 2 + cos(radians(lat1)) * cos(radians(lat2)) * sin(d_lon / 2) ** 2
    return 2 * 6371000 * asin(sqrt(a))


def nearest_on_road(lng, lat):
    """คืน (lng, lat, ระยะเป็นเมตร) ของจุดบนถนนที่ใกล้ที่สุด หรือ None ถ้าถามไม่สำเร็จ"""
    url = f"{OSRM}/{lng},{lat}?number=1"
    for attempt in range(RETRIES):
        try:
            with urllib.request.urlopen(url, timeout=TIMEOUT_S) as r:
                data = json.load(r)
            if data.get("code") != "Ok" or not data.get("waypoints"):
                return None
            wp = data["waypoints"][0]
            return wp["location"][0], wp["location"][1], wp["distance"]
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError, KeyError):
            if attempt < RETRIES - 1:
                time.sleep(1.0 * (attempt + 1))
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", default=str(DEFAULT_FILE))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-snap", type=float, default=MAX_SNAP_M)
    a = ap.parse_args()

    path = Path(a.file)
    gj = json.loads(path.read_text(encoding="utf-8"))
    feats = gj["features"]
    print(f"ไฟล์ {path.name} — {len(feats)} คลัสเตอร์\n")

    moved, kept, failed, dists = 0, 0, 0, []
    for i, f in enumerate(feats, 1):
        lng, lat = f["geometry"]["coordinates"]
        props = f["properties"]

        # ถ้าเคย snap แล้ว ให้เริ่มจากพิกัดดิบเสมอ จะได้ไม่ย้ายซ้อนไปเรื่อยๆ
        if "medoid_raw" in props:
            lng, lat = props["medoid_raw"]

        res = nearest_on_road(lng, lat)
        if res is None:
            failed += 1
            print(f"  [{i}/{len(feats)}] {props['id']}: ถามไม่สำเร็จ คงพิกัดเดิม")
            time.sleep(REQUEST_GAP_S)
            continue

        snap_lng, snap_lat, dist = res
        # วัดเองด้วย haversine ไม่พึ่งค่า distance ของ OSRM อย่างเดียว
        real = haversine_m(lat, lng, snap_lat, snap_lng)

        props["medoid_raw"] = [lng, lat]
        if real <= a.max_snap:
            f["geometry"]["coordinates"] = [round(snap_lng, 6), round(snap_lat, 6)]
            props["snap_distance_m"] = round(real, 2)
            moved += 1
            dists.append(real)
        else:
            f["geometry"]["coordinates"] = [lng, lat]
            props["snap_distance_m"] = None
            kept += 1
            print(f"  [{i}/{len(feats)}] {props['id']}: ถนนใกล้สุดห่าง {real:.0f} ม. เกินเกณฑ์ -> ไม่ย้าย")

        if i % 50 == 0:
            print(f"  ...{i}/{len(feats)}")
        time.sleep(REQUEST_GAP_S)

    dists.sort()
    print(f"\nย้ายเข้าแนวถนน {moved} · คงเดิมเพราะเกินเกณฑ์ {kept} · ถามไม่สำเร็จ {failed}")
    if dists:
        print(
            f"ระยะที่ย้าย: กลาง {dists[len(dists)//2]:.1f} ม. · "
            f"มากสุด {dists[-1]:.1f} ม. · เฉลี่ย {sum(dists)/len(dists):.1f} ม."
        )

    if a.dry_run:
        print("\n--dry-run: ไม่เขียนไฟล์")
        return

    cal = gj.setdefault("calibration", {})
    cal["marker_snapped_to_road"] = True
    cal["marker_snap_max_m"] = a.max_snap
    path.write_text(json.dumps(gj, ensure_ascii=False), encoding="utf-8")
    print(f"\nเขียน {path.name} แล้ว (พิกัดเดิมเก็บไว้ในฟิลด์ medoid_raw ทุกจุด)")


if __name__ == "__main__":
    main()
