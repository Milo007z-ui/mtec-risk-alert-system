#!/usr/bin/env python3
"""
pi_alert_client.py — ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi (สำหรับติดบนรถเมล์)

หลักการทำงาน (วนลูปทุก POLL_INTERVAL_S วินาที):
  1. อ่านพิกัด GPS ปัจจุบันของรถ (จาก gpsd หรือโหมดจำลอง)
  2. ยิง GET /api/risk-points/nearby?lat=..&lng=..&radius=600 ไปที่เซิร์ฟเวอร์
  3. ถ้ามีจุดเสี่ยงใกล้กว่า 500 เมตรและยังไม่เคยเตือน -> พูดข้อความ alert_message
     ที่เซิร์ฟเวอร์สร้างให้ ผ่าน espeak-ng เสียงภาษาไทย

กติกา cooldown ต่อจุด (ตรงกับ js/alert.js ของหน้าเว็บ):
  - เตือนครั้งแรกเมื่อเข้ามาในรัศมี ALERT_RADIUS_M (500 ม.)
  - เตือนจุดเดิมซ้ำได้ต่อเมื่อ (ก) ออกไกลกว่า EXIT_RADIUS_M (600 ม.) แล้วกลับเข้ามาใหม่
    หรือ (ข) วนอยู่ในรัศมีนานเกิน REALERT_S (5 นาที)

ใช้เฉพาะ Python standard library — ไม่ต้อง pip install อะไรเพิ่มบน Pi

ตัวอย่างการใช้งาน:
  # ทดสอบด้วยพิกัดคงที่ (ไม่ต้องมี GPS)
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --test 13.665 100.534

  # ใช้งานจริงกับ GPS ผ่าน gpsd (sudo apt install gpsd espeak-ng)
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --gpsd

  # จำลองการขับด้วยไฟล์เส้นทาง (บรรทัดละ "lat,lng")
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --route route.csv
"""

import argparse
import json
import shutil
import socket
import subprocess
import sys
import time
import urllib.parse
import urllib.request

ALERT_RADIUS_M = 500
EXIT_RADIUS_M = 600   # hysteresis กันเด้งเข้าออกตรงขอบรัศมี
REALERT_S = 5 * 60
POLL_INTERVAL_S = 3
HTTP_TIMEOUT_S = 5

GPSD_HOST, GPSD_PORT = "127.0.0.1", 2947

# ให้ log ขึ้นทันทีแม้ stdout ถูก redirect (เช่น รันผ่าน systemd/journald บน Pi)
sys.stdout.reconfigure(line_buffering=True)


# ---------- แหล่งพิกัด GPS ----------

class FixedPosition:
    """โหมดทดสอบ: พิกัดคงที่"""

    def __init__(self, lat, lng):
        self.lat, self.lng = lat, lng

    def read(self):
        return self.lat, self.lng


class RoutePlayer:
    """โหมดจำลอง: อ่านพิกัดจากไฟล์ทีละบรรทัด (lat,lng) วนเมื่อจบไฟล์"""

    def __init__(self, path):
        self.positions = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                lat, lng = line.split(",")
                self.positions.append((float(lat), float(lng)))
        if not self.positions:
            sys.exit(f"ไฟล์เส้นทาง {path} ไม่มีพิกัดเลย")
        self.index = 0

    def read(self):
        pos = self.positions[self.index]
        self.index = (self.index + 1) % len(self.positions)
        return pos


class GpsdReader:
    """อ่านพิกัดจาก gpsd ผ่าน TCP JSON protocol (ไม่ต้องใช้ไลบรารี gps3)"""

    def __init__(self):
        self.sock = None
        self.buffer = b""
        self.last_fix = None

    def _connect(self):
        self.sock = socket.create_connection((GPSD_HOST, GPSD_PORT), timeout=5)
        self.sock.sendall(b'?WATCH={"enable":true,"json":true}\n')
        self.sock.settimeout(2)

    def read(self):
        """คืน (lat, lng) จากรายงาน TPV ล่าสุด หรือ fix เก่าถ้ายังไม่มีรายงานใหม่"""
        try:
            if self.sock is None:
                self._connect()
            try:
                self.buffer += self.sock.recv(65536)
            except socket.timeout:
                pass
            *lines, self.buffer = self.buffer.split(b"\n")
            for line in lines:
                try:
                    report = json.loads(line)
                except ValueError:
                    continue
                if report.get("class") == "TPV" and "lat" in report and "lon" in report:
                    self.last_fix = (report["lat"], report["lon"])
        except OSError as e:
            print(f"[gpsd] ขาดการเชื่อมต่อ: {e} — จะลองใหม่", file=sys.stderr)
            self.sock = None
        return self.last_fix


