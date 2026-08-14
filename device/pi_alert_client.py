#!/usr/bin/env python3
"""
pi_alert_client.py — ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi (สำหรับติดบนรถเมล์)

หลักการทำงาน (วนลูปทุก POLL_INTERVAL_S วินาที):
  1. อ่านพิกัด GPS ปัจจุบันของรถ (จาก gpsd หรือโหมดจำลอง)
  2. ยิง GET /api/risk-points/nearby?lat=..&lng=..&radius=600 ไปที่เซิร์ฟเวอร์
  3. ถ้ามีจุดเสี่ยงใกล้กว่า 500 เมตรและยังไม่เคยเตือน -> สั่ง buzzer ที่ต่อขา GPIO13 (เลขแบบ BCM) ร้อง 1 วิ

กติกา cooldown ต่อจุด:
  - เตือนครั้งแรกเมื่อเข้ามาในรัศมี ALERT_RADIUS_M (500 ม.)
  - เตือนจุดเดิมซ้ำได้ต่อเมื่อออกไกลกว่า EXIT_RADIUS_M (600 ม.) แล้วกลับเข้ามาใหม่

ใช้ Python standard library เป็นหลัก ยกเว้นส่วนคุม buzzer ที่ต้องมี RPi.GPIO
(มากับ Raspberry Pi OS อยู่แล้ว ไม่ต้อง pip install เพิ่ม — ถ้าไม่มีจะแค่ข้ามการสั่ง buzzer เฉยๆ)

ตัวอย่างการใช้งาน:
  # ทดสอบด้วยพิกัดคงที่ (ไม่ต้องมี GPS)
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --test 13.665 100.534

  # ใช้งานจริงกับ GPS ผ่าน gpsd (sudo apt install gpsd)
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --gpsd

  # จำลองการขับด้วยไฟล์เส้นทาง (บรรทัดละ "lat,lng")
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --route route.csv

  # จำลองการขับด้วยเส้นทางเดียวกับที่เว็บใช้ตอน ?mock=1
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --route ../data/mock_route.geojson

  # วิ่งจบเส้นทางครั้งเดียวแล้วหยุด (ไม่วนซ้ำ)
  python3 pi_alert_client.py --api http://192.168.1.10:8000 --route ../data/mock_route.geojson --once
"""

import argparse
import json
import socket
import sys
import time
import urllib.parse
import urllib.request

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

ALERT_RADIUS_M = 500
EXIT_RADIUS_M = 600   # hysteresis กันเด้งเข้าออกตรงขอบรัศมี
POLL_INTERVAL_S = 3
HTTP_TIMEOUT_S = 5

BUZZER_PIN = 13  # เลข GPIO แบบ BCM (ไม่ใช่ตำแหน่งจริงบนขาเข็มแบบ BOARD — ทดสอบแล้วว่า BCM13 ตรงกับ buzzer ที่ต่อไว้)

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
    """โหมดจำลอง: อ่านพิกัดจากไฟล์ วนซ้ำเมื่อจบไฟล์ (หรือหยุดครั้งเดียวถ้า loop=False)

    รองรับ 2 ฟอร์แมต (เลือกอัตโนมัติจากนามสกุลไฟล์):
      - .geojson/.json  เส้นทาง LineString เดียวกับที่เว็บใช้ตอน ?mock=1
                         (data/mock_route.geojson) พิกัดเป็น [lng, lat]
      - อื่นๆ (เช่น .csv) ไฟล์ข้อความบรรทัดละ "lat,lng"
    """

    def __init__(self, path, loop=True):
        if path.endswith((".geojson", ".json")):
            self.positions = self._read_geojson(path)
        else:
            self.positions = self._read_csv(path)
        if not self.positions:
            sys.exit(f"ไฟล์เส้นทาง {path} ไม่มีพิกัดเลย")
        self.index = 0
        self.loop = loop
        self.finished = False

    @staticmethod
    def _read_csv(path):
        positions = []
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#"):
                    continue
                lat, lng = line.split(",")
                positions.append((float(lat), float(lng)))
        return positions

    @staticmethod
    def _read_geojson(path):
        with open(path, encoding="utf-8") as f:
            gj = json.load(f)
        for feat in gj.get("features", []):
            geom = feat.get("geometry") or {}
            if geom.get("type") == "LineString":
                return [(lat, lng) for lng, lat in geom["coordinates"]]
        return []

    def read(self):
        if self.finished:
            return None
        pos = self.positions[self.index]
        self.index += 1
        if self.index >= len(self.positions):
            if self.loop:
                self.index = 0
            else:
                self.finished = True
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