# ---------- เสียงพูด ----------

def find_speaker():
    """หาโปรแกรม TTS ที่มีในเครื่อง: espeak-ng (มีเสียงไทย) > espeak"""
    for cmd in ("espeak-ng", "espeak"):
        if shutil.which(cmd):
            return cmd
    return None


SPEAKER = find_speaker()


def speak(message):
    print(f"\a🔊 {message}")
    if SPEAKER:
        # -v th เสียงไทย, -s 140 ความเร็วพูดช้าลงให้ฟังชัดขณะขับรถ
        subprocess.run([SPEAKER, "-v", "th", "-s", "140", message], check=False)
    else:
        print("   (ไม่พบ espeak-ng — ติดตั้งด้วย: sudo apt install espeak-ng)", file=sys.stderr)


# ---------- เรียก API ----------

def fetch_nearby(api_base, lat, lng):
    query = urllib.parse.urlencode(
        {"lat": f"{lat:.6f}", "lng": f"{lng:.6f}", "radius": EXIT_RADIUS_M}
    )
    url = f"{api_base}/api/risk-points/nearby?{query}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read())["points"]


# ---------- ลูปหลัก ----------

def run(api_base, position_source):
    alerted = {}  # point id -> เวลาที่เตือนล่าสุด (มี entry = ยังอยู่ในสถานะ "เตือนแล้ว")
    print(f"เริ่มเฝ้าระวังจุดเสี่ยง (API: {api_base}, เตือนที่ระยะ {ALERT_RADIUS_M} ม.)")

    while True:
        started = time.monotonic()
        pos = position_source.read()
        if pos is None:
            print("[gps] ยังไม่ได้ตำแหน่ง (รอสัญญาณดาวเทียม)...")
        else:
            lat, lng = pos
            try:
                nearby = fetch_nearby(api_base, lat, lng)
            except OSError as e:
                print(f"[api] เรียกเซิร์ฟเวอร์ไม่สำเร็จ: {e}", file=sys.stderr)
                nearby = None

            if nearby is not None:
                now = time.monotonic()
                nearby_ids = {p["id"] for p in nearby}

                # จุดที่เคยเตือนแต่ออกนอกรัศมี EXIT แล้ว -> รีเซ็ตให้เตือนใหม่ได้
                for pid in list(alerted):
                    if pid not in nearby_ids:
                        del alerted[pid]

                # เตือนเฉพาะจุดใกล้สุดที่เข้าเงื่อนไข (API เรียงใกล้ -> ไกลให้แล้ว)
                for p in nearby:
                    if p["distance_m"] > ALERT_RADIUS_M:
                        continue
                    if p["id"] in alerted and now - alerted[p["id"]] < REALERT_S:
                        continue
                    alerted[p["id"]] = now
                    speak(p["alert_message"])
                    break

                nearest = nearby[0] if nearby else None
                status = (
                    f"ใกล้สุด: {nearest['road']} {nearest['distance_m']:.0f} ม. ({nearest['level']})"
                    if nearest
                    else f"ไม่มีจุดเสี่ยงในรัศมี {EXIT_RADIUS_M} ม."
                )
                print(f"[{time.strftime('%H:%M:%S')}] ({lat:.5f}, {lng:.5f}) {status}")

        time.sleep(max(0, POLL_INTERVAL_S - (time.monotonic() - started)))


def main():
    parser = argparse.ArgumentParser(description="ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="URL ของ EMMA Risk Point API (ค่าเริ่มต้น: http://localhost:8000)")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--gpsd", action="store_true", help="อ่านพิกัดจริงจาก gpsd")
    source.add_argument("--test", nargs=2, type=float, metavar=("LAT", "LNG"),
                        help="โหมดทดสอบ: ใช้พิกัดคงที่")
    source.add_argument("--route", metavar="FILE",
                        help="โหมดจำลอง: อ่านพิกัดจากไฟล์ (บรรทัดละ lat,lng)")
    args = parser.parse_args()

    if args.gpsd:
        position_source = GpsdReader()
    elif args.test:
        position_source = FixedPosition(*args.test)
    else:
        position_source = RoutePlayer(args.route)

    try:
        run(args.api.rstrip("/"), position_source)
    except KeyboardInterrupt:
        print("\nหยุดการทำงาน")


if __name__ == "__main__":
    main()