def setup_buzzer():
    """เตรียมขา GPIO ของ buzzer (เรียกครั้งเดียวตอนเริ่มโปรแกรม)"""
    if GPIO is None:
        print("   (ไม่พบ RPi.GPIO — buzzer จะไม่ทำงาน ติดตั้งด้วย: sudo apt install python3-rpi.gpio)", file=sys.stderr)
        return
    GPIO.setmode(GPIO.BCM)  # เลข GPIO แบบ BCM (ยืนยันจากการทดสอบจริงว่าตรงกับ buzzer ที่ต่อไว้ — BUZZER_PIN=13)
    GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)


def beep():
    """buzzer ร้อง 1 วิ ผ่านขา GPIO — ตอนเข้าใกล้จุดเสี่ยงในระยะ ALERT_RADIUS_M"""
    print("\a🔔 buzzer")
    if GPIO is None:
        return
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(1)
    GPIO.output(BUZZER_PIN, GPIO.LOW)


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
    beeped = set()  # point id ที่ร้อง beep ไปแล้ว (รีเซ็ตเมื่อออกนอกรัศมี)
    print(
        f"เริ่มเฝ้าระวังจุดเสี่ยง (API: {api_base}, "
        f"buzzer ร้องที่ {ALERT_RADIUS_M} ม.)"
    )

    while True:
        started = time.monotonic()
        pos = position_source.read()
        if pos is None:
            if getattr(position_source, "finished", False):
                print("จบเส้นทางจำลองแล้ว — หยุดทำงาน")
                break
            print("[gps] ยังไม่ได้ตำแหน่ง (รอสัญญาณดาวเทียม)...")
        else:
            lat, lng = pos
            try:
                nearby = fetch_nearby(api_base, lat, lng)
            except OSError as e:
                print(f"[api] เรียกเซิร์ฟเวอร์ไม่สำเร็จ: {e}", file=sys.stderr)
                nearby = None

            if nearby is not None:
                nearby_ids = {p["id"] for p in nearby}

                beeped &= nearby_ids  # จุดที่ออกนอกรัศมีแล้ว -> รีเซ็ตให้ beep ใหม่ได้เมื่อเข้ามาอีกรอบ

                # beep ครั้งเดียวตอนเพิ่งเข้ารัศมี ALERT_RADIUS_M
                for p in nearby:
                    if p["distance_m"] > ALERT_RADIUS_M:
                        continue
                    if p["id"] not in beeped:
                        beeped.add(p["id"])
                        beep()

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
                        help="โหมดจำลอง: อ่านพิกัดจากไฟล์ (.geojson เส้นทางเดียวกับเว็บ ?mock=1 "
                             "หรือ .csv บรรทัดละ lat,lng)")
    parser.add_argument("--once", action="store_true",
                        help="ใช้กับ --route เท่านั้น: วิ่งจบเส้นทางครั้งเดียวแล้วหยุด แทนที่จะวนซ้ำ")
    args = parser.parse_args()

    if args.gpsd:
        position_source = GpsdReader()
    elif args.test:
        position_source = FixedPosition(*args.test)
    else:
        position_source = RoutePlayer(args.route, loop=not args.once)

    setup_buzzer()
    try:
        run(args.api.rstrip("/"), position_source)
    except KeyboardInterrupt:
        print("\nหยุดการทำงาน")
    finally:
        if GPIO is not None:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
