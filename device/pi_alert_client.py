#!/usr/bin/env python3
"""pi_alert_client.py — ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi (สำหรับติดบนรถเมล์)"""

import argparse
import collections
import glob
import json
import math
import select
import pathlib
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

DEFAULT_ALERT_RADIUS_M = 500      # เริ่มพูดเตือนเมื่อเข้าใกล้จุดเสี่ยงเท่านี้ (เมตร)
DEFAULT_EXIT_RADIUS_M = 600      # ต้องออกไกลกว่านี้ก่อน ถึงจะเตือนจุดเดิมซ้ำได้
ALERT_RADIUS_M = DEFAULT_ALERT_RADIUS_M
EXIT_RADIUS_M = DEFAULT_EXIT_RADIUS_M

DEFAULT_HEADING_WINDOW_DEG = 30  # นับว่า "ข้างหน้า" ถ้าเบนจากหัวรถไม่เกินนี้ (180 = ปิดการกรอง)
HEADING_WINDOW_DEG = DEFAULT_HEADING_WINDOW_DEG
HEADING_MIN_MOVE_M = 15          # วิธีสำรอง: ต้องขยับเกินนี้ก่อนถึงเชื่อทิศที่คำนวณจากพิกัด

COG_MIN_SPEED_KMH = 5            # ช้ากว่านี้ไม่รับทิศใหม่ เพราะตอนรถจอด COG หมุนสุ่ม
COG_HOLD_MAX_S = 120             # จอดนานเกินนี้ = ทิ้งทิศเก่า ถือว่าไม่รู้ทิศ
COURSE_WINDOW_S = 0.5            # เฉลี่ยทิศย้อนหลังกี่วินาที (ยาวไปจะตามการเลี้ยวไม่ทัน)

POLL_INTERVAL_S = 1              # รอบของลูปหลัก: อ่าน GPS -> ถาม API -> ตัดสินใจเตือน (วินาที)
HTTP_TIMEOUT_S = 5               # รอเซิร์ฟเวอร์ตอบนานสุดเท่านี้
REPORT_LOCATION = True           # ส่งพิกัดขึ้นเว็บให้เห็นหมุดรถแบบเรียลไทม์

GPSD_HOST, GPSD_PORT = "127.0.0.1", 2947

# พอร์ตที่ไล่หาตัวรับ GPS ตามลำดับ (ชื่อ by-id ก่อน เพราะไม่สลับเลขเวลาเสียบ USB หลายตัว)
GPS_PORT_GLOBS = ["/dev/serial/by-id/*GPS*", "/dev/serial/by-id/*u-blox*",
                  "/dev/ttyACM*", "/dev/ttyUSB*"]
GPS_BAUD = 115200                # ต้องตรงกับที่ตั้งไว้ในโมดูล ไม่งั้นอ่านได้แต่ตัวอักษรมั่ว
GPS_CHECK_SECONDS = 20           # --checkgps ฟังสัญญาณนานเท่านี้
DEFAULT_GPS_UPDATE_HZ = 10       # สั่งให้โมดูลส่งข้อมูลกี่ครั้งต่อวินาที (0 = ไม่ตั้งค่า)
GPS_UPDATE_HZ = DEFAULT_GPS_UPDATE_HZ

NMEA_KEEP = ("RMC", "VTG", "GGA")   # ประโยคที่ใช้จริง: ทิศ ความเร็ว พิกัด จำนวนดาว
NMEA_DROP = ("GSV", "GSA", "GLL")   # ปิดทิ้ง ไม่ได้ใช้ และ GSV กินสายจนล้นที่ 10Hz

UBX_KEY_RATE_MEAS = 0x30210001   # คีย์ตั้งคาบการวัด หน่วย ms (100 = 10Hz)
UBX_KEY_MSGOUT_UART1 = {         # คีย์เปิด/ปิดประโยค NMEA แต่ละชนิด (0 = ปิด, 1 = ทุกรอบ)
    "GGA": 0x209100BB, "GLL": 0x209100CA, "GSA": 0x209100C0,
    "GSV": 0x209100C5, "RMC": 0x209100AC, "VTG": 0x209100B1,
}
UBX_LAYER_RAM = 0x01             # เขียนลง RAM อย่างเดียว ไม่แตะ FLASH กันตั้งค่าผิดแล้วกู้ไม่ได้

sys.stdout.reconfigure(line_buffering=True)


def _haversine_m(lat1, lon1, lat2, lon2):
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2):
    """ทิศจากจุดหนึ่งไปอีกจุด 0-360 องศา (0 = เหนือ, 90 = ตะวันออก)"""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_lon = math.radians(lon2 - lon1)
    y = math.sin(d_lon) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(d_lon)
    return (math.degrees(math.atan2(y, x)) + 360) % 360


def _angle_diff_deg(a, b):
    """ผลต่างสองมุมเอาทางที่สั้นกว่า 0-180 (350 กับ 10 ต่างกัน 20 ไม่ใช่ 340)"""
    d = abs(a - b) % 360
    return 360 - d if d > 180 else d


class HeadingTracker:
    """ติดตามทิศที่รถมุ่งหน้า จากตำแหน่งที่ขยับไปจริง"""

    def __init__(self, min_move_m=None):
        self.min_move_m = HEADING_MIN_MOVE_M if min_move_m is None else min_move_m
        self.anchor = None
        self.heading = None

    def update(self, lat, lng):
        if self.anchor is None:
            self.anchor = (lat, lng)
            return self.heading
        if _haversine_m(*self.anchor, lat, lng) >= self.min_move_m:
            self.heading = _bearing_deg(*self.anchor, lat, lng)
            self.anchor = (lat, lng)
        return self.heading

    def get(self):
        return self.heading


class CourseTracker:
    """ติดตามทิศจากค่า COG ที่ตัวรับ GPS ส่งมาโดยตรง (ไม่ใช่จากการลบพิกัด)"""

    def __init__(self, min_speed_kmh=None, hold_max_s=None):
        self.min_speed_kmh = COG_MIN_SPEED_KMH if min_speed_kmh is None else min_speed_kmh
        self.hold_max_s = COG_HOLD_MAX_S if hold_max_s is None else hold_max_s
        self.course = None
        self.updated_at = 0.0

    def _expire(self, now):
        if self.course is not None and now - self.updated_at > self.hold_max_s:
            self.course = None
        return self.course

    def update(self, course_deg, speed_kmh, now=None):
        """ป้อน COG + ความเร็วรอบนี้ คืนทิศล่าสุดที่เชื่อได้ (องศา) หรือ None"""
        now = time.monotonic() if now is None else now
        self._expire(now)
        if course_deg is None or speed_kmh is None:
            return self.course
        if speed_kmh < self.min_speed_kmh:
            return self.course
        self.course = course_deg % 360
        self.updated_at = now
        return self.course

    def get(self, now=None):
        return self._expire(time.monotonic() if now is None else now)


HEADING_NEAR_BYPASS_M = 30


def is_ahead(heading_deg, user_lat, user_lng, point_lat, point_lng, window_deg):
    """จุดนี้อยู่ข้างหน้ารถไหม — ยังไม่รู้ทิศ / window >= 180 / ใกล้มาก = ถือว่าใช่เสมอ"""
    if heading_deg is None or window_deg >= 180:
        return True
    if _haversine_m(user_lat, user_lng, point_lat, point_lng) <= HEADING_NEAR_BYPASS_M:
        return True
    to_point = _bearing_deg(user_lat, user_lng, point_lat, point_lng)
    return _angle_diff_deg(heading_deg, to_point) <= window_deg


class FixedPosition:
    """โหมดทดสอบ: พิกัดคงที่"""

    name = "fixed"

    def __init__(self, lat, lng):
        self.lat, self.lng = lat, lng

    def read(self):
        return self.lat, self.lng


class RoutePlayer:
    """โหมดจำลอง: อ่านพิกัดจากไฟล์ วนซ้ำเมื่อจบไฟล์ (หรือหยุดครั้งเดียวถ้า loop=False)"""

    name = "route"

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


def _nmea_degrees(value, hemi):
    """แปลงพิกัดรูปแบบ NMEA (ddmm.mmmm / dddmm.mmmm) เป็นองศาทศนิยม"""
    if not value or not hemi:
        return None
    dot = value.find(".")
    if dot < 3:
        return None
    deg = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    result = deg + minutes / 60.0
    return -result if hemi in ("S", "W") else result


def _nmea_float(value):
    """แปลงฟิลด์ NMEA เป็น float — ฟิลด์ว่างคืน None"""
    if not value:
        return None
    try:
        return float(value)
    except ValueError:
        return None


def _nmea_checksum_ok(line):
    """ตรวจ checksum ท้ายประโยค NMEA (*XX = XOR ของทุกตัวอักษรระหว่าง $ กับ *)"""
    if not line.startswith("$") or "*" not in line:
        return False
    body, _, given = line[1:].partition("*")
    calc = 0
    for ch in body:
        calc ^= ord(ch)
    try:
        return calc == int(given[:2], 16)
    except ValueError:
        return False


# ---------- UBX binary protocol (ใช้ตั้งค่าโมดูลเท่านั้น ไม่ได้ใช้อ่านพิกัด) ----------
def _ubx_frame(msg_class, msg_id, payload=b""):
    """ประกอบเฟรม UBX: B5 62 | class id | ความยาว (2 ไบต์ little-endian) | payload | checksum"""
    body = bytes([msg_class, msg_id]) + len(payload).to_bytes(2, "little") + payload
    ck_a = ck_b = 0
    for b in body:
        ck_a = (ck_a + b) & 0xFF
        ck_b = (ck_b + ck_a) & 0xFF
    return b"\xb5\x62" + body + bytes([ck_a, ck_b])


def _ubx_valset(pairs, layers=UBX_LAYER_RAM):
    """UBX-CFG-VALSET (0x06 0x8A) — ตั้งค่าหลายคีย์ในเฟรมเดียว"""
    size_bytes = {0x01: 1, 0x02: 1, 0x03: 2, 0x04: 4, 0x05: 8}
    payload = bytes([0x00, layers, 0x00, 0x00])
    for key, value in pairs:
        n = size_bytes[(key >> 28) & 0x07]
        payload += key.to_bytes(4, "little") + int(value).to_bytes(n, "little")
    return _ubx_frame(0x06, 0x8A, payload)


def _ubx_read(f, want, timeout_s):
    """อ่านสตรีมจนเจอเฟรม UBX ที่ class/id ตรงกับ want คืน (class, id, payload) หรือ None"""
    want = set(want)
    buf = b""
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        remaining = deadline - time.monotonic()
        if not select.select([f], [], [], max(0.05, min(0.5, remaining)))[0]:
            continue
        chunk = f.read(512)
        if not chunk:
            continue
        buf += chunk
        while True:
            i = buf.find(b"\xb5\x62")
            if i < 0 or len(buf) - i < 8:
                break
            length = int.from_bytes(buf[i + 4:i + 6], "little")
            if len(buf) - i < 8 + length:
                break
            frame = buf[i:i + 8 + length]
            buf = buf[i + 8 + length:]
            cls_id = (frame[2], frame[3])
            if cls_id in want:
                return cls_id[0], cls_id[1], frame[6:6 + length]
        if len(buf) > 8192:
            buf = buf[-4096:]
    return None


def _ubx_text(raw):
    """ฟิลด์ข้อความใน UBX เป็นความยาวคงที่เติมศูนย์ท้าย — ตัดตรงศูนย์ตัวแรก"""
    return raw.split(b"\x00")[0].decode("ascii", "replace")


def _ubx_mon_ver(port, timeout_s=2.0):
    """ถาม UBX-MON-VER ว่าเป็นชิปรุ่นอะไร เฟิร์มแวร์/โปรโตคอลเวอร์ชันไหน"""
    try:
        with open(port, "r+b", buffering=0) as f:
            f.write(_ubx_frame(0x0A, 0x04))
            got = _ubx_read(f, {(0x0A, 0x04)}, timeout_s)
    except OSError as e:
        return {"error": str(e)}
    if got is None:
        return None
    payload = got[2]
    info = {"sw": _ubx_text(payload[0:30]), "hw": _ubx_text(payload[30:40]), "ext": []}
    for i in range(40, len(payload), 30):
        line = _ubx_text(payload[i:i + 30])
        if line:
            info["ext"].append(line)
    return info


def _ubx_configure_port(port, hz=None, timeout_s=2.0):
    """ตั้ง update rate + ปิดประโยคที่ไม่ใช้ ผ่าน UBX-CFG-VALSET (เขียนลง RAM เท่านั้น)"""
    hz = GPS_UPDATE_HZ if hz is None else hz
    if not hz:
        return {"skipped": True}
    pairs = [(UBX_KEY_RATE_MEAS, int(round(1000 / hz)))]
    for name in NMEA_DROP:
        pairs.append((UBX_KEY_MSGOUT_UART1[name], 0))
    for name in NMEA_KEEP:
        pairs.append((UBX_KEY_MSGOUT_UART1[name], 1))
    try:
        with open(port, "r+b", buffering=0) as f:
            f.write(_ubx_valset(pairs))
            got = _ubx_read(f, {(0x05, 0x01), (0x05, 0x00)}, timeout_s)
    except OSError as e:
        return {"error": str(e)}
    if got is None:
        return {"acked": None, "hz": hz}   # ไม่ตอบเลย = น่าจะไม่รองรับ UBX
    return {"acked": got[1] == 0x01, "hz": hz}


def _measure_nmea_rate(port, seconds=3.0):
    """นับว่าประโยคไหนเข้ามากี่ครั้งต่อวินาทีจริง ๆ"""
    counts = collections.Counter()
    bytes_in = 0
    try:
        with open(port, "rb", buffering=0) as f:
            buf = b""
            deadline = time.monotonic() + seconds
            while time.monotonic() < deadline:
                if not select.select([f], [], [], 0.3)[0]:
                    continue
                chunk = f.read(1024)
                if not chunk:
                    continue
                bytes_in += len(chunk)
                buf += chunk
                *lines, buf = buf.split(b"\n")
                for line in lines:
                    text = line.strip().decode("ascii", "replace")
                    if _nmea_checksum_ok(text):
                        counts[text.split(",")[0][3:]] += 1
    except OSError as e:
        return {"error": str(e)}
    return {"per_s": {k: v / seconds for k, v in counts.items()},
            "bytes_per_s": bytes_in / seconds, "seconds": seconds}


class CircularCourseSmoother:
    """เฉลี่ยทิศแบบวงกลมบนหน้าต่างเวลา — เฉลี่ยองศาตรง ๆ ไม่ได้"""

    def __init__(self, window_s=None, min_speed_kmh=None):
        self.window_s = COURSE_WINDOW_S if window_s is None else window_s
        self.min_speed_kmh = COG_MIN_SPEED_KMH if min_speed_kmh is None else min_speed_kmh
        self.samples = collections.deque()   # (เวลา, มุมองศา)
        self.last_good = None

    def add(self, course_deg, speed_kmh, now=None):
        now = time.monotonic() if now is None else now
        if course_deg is not None and speed_kmh is not None and speed_kmh >= self.min_speed_kmh:
            self.samples.append((now, course_deg % 360))
        return self.get(now)

    def get(self, now=None):
        now = time.monotonic() if now is None else now
        while self.samples and now - self.samples[0][0] > self.window_s:
            self.samples.popleft()
        if not self.samples:
            return self.last_good
        if len(self.samples) == 1:
            # ตัวอย่างเดียว = ค่าเฉลี่ยคือตัวมันเอง คืนตรง ๆ เลี่ยงเศษทศนิยมจาก atan2
            self.last_good = self.samples[0][1]
            return self.last_good
        sum_x = sum(math.cos(math.radians(a)) for _, a in self.samples)
        sum_y = sum(math.sin(math.radians(a)) for _, a in self.samples)
        # ความยาวเวกเตอร์ลัพธ์บอกว่าตัวอย่างในหน้าต่างไปทางเดียวกันแค่ไหน (1 = ตรงกันหมด)
        if math.hypot(sum_x, sum_y) / len(self.samples) < 0.3:
            return self.last_good
        self.last_good = (math.degrees(math.atan2(sum_y, sum_x)) + 360) % 360
        return self.last_good


class NmeaSerialReader:
    """อ่านพิกัดจากตัวรับ GPS USB (BE-609U) ที่พูด NMEA 0183 — ไม่ต้องมี pyserial/gpsd"""

    name = "serial"

    def __init__(self, port=None):
        self.port = port or self.find_port()
        if not self.port:
            sys.exit(
                "หาตัวรับ GPS ไม่เจอ — ตรวจว่าเสียบสาย USB แล้ว\n"
                "  ดูรายการพอร์ต:  ls -l /dev/serial/by-id/ /dev/ttyACM* /dev/ttyUSB*\n"
                "  ดูว่า Linux เห็นอุปกรณ์ไหม:  lsusb\n"
                "  ถ้าเจอพอร์ตแต่โค้ดหาไม่เจอ ระบุเองได้:  --serial /dev/ttyUSB0"
            )
        self.last_fix = None
        self.speed_kmh = None
        self.course = None          # COG ที่ผ่าน CircularCourseSmoother แล้ว
        self.course_raw = None      # COG ดิบรอบล่าสุด (ไว้เทียบใน log ว่าการเฉลี่ยทำอะไรไป)
        self.satellites = None
        self.fix_quality = 0
        # VTG มาก่อน RMC: VTG มีทั้ง COG อ้าง true north และความเร็วเป็น กม./ชม. อยู่ใน
        self._vtg_seen = False
        # เฉลี่ยทิศในเธรดอ่าน (ทุกประโยคที่เข้ามา) ไม่ใช่ในลูปหลักที่โพลทุก 1 วินาที
        self._smoother = CircularCourseSmoother()
        self._lock = threading.Lock()
        self._configure_port()
        # ตั้งค่าโมดูลก่อนเปิดเธรดอ่านเสมอ — ระหว่างตั้งค่าต้องอ่าน ACK กลับมาจากพอร์ตเดียวกัน
        self.config_result = _ubx_configure_port(self.port, GPS_UPDATE_HZ)
        self._print_config_result()
        threading.Thread(target=self._reader_loop, daemon=True).start()

    def _print_config_result(self):
        r = self.config_result
        if r.get("skipped"):
            return
        keep = "+".join(NMEA_KEEP)
        if r.get("error"):
            print(f"[gps] ตั้งค่าโมดูลไม่ได้ ({r['error']}) — ใช้อัตราเดิมของโมดูลต่อไป",
                  file=sys.stderr)
        elif r.get("acked") is True:
            print(f"[gps] ตั้งโมดูลเป็น {r['hz']}Hz · เหลือประโยค {keep} "
                  f"(ปิด {'+'.join(NMEA_DROP)}) · เขียนลง RAM ไม่แตะ FLASH")
        elif r.get("acked") is False:
            print("[gps] โมดูลปฏิเสธการตั้งค่า (NAK) — ใช้อัตราเดิมต่อไป", file=sys.stderr)
        else:
            print("[gps] โมดูลไม่ตอบคำสั่ง UBX (อาจไม่ใช่ชิป u-blox) — ใช้อัตราเดิมต่อไป",
                  file=sys.stderr)

    @staticmethod
    def find_port():
        for pattern in GPS_PORT_GLOBS:
            matches = sorted(glob.glob(pattern))
            if matches:
                return matches[0]
        return None

    def _configure_port(self):
        """ตั้ง baud rate + โหมด raw ด้วย stty (ล้มเหลวก็ไปต่อ — ttyACM ไม่ต้องตั้งอยู่แล้ว)"""
        try:
            subprocess.run(
                ["stty", "-F", self.port, str(GPS_BAUD), "raw", "-echo"],
                check=True, capture_output=True, timeout=5,
            )
        except (OSError, subprocess.SubprocessError) as e:
            print(f"[gps] ตั้งค่าพอร์ตไม่สำเร็จ ({e}) — ลองอ่านต่อไปเลย", file=sys.stderr)

    def _reader_loop(self):
        while True:
            try:
                with open(self.port, "r", encoding="ascii", errors="replace") as f:
                    for line in f:
                        self._handle(line.strip())
            except OSError as e:
                print(f"[gps] อ่านพอร์ต {self.port} ไม่ได้: {e} — ลองใหม่ใน 3 วิ", file=sys.stderr)
                time.sleep(3)

    def _handle(self, line):
        if not _nmea_checksum_ok(line):
            return
        parts = line.split(",")
        kind = parts[0][3:]

        if kind == "GGA" and len(parts) >= 10:
            quality = parts[6]
            self.fix_quality = int(quality) if quality.isdigit() else 0
            if parts[7].isdigit():
                self.satellites = int(parts[7])
            if self.fix_quality > 0:
                lat = _nmea_degrees(parts[2], parts[3])
                lng = _nmea_degrees(parts[4], parts[5])
                if lat is not None and lng is not None:
                    with self._lock:
                        self.last_fix = (lat, lng)

        elif kind == "RMC" and len(parts) >= 8:
            if parts[2] != "A":
                return
            lat = _nmea_degrees(parts[3], parts[4])
            lng = _nmea_degrees(parts[5], parts[6])
            if lat is not None and lng is not None:
                with self._lock:
                    self.last_fix = (lat, lng)
            try:
                self.speed_kmh = float(parts[7]) * 1.852
            except ValueError:
                pass
            # field 8 = course over ground (องศา อ้าง true north) — ว่างได้เมื่อรถจอดนิ่ง
            if len(parts) >= 9 and not self._vtg_seen:
                self._update_course(_nmea_float(parts[8]))

        elif kind == "VTG" and len(parts) >= 8:
            # $--VTG,cogTrue,T,cogMag,M,knots,N,kmh,K,mode
            self._vtg_seen = True
            speed = _nmea_float(parts[7])
            if speed is not None:
                self.speed_kmh = speed
            self._update_course(_nmea_float(parts[1]))

    def _update_course(self, raw_course):
        """ป้อน COG ดิบเข้า smoother แล้วเก็บผลที่เฉลี่ยแล้วไว้ให้ลูปหลักมาหยิบ"""
        smoothed = self._smoother.add(raw_course, self.speed_kmh)
        with self._lock:
            self.course_raw = raw_course
            self.course = smoothed

    def read(self):
        with self._lock:
            return self.last_fix


class GpsdReader:
    """อ่านพิกัดจาก gpsd ผ่าน TCP JSON protocol (ไม่ต้องใช้ไลบรารี gps3)"""

    name = "gpsd"

    def __init__(self):
        self.sock = None
        self.buffer = b""
        self.last_fix = None
        self.course = None      # gpsd TPV field "track" = COG องศา อ้าง true north (เฉลี่ยแล้ว)
        self.course_raw = None
        self.speed_kmh = None   # TPV field "speed" เป็น m/s ต้องคูณ 3.6
        self.satellites = None
        self._smoother = CircularCourseSmoother()

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
                if report.get("class") == "SKY" and "satellites" in report:
                    self.satellites = len(report["satellites"])
                if report.get("class") != "TPV":
                    continue
                if "lat" in report and "lon" in report:
                    self.last_fix = (report["lat"], report["lon"])
                # track/speed อาจไม่มาในทุกรายงาน — ไม่มีก็คงค่าเดิมไว้
                if report.get("speed") is not None:
                    self.speed_kmh = float(report["speed"]) * 3.6
                if report.get("track") is not None:
                    self.course_raw = float(report["track"])
                    self.course = self._smoother.add(self.course_raw, self.speed_kmh)
        except OSError as e:
            print(f"[gpsd] ขาดการเชื่อมต่อ: {e} — จะลองใหม่", file=sys.stderr)
            self.sock = None
        return self.last_fix


_AUDIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "audio"


def _pick_clip_dir():
    """เลือกชุดไฟล์เสียง — ชุด "ดัง" ใน audio/loud/ มาก่อนถ้ามี"""
    loud = _AUDIO_DIR / "loud"
    if loud.is_dir() and any(loud.glob("alert_*.mp3")):
        return loud
    return _AUDIO_DIR


CLIP_DIR = _pick_clip_dir()

DEFAULT_AUDIO_DEVICE = "plughw:2,0"
AUDIO_DEVICE = DEFAULT_AUDIO_DEVICE

DEFAULT_VOLUME_PCT = 100
VOLUME_PCT = DEFAULT_VOLUME_PCT

ANNOUNCE_VOLUME_RATIO = 0.5
ANNOUNCE_VOLUME_MIN_PCT = 50

BOTNOI_ENABLED = True

VOICE_CLIPS = {
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงต่ำ โปรดขับขี่ด้วยความระมัดระวัง":
        "alert_01.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง":
        "alert_02.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
        "alert_04.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ":
        "alert_05.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
        "alert_06.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดลดความเร็ว และระวังรถตัดผ่านทางแยก":
        "alert_07.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดใช้ความเร็วไม่เกิน 90 กิโลเมตรต่อชั่วโมง":
        "alert_09.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดลดความเร็วก่อนเข้าโค้ง และงดแซงในช่วงนี้":
        "alert_10.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดลดความเร็วก่อนเข้าโค้ง และงดแซงในช่วงนี้":
        "alert_11.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดเว้นระยะห่าง และระวังรถชะลอตัวเพื่อกลับรถ":
        "alert_12.mp3",
}


def _player_cmd():
    """หาโปรแกรมเล่น mp3 ที่มีในเครื่อง — คืน None ถ้าไม่มีเลย"""
    for exe in ("mpg123", "mpg321", "ffplay"):
        if shutil.which(exe):
            return exe
    return None


def _play_mp3(data, label):
    """เล่น mp3 จาก bytes ผ่าน stdin — คืน True ถ้าเล่นจบปกติ"""
    exe = _player_cmd()
    if exe is None or not data:
        return False
    dev = ["-a", AUDIO_DEVICE] if AUDIO_DEVICE and exe in ("mpg123", "mpg321") else []
    vol = ["-f", str(int(32768 * VOLUME_PCT / 100))] if exe == "mpg123" and VOLUME_PCT != 100 else []
    cmd = {
        "mpg123": [exe, "-q", *dev, *vol, "-"],
        "mpg321": [exe, "-q", *dev, "-"],
        "ffplay": [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", "-"],
    }[exe]
    try:
        if subprocess.run(cmd, input=data, timeout=30).returncode != 0:
            return False
    except (OSError, subprocess.TimeoutExpired) as e:
        print(f"   [เสียง] เล่นไฟล์ไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    print(f"   [เสียง] {label}")
    return True


# ---------- เสียง beep บอกระยะ (แทน buzzer GPIO ที่ถอดออกไปแล้ว) ----------
# AASHTO Green Book 7th ed. Table 3-3 — Decision Sight Distance (เมตร), Avoidance Maneuver E
DSD_E_M = {50: 200, 60: 235, 70: 275, 80: 315, 90: 360,
           100: 405, 110: 435, 120: 470}

MAX_DESIGN_SPEED_KMH = 120   # เพดานทางพิเศษของไทย เกินจากนี้ใช้ค่าที่ 120

# ใช้เมื่อยังไม่รู้ความเร็ว (เพิ่งจับดาวได้ / GPS ไม่ส่งค่ามาใน RMC) — เลือกค่ากลางของ
DEFAULT_SPEED_KMH = 90

# ต่ำกว่านี้ถือว่ารถไม่ได้เคลื่อนที่ — คงค่าความเร็วเดิมไว้ ไม่ให้ระยะ beep ร่วงไปขั้นต่ำสุด
SPEED_HOLD_MIN_KMH = 5

BEEP_DIR = _AUDIO_DIR / "beep"
BEEP_LOOP_S = 2.0        # ความยาวไฟล์แพตเทิร์น = จังหวะเปลี่ยนได้ทุก 2 วินาที
BEEP_FAR_FRAC = 0.66     # เกิน 66% ของระยะ DSD = จังหวะช้า
BEEP_MID_FRAC = 0.33     # 33-66% = ปานกลาง · ต่ำกว่านั้น = ถี่สุด

# ถือว่า "ขับผ่านไปแล้ว" เมื่อระยะเพิ่มจากค่าต่ำสุดที่เคยวัดได้เกินค่านี้ แล้วหยุด beep
BEEP_RECEDE_MIN_M = 25

# ล็อกทางออกเสียง — พอถอด buzzer ออก เสียงพูดกับ beep ก็ใช้ลำโพงตัวเดียวกัน และ plughw:
AUDIO_LOCK = threading.Lock()
SPEECH_ACTIVE = threading.Event()

_beep_warned = False


def beep_start_m(speed_kmh):
    """ระยะที่เริ่ม beep บอกระยะ = DSD Maneuver E ที่ความเร็วรถขณะนั้น"""
    v = DEFAULT_SPEED_KMH if speed_kmh is None else min(speed_kmh, MAX_DESIGN_SPEED_KMH)
    for s in sorted(DSD_E_M):
        if v <= s:
            return float(DSD_E_M[s])
    return float(DSD_E_M[max(DSD_E_M)])


def _play_wav(path):
    """เล่น WAV ออกลำโพงตัวเดียวกับเสียงพูด — คืน True ถ้าเล่นจบปกติ"""
    exe = shutil.which("aplay") or shutil.which("ffplay")
    if exe is None or not path.exists():
        return False
    if exe.endswith("aplay"):
        dev = ["-D", AUDIO_DEVICE] if AUDIO_DEVICE else []
        cmd = [exe, "-q", *dev, str(path)]
    else:
        cmd = [exe, "-nodisp", "-autoexit", "-loglevel", "quiet", str(path)]
    try:
        return subprocess.run(cmd, timeout=10).returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def play_lead_beep():
    """beep สองครั้งนำหน้าประโยคเตือน — แทน chime เดิมของเว็บ"""
    global _beep_warned
    with AUDIO_LOCK:
        if _play_wav(BEEP_DIR / "beep_lead.wav"):
            return True
    if not _beep_warned:
        _beep_warned = True
        print("   [beep] เล่นไฟล์ beep ไม่ได้ — สร้างด้วย: "
              "python3 scripts/build_beep_clips.py", file=sys.stderr)
    return False


def beep_pattern_for(points, closest_seen, speed_kmh):
    """เลือกจังหวะ beep จากจุดที่ใกล้ที่สุดเทียบกับระยะเริ่ม beep ของความเร็วปัจจุบัน"""
    radius = beep_start_m(speed_kmh)
    best = None
    for p in points:
        pid, d = p["id"], p["distance_m"]
        low = closest_seen.get(pid)
        if low is None or d < low:
            closest_seen[pid] = low = d
        if d > radius:
            continue
        if d > low + BEEP_RECEDE_MIN_M:      # ขับผ่านไปแล้ว เลิกร้องจุดนี้
            continue
        frac = d / radius
        if best is None or frac < best:
            best = frac
    if best is None:
        return None
    if best > BEEP_FAR_FRAC:
        return "far"
    if best > BEEP_MID_FRAC:
        return "mid"
    return "near"


# รถแทบหยุดนิ่ง (ต่ำกว่า SPEED_HOLD_MIN_KMH) ติดต่อกันนานเท่านี้ -> หยุด beep
# จอดติดไฟแดงหน้าจุดเสี่ยง beep ที่ร้องต่อไม่ได้เตือนอะไรเพิ่ม กลายเป็นเสียงรบกวน
# รอ 3 วิก่อน กันเสียงดับ ๆ ติด ๆ ตอนรถติดที่หยุดแป๊บเดียวแล้วคลานต่อ (ต้องตรงกับ PARKED_MUTE_MS)
PARKED_MUTE_S = 3.0


class ParkedDetector:
    """ตรวจว่ารถจอดนิ่งนานพอจะหยุด beep หรือยัง — ไม่รู้ความเร็ว (None) = ไม่นับว่าจอด"""

    def __init__(self, min_speed_kmh=None, mute_after_s=None):
        self.min_speed_kmh = SPEED_HOLD_MIN_KMH if min_speed_kmh is None else min_speed_kmh
        self.mute_after_s = PARKED_MUTE_S if mute_after_s is None else mute_after_s
        self.stopped_since = None

    def update(self, speed_kmh, now=None):
        """ป้อนความเร็วรอบนี้ คืน True เมื่อจอดนิ่งติดต่อกันถึงเกณฑ์"""
        now = time.monotonic() if now is None else now
        if speed_kmh is None or speed_kmh >= self.min_speed_kmh:
            self.stopped_since = None
            return False
        if self.stopped_since is None:
            self.stopped_since = now
        return now - self.stopped_since >= self.mute_after_s


class BeepLoop:
    """เล่นไฟล์แพตเทิร์น beep วนซ้ำในเธรดแยก จนกว่าจะสั่งเปลี่ยนหรือหยุด"""

    def __init__(self):
        self._pattern = None
        self._stop = threading.Event()
        self._thread = None

    def set_pattern(self, name):
        """name = 'far' | 'mid' | 'near' | None (None = เงียบ)"""
        self._pattern = name

    def start(self):
        if self._thread is not None:
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self):
        self._pattern = None
        self._stop.set()

    def _run(self):
        global _beep_warned
        while not self._stop.is_set():
            name = self._pattern
            # เสียงพูดมาก่อนเสมอ — ยอมให้ beep ขาดช่วง ดีกว่าให้ประโยคเตือนถูกกลืน
            if name is None or SPEECH_ACTIVE.is_set():
                time.sleep(0.1)
                continue
            with AUDIO_LOCK:
                ok = _play_wav(BEEP_DIR / f"beep_{name}.wav")
            if not ok:
                if not _beep_warned:
                    _beep_warned = True
                    print("   [beep] เล่นไฟล์ beep ไม่ได้ — สร้างด้วย: "
                          "python3 scripts/build_beep_clips.py", file=sys.stderr)
                time.sleep(BEEP_LOOP_S)   # เล่นไม่ได้ก็อย่าวนรัวเปล่า ๆ


def _speak_clip(text):
    """ชั้น 0 — ไฟล์เสียง Botnoi ที่อัดไว้ล่วงหน้า"""
    name = VOICE_CLIPS.get(text)
    if name is None:
        return False
    path = CLIP_DIR / name
    if not path.exists():
        return False
    return _play_mp3(path.read_bytes(), f"ชั้น 0 ไฟล์ที่อัดไว้ {name}")


def _speak_botnoi(text, api_base):
    """ชั้น 1 — Botnoi สดผ่าน proxy /api/tts ของเซิร์ฟเวอร์เรา"""
    global BOTNOI_ENABLED
    if not BOTNOI_ENABLED:
        return False
    url = f"{api_base}/api/tts?" + urllib.parse.urlencode({"text": text})
    try:
        with urllib.request.urlopen(url, timeout=30) as resp:
            data = resp.read()
    except urllib.error.HTTPError as e:
        if e.code == 503:
            BOTNOI_ENABLED = False
            print("   [เสียง] ข้ามชั้น 1 ทั้งรอบ: เซิร์ฟเวอร์ยังไม่ได้ตั้ง BOTNOI_TOKEN")
        else:
            print(f"   [เสียง] Botnoi สดไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    except Exception as e:
        print(f"   [เสียง] Botnoi สดไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    return _play_mp3(data, "ชั้น 1 Botnoi สด")


def _speak_google(text):
    """ชั้น 2 — Google translate_tts (ต้องมีเน็ต)"""
    if len(text) > 190:
        return False
    url = "https://translate.google.com/translate_tts?" + urllib.parse.urlencode(
        {"ie": "UTF-8", "q": text, "tl": "th", "client": "tw-ob"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
    except Exception as e:
        print(f"   [เสียง] Google ไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    return _play_mp3(data, "ชั้น 2 Google")


def _speak_espeak(text):
    """ชั้น 3 — espeak-ng ในเครื่อง ใช้ตอนไม่มีเน็ต (เสียงแข็ง ใช้เป็นตัวสำรองเท่านั้น)"""
    if not shutil.which("espeak-ng"):
        return False
    try:
        amp = str(min(200, max(0, VOLUME_PCT)))
        if subprocess.run(
            ["espeak-ng", "-v", "th", "-s", "150", "-a", amp, text], timeout=30
        ).returncode != 0:
            return False
    except (OSError, subprocess.TimeoutExpired):
        return False
    print("   [เสียง] ชั้น 3 espeak-ng (สำรอง)")
    return True


def speak(text, api_base):
    """พูดข้อความเตือน ไล่ลงทีละชั้นจนกว่าจะมีชั้นไหนสำเร็จ"""
    print(f"   >> {text}")
    SPEECH_ACTIVE.set()
    try:
        with AUDIO_LOCK:
            for layer in (
                lambda: _speak_clip(text),
                lambda: _speak_botnoi(text, api_base),
                lambda: _speak_google(text),
                lambda: _speak_espeak(text),
            ):
                if layer():
                    return True
    finally:
        SPEECH_ACTIVE.clear()
    print("   [เสียง] ไม่มีชั้นไหนพูดได้ — เหลือแค่ beep", file=sys.stderr)
    return False


def announce(text, speak_enabled, api_base):
    """บอกสถานะของตัวระบบเอง (ไม่ใช่การเตือนจุดเสี่ยง) — ใช้แทนจอตอนออกภาคสนาม"""
    print(f"[สถานะ] {text}")
    if not speak_enabled:
        return
    global VOLUME_PCT
    saved = VOLUME_PCT
    VOLUME_PCT = max(ANNOUNCE_VOLUME_MIN_PCT, int(saved * ANNOUNCE_VOLUME_RATIO))
    try:
        speak(text, api_base)
    finally:
        VOLUME_PCT = saved


def fetch_nearby(api_base, lat, lng, heading_deg=None):
    """ดึงจุดเสี่ยงในรัศมี — ส่งทิศไปด้วยเพื่อให้เซิร์ฟเวอร์กรองเฉพาะจุดข้างหน้าให้เลย"""
    params = {"lat": f"{lat:.6f}", "lng": f"{lng:.6f}", "radius": EXIT_RADIUS_M}
    if heading_deg is not None and HEADING_WINDOW_DEG < 180:
        params["heading"] = f"{heading_deg:.1f}"
        params["cone_deg"] = f"{HEADING_WINDOW_DEG:.1f}"
    query = urllib.parse.urlencode(params)
    url = f"{api_base}/api/risk-points/nearby?{query}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read())["points"]


def report_location(api_base, lat, lng, source, heading_deg=None):
    """ส่งพิกัดปัจจุบันขึ้น POST /api/device/location ให้หน้าเว็บวาดหมุดรถเรียลไทม์"""
    global _report_failed_once
    if not REPORT_LOCATION:
        return
    body = {"source": source}
    if lat is not None and lng is not None:
        body.update(lat=round(lat, 6), lng=round(lng, 6))
    # ทิศส่งขึ้นไปด้วยเพื่อให้เว็บหมุนหมุดรถให้ตรงกับทิศที่วิ่งจริง (None = ยังไม่รู้ทิศ)
    if heading_deg is not None:
        body["heading"] = round(heading_deg, 1)
    if source_telemetry:
        body.update(source_telemetry())
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base}/api/device/location", data=data,
        headers={"Content-Type": "application/json"}, method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S):
            pass
        _report_failed_once = False
    except (OSError, ValueError) as e:
        if not _report_failed_once:
            print(f"[report] ส่งพิกัดขึ้นเว็บไม่สำเร็จ: {e} (จะเงียบไว้จนกว่าจะส่งได้)",
                  file=sys.stderr)
            _report_failed_once = True


_report_failed_once = False
source_telemetry = None


def _lan_ip():
    """หา IP ของ Pi ในวงแลน เพื่อบอก URL ที่เปิดจากมือถือได้จริง"""
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("8.8.8.8", 80))
            return sk.getsockname()[0]
    except OSError:
        return None


def _web_page(api_base):
    """เดาว่าควรเปิดหน้าไหน จากชุดข้อมูลที่ API กำลังแจกอยู่"""
    try:
        with urllib.request.urlopen(f"{api_base}/api/health", timeout=HTTP_TIMEOUT_S) as r:
            dataset = json.loads(r.read()).get("dataset", "")
    except (OSError, ValueError):
        return "index.html"
    return "test-nstda.html" if "nstda" in dataset else "index.html"


def run(api_base, position_source, speak_enabled=True):
    announced = set()          # จุดที่พูดประโยคเตือนไปแล้ว (cooldown ของเสียงพูด)
    closest_seen = {}          # id -> ระยะต่ำสุดที่เคยวัดได้ ใช้ดูว่าขับผ่านไปหรือยัง
    last_moving_speed = None   # ความเร็วล่าสุดตอนที่รถยังเคลื่อนที่จริง
    parked = ParkedDetector()  # จอดนิ่งเกิน 3 วิ -> หยุด beep (เสียงพูดไม่เกี่ยว)
    beeper = BeepLoop()
    beeper.start()

    global source_telemetry
    if hasattr(position_source, "speed_kmh"):
        source_telemetry = lambda: {
            "speed_kmh": (round(position_source.speed_kmh, 1)
                          if position_source.speed_kmh is not None else None),
            "satellites": getattr(position_source, "satellites", None),
        }
    voice = "เปิด" if speak_enabled else "ปิด"
    player = _player_cmd() or "ไม่พบโปรแกรมเล่น mp3"
    beep_ready = "พร้อม" if (BEEP_DIR / "beep_far.wav").exists() else "ไม่มีไฟล์"
    print(
        f"เริ่มเฝ้าระวังจุดเสี่ยง (API: {api_base}, เตือนที่ {ALERT_RADIUS_M} ม. "
        f"{'ทุกทิศรอบตัว' if HEADING_WINDOW_DEG >= 180 else f'เฉพาะข้างหน้า ±{HEADING_WINDOW_DEG:.0f}°'}, "
        f"เสียงพูด: {voice} [{player} -> {AUDIO_DEVICE or 'default'} {VOLUME_PCT}%], "
        f"beep: {beep_ready})"
    )
    hz_note = getattr(position_source, "config_result", None)
    if hz_note and hz_note.get("acked") is True:
        print(f"GPS: {hz_note['hz']:g}Hz · เฉลี่ยทิศแบบวงกลมหน้าต่าง {COURSE_WINDOW_S} วิ")
    if REPORT_LOCATION:
        page = _web_page(api_base)
        ip = _lan_ip()
        print("ส่งตำแหน่งขึ้นเว็บ: เปิด — เปิดลิงก์นี้เพื่อดูหมุด 🚌 บนแผนที่")
        print(f"   บน Pi เครื่องนี้ : {api_base}/{page}")
        if ip:
            print(f"   จากมือถือ       : http://{ip}:8000/{page}  (ต่อ WiFi วงเดียวกัน)")

    # ทิศมาจาก COG ของตัวรับเป็นหลัก ส่วน HeadingTracker (ลบพิกัด) เป็นตัวสำรอง
    course = CourseTracker()
    heading = HeadingTracker()

    announce("ระบบพร้อมทำงาน กำลังค้นหาสัญญาณดาวเทียม", speak_enabled, api_base)
    got_first_fix = False

    while True:
        started = time.monotonic()
        pos = position_source.read()
        if pos is None:
            if getattr(position_source, "finished", False):
                print("จบเส้นทางจำลองแล้ว — หยุดทำงาน")
                break
            sats = getattr(position_source, "satellites", None)
            print(f"[gps] ยังไม่ได้ตำแหน่ง · เห็นดาว {'?' if sats is None else sats} ดวง"
                  " (รอสัญญาณดาวเทียม)...")
            report_location(api_base, None, None,
                            getattr(position_source, "name", None))
            beeper.set_pattern(None)
        else:
            lat, lng = pos
            if not got_first_fix:
                got_first_fix = True
                announce("รับสัญญาณดาวเทียมแล้ว เริ่มแจ้งเตือนจุดเสี่ยง",
                         speak_enabled, api_base)
            speed_now = getattr(position_source, "speed_kmh", None)
            cog_deg = course.update(getattr(position_source, "course", None), speed_now)
            fallback_deg = heading.update(lat, lng)
            heading_deg = cog_deg if cog_deg is not None else fallback_deg
            heading_src = "COG" if cog_deg is not None else "พิกัด"
            report_location(api_base, lat, lng, getattr(position_source, "name", None),
                            heading_deg)
            try:
                nearby = fetch_nearby(api_base, lat, lng, heading_deg)
            except OSError as e:
                print(f"[api] เรียกเซิร์ฟเวอร์ไม่สำเร็จ: {e}", file=sys.stderr)
                nearby = None
                beeper.set_pattern(None)

            if nearby is not None:
                nearby_ids = {p["id"] for p in nearby}

                announced &= nearby_ids
                for pid in [k for k in closest_seen if k not in nearby_ids]:
                    del closest_seen[pid]

                ahead = [p for p in nearby
                         if is_ahead(heading_deg, lat, lng, p["lat"], p["lng"],
                                     HEADING_WINDOW_DEG)]

                for p in ahead:
                    if p["distance_m"] > ALERT_RADIUS_M:
                        continue
                    if p["id"] not in announced:
                        announced.add(p["id"])
                        # beep นำเล่นเสมอแม้ปิดเสียงพูด — เหมือนที่ buzzer เคยทำ
                        play_lead_beep()
                        if speak_enabled:
                            speak(p["alert_message"], api_base)

                # beep บอกระยะคิดแยกจาก cooldown ของเสียงพูด เพราะตอบคนละคำถาม:
                if speed_now is not None and speed_now >= SPEED_HOLD_MIN_KMH:
                    last_moving_speed = speed_now
                # คิดจังหวะทุกรอบให้ closest_seen ตามระยะจริงต่อไป แต่รถจอดนิ่งเกิน 3 วิให้เงียบ
                moving_pattern = beep_pattern_for(ahead, closest_seen, last_moving_speed)
                beeper.set_pattern(None if parked.update(speed_now) else moving_pattern)

                nearest = nearby[0] if nearby else None
                status = (
                    f"ใกล้สุด: {nearest.get('road_label') or nearest['road']} "
                    f"{nearest['distance_m']:.0f} ม. ({nearest['level']})"
                    if nearest
                    else f"ไม่มีจุดเสี่ยงในรัศมี {EXIT_RADIUS_M} ม."
                )
                hdg = ("ทิศ ?" if heading_deg is None
                       else f"ทิศ {heading_deg:.0f}° ({heading_src})")
                print(f"[{time.strftime('%H:%M:%S')}] ({lat:.5f}, {lng:.5f}) {hdg} {status}")

        time.sleep(max(0, POLL_INTERVAL_S - (time.monotonic() - started)))


SAMPLE_TEXT = "ข้างหน้าอีกประมาณ 500 เมตร มีจุดอันตราย กรุณาลดความเร็ว และใช้ความระมัดระวังเป็นพิเศษ"


def check_voice(api_base):
    """ตรวจว่าทำไมเสียงพูดไม่ออก — ไล่ทีละชั้นแล้วบอกว่าติดที่อะไร"""
    print("=" * 62)
    print("ตรวจระบบเสียงพูดแจ้งเตือน")
    print("=" * 62)

    print()
    print("1) ไฟล์เสียงที่อัดไว้")
    print("   โฟลเดอร์:", CLIP_DIR)
    print("   ชุดที่ใช้:", "ดัง (audio/loud)" if CLIP_DIR.name == "loud"
          else "ต้นฉบับ — สร้างชุดดังได้ด้วย scripts/boost_voice_clips.py")
    if not CLIP_DIR.is_dir():
        print("   [ไม่ผ่าน] ไม่มีโฟลเดอร์นี้ — ยังไม่ได้ git pull ใช่ไหม")
    else:
        clips = sorted(set(VOICE_CLIPS.values()))
        missing = [c for c in clips if not (CLIP_DIR / c).exists()]
        if missing:
            print("   [ไม่ผ่าน] ขาด", len(missing), "ไฟล์:", ", ".join(missing))
        else:
            print("   [ผ่าน] ครบทั้ง", len(clips), "ไฟล์")

    print()
    print("2) โปรแกรมเล่นเสียงในเครื่อง")
    for exe in ("mpg123", "mpg321", "ffplay", "espeak-ng"):
        path = shutil.which(exe)
        print("  ", "[มี]  " if path else "[ไม่มี]", exe.ljust(10), path or "")
    if _player_cmd() is None:
        print()
        print("   >>> ไม่มีตัวเล่น mp3 เลย นี่คือสาเหตุที่ได้ยินแต่ beep")
        print("   >>> แก้ด้วย:  sudo apt install -y mpg123")
    if AUDIO_DEVICE:
        print("   อุปกรณ์เสียงที่บังคับใช้:", AUDIO_DEVICE)

    print()
    print("3) ทดลองพูดประโยคตัวอย่าง (ระดับสูง)")
    print("-" * 62)
    ok = speak(SAMPLE_TEXT, api_base)
    print("-" * 62)

    print()
    if ok:
        print("โปรแกรมเล่นเสียงสำเร็จ — ถ้ายังไม่ได้ยินเสียงจากลำโพง ให้ตรวจต่อที่:")
        print("   amixer sset Master 90%       เร่งเสียงให้สุด")
        print("   aplay -l                     ดูว่ามีการ์ดเสียงอะไรบ้าง")
        print("   sudo raspi-config            System Options > Audio เลือกช่องที่ต่อลำโพง")
        print("   ถ้าต้องเจาะจงการ์ด ให้เพิ่ม  --audio-device plughw:2,0 (ดูเลขการ์ดจาก aplay -l)")
    else:
        print("ไม่มีชั้นไหนเล่นได้เลย — ดูบรรทัด [เสียง] ด้านบนว่าติดที่อะไร")
    return ok


def _alert_client_service_running():
    """service ตัวจริงกำลังจับพอร์ต GPS อยู่ไหม"""
    try:
        r = subprocess.run(["systemctl", "is-active", "mtec-alert-client"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def check_gps(port=None):
    """ดูว่าตัวรับ GPS ส่งอะไรมาบ้าง จับดาวได้กี่ดวง — ใช้ตอน --serial แล้วไม่ได้พิกัด"""
    print("=" * 62)
    print("ตรวจตัวรับ GPS (Beltian BE-609U)")
    print("=" * 62)

    if _alert_client_service_running():
        print("❌ mtec-alert-client.service ทำงานอยู่ — หยุดก่อนแล้วค่อยตรวจ")
        print()
        print("   sudo systemctl stop mtec-autoheal.timer mtec-alert-client")
        print("   python3 device/pi_alert_client.py --checkgps")
        print("   sudo systemctl start mtec-autoheal.timer mtec-alert-client   # เปิดกลับ")
        print()
        print("   ต้องปิด mtec-autoheal.timer ด้วย ไม่งั้นมันจะเปิด service กลับมา")
        print("   ภายใน 5 นาที แล้วมาแย่งพอร์ต GPS กลางคันจนผลตรวจเพี้ยน")
        print()
        print("   เหตุผล: พอร์ตอนุกรมอ่านพร้อมกันสองโปรเซสไม่ได้ ข้อมูล NMEA จะถูกแบ่งกันไป")
        print("   คนละครึ่งจนอ่านไม่ออกทั้งคู่ ผลตรวจจะขึ้นว่าไม่เห็นดาวเลยทั้งที่ GPS ปกติดี")
        return False

    port = port or NmeaSerialReader.find_port()
    if not port:
        print("❌ หาพอร์ต GPS ไม่เจอ")
        print("   ls -l /dev/serial/by-id/ /dev/ttyACM* /dev/ttyUSB*")
        print("   lsusb          # ดูว่า Linux เห็นตัวอุปกรณ์ไหม")
        print("   ถ้าเห็นใน lsusb แต่ไม่มีไฟล์พอร์ต แปลว่าไดรเวอร์ยังไม่โหลด ลองถอดเสียบใหม่")
        return False
    print(f"✓ พบพอร์ต: {port}")

    try:
        with open(port, "rb"):
            pass
    except PermissionError:
        print(f"❌ ไม่มีสิทธิ์อ่าน {port}")
        print("   sudo usermod -a -G dialout $USER   แล้ว logout/login (หรือ reboot) หนึ่งครั้ง")
        return False
    except OSError as e:
        print(f"❌ เปิดพอร์ตไม่ได้: {e}")
        print("   อาจมี gpsd จองพอร์ตอยู่:  sudo systemctl stop gpsd gpsd.socket")
        return False
    print("✓ เปิดพอร์ตได้")

    # ---- ระบุตัวชิป ----
    print()
    print("1) ตัวชิปในโมดูล (UBX-MON-VER)")
    ver = _ubx_mon_ver(port)
    if ver is None:
        print("   ไม่ตอบคำสั่ง UBX — อาจไม่ใช่ชิป u-blox หรือปิดโปรโตคอล UBX ไว้")
        print("   ไม่ใช่ปัญหา: ระบบอ่าน NMEA อย่างเดียวก็ทำงานได้ครบ แค่ตั้ง update rate ไม่ได้")
    elif ver.get("error"):
        print("   เปิดพอร์ตเพื่อถามไม่ได้:", ver["error"])
    else:
        print(f"   เฟิร์มแวร์ : {ver['sw']}")
        print(f"   ฮาร์ดแวร์  : {ver['hw']}")
        for line in ver["ext"]:
            print(f"   ส่วนขยาย   : {line}")
        print("   >>> ตอบกลับมาเป็นโครงสร้าง = เป็นชิป u-blox และรองรับ UBX ยืนยันแล้ว")

    # ---- อัตราก่อน/หลังตั้งค่า ----
    budget = GPS_BAUD / 10   # 8N1 = 10 บิตต่อ 1 ไบต์

    def show_rate(label, r):
        if r.get("error"):
            print(f"   {label}: อ่านไม่ได้ ({r['error']})")
            return
        pct = r["bytes_per_s"] / budget * 100
        order = sorted(r["per_s"].items(), key=lambda kv: -kv[1])
        detail = " · ".join(f"{k} {v:.1f}/วิ" for k, v in order) or "ไม่มีประโยคที่ checksum ผ่าน"
        print(f"   {label}: {detail}")
        print(f"   {' ' * len(label)}  รวม {r['bytes_per_s']:,.0f} ไบต์/วิ = "
              f"{pct:.1f}% ของสาย {GPS_BAUD} bps")

    print()
    print("2) อัตราข้อมูลที่ตัวรับส่งมา")
    show_rate("ก่อนตั้งค่า", _measure_nmea_rate(port, 3.0))

    if GPS_UPDATE_HZ:
        print()
        print(f"3) ตั้งค่าเป็น {GPS_UPDATE_HZ:g}Hz + ปิด {'/'.join(NMEA_DROP)}")
        res = _ubx_configure_port(port, GPS_UPDATE_HZ)
        if res.get("error"):
            print("   ล้มเหลว:", res["error"])
        elif res.get("acked") is True:
            print("   ✓ โมดูลตอบ ACK — ตั้งค่าสำเร็จ (เขียนลง RAM เท่านั้น ไม่แตะ FLASH)")
        elif res.get("acked") is False:
            print("   ✗ โมดูลตอบ NAK — ไม่รับค่านี้ (อัตราสูงเกินที่รุ่นนี้ทำได้?)")
        else:
            print("   ไม่มีคำตอบกลับมา — น่าจะไม่รองรับ UBX")
        show_rate("หลังตั้งค่า", _measure_nmea_rate(port, 3.0))
        print()
        print("   หมายเหตุ: ค่านี้อยู่ใน RAM หายเมื่อถอดไฟ — ตั้งใจให้เป็นแบบนี้")
        print("   ไคลเอนต์ตั้งใหม่ให้เองทุกครั้งที่เริ่มทำงาน จึงไม่ต้องเขียน FLASH")

    print()
    print("4) ฟังพิกัดจริง")
    reader = NmeaSerialReader(port)
    print(f"\nกำลังฟัง NMEA {GPS_CHECK_SECONDS} วินาที...")
    print("(ตัวรับที่เพิ่งเปิดเครื่องต้องใช้เวลาจับดาวครั้งแรก 30 วิ - 2 นาที และต้องอยู่กลางแจ้ง")
    print(" หรือริมหน้าต่าง — ในอาคารลึก ๆ จับดาวไม่ได้เลย)")
    for i in range(GPS_CHECK_SECONDS):
        time.sleep(1)
        fix = reader.read()
        sats = reader.satellites if reader.satellites is not None else "?"
        if fix:
            cog = ("ทิศ -" if reader.course is None
                   else f"ทิศ {reader.course:.1f}° (ดิบ {reader.course_raw:.1f}°)"
                   if reader.course_raw is not None else f"ทิศ {reader.course:.1f}°")
            spd = "-" if reader.speed_kmh is None else f"{reader.speed_kmh:.1f} กม./ชม."
            print(f"  [{i + 1:2d}วิ] ✓ พิกัด {fix[0]:.6f}, {fix[1]:.6f} · ดาว {sats} ดวง"
                  f" · {cog} · {spd}")
        else:
            print(f"  [{i + 1:2d}วิ] ยังไม่ได้พิกัด · เห็นดาว {sats} ดวง · fix quality {reader.fix_quality}")

    fix = reader.read()
    print()
    if fix:
        print(f"✅ GPS ใช้งานได้ — พิกัดล่าสุด {fix[0]:.6f}, {fix[1]:.6f}")
        print(f"   เช็คว่าตรงจริงไหม: https://www.google.com/maps?q={fix[0]:.6f},{fix[1]:.6f}")
        print(f"\n   ใช้งานจริง:  python3 device/pi_alert_client.py --serial")
        return True

    print("❌ ยังไม่ได้พิกัดใน", GPS_CHECK_SECONDS, "วินาที")
    if reader.satellites:
        print(f"   แต่เห็นดาว {reader.satellites} ดวงแล้ว = ตัวรับทำงานปกติ แค่ยังจับไม่พอ")
        print("   เอาตัวรับออกไปกลางแจ้งแล้วรออีก 1-2 นาที")
    else:
        print("   ไม่เห็นดาวเลย และไม่มีข้อมูล NMEA เข้ามา — เป็นไปได้ว่า:")
        print("   1. มีโปรเซสอื่นแย่งอ่านพอร์ตอยู่ (ตัวที่รันมือค้างไว้):")
        print("      pgrep -af pi_alert_client.py")
        print("   2. เป็นพอร์ตผิดตัว (ลอง --checkgps /dev/ttyUSB0 หรือพอร์ตอื่นใน ls)")
        print(f"   3. baud rate ไม่ใช่ {GPS_BAUD} (ตัวรับรุ่นอื่นใช้ค่าอื่น — ไล่ด้วย stty แล้ว cat ดู)")
        print(f"   4. ดู NMEA ดิบตรง ๆ:  stty -F {port} {GPS_BAUD} raw -echo && cat {port}")
    return False


def main():
    parser = argparse.ArgumentParser(description="ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="URL ของ EMMA Risk Point API (ค่าเริ่มต้น: http://localhost:8000)")
    parser.add_argument("--volume", type=int, default=DEFAULT_VOLUME_PCT, metavar="PCT",
                        help=f"ความดังเสียงพูดเป็นเปอร์เซ็นต์ (ค่าเริ่มต้น {DEFAULT_VOLUME_PCT}) "
                             "หาเพดานที่ปลอดภัยด้วย scripts/measure_audio_headroom.py")
    parser.add_argument("--audio-device", metavar="DEV", default=DEFAULT_AUDIO_DEVICE,
                        help=f"อุปกรณ์เสียงที่ส่งให้ mpg123 (-a) ค่าเริ่มต้น {DEFAULT_AUDIO_DEVICE} "
                             "= การ์ด MAX98357A · ดูเลขการ์ดของเครื่องด้วย aplay -l")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--checkvoice", action="store_true",
                        help="ตรวจว่าทำไมเสียงพูดไม่ออก แล้วลองพูดประโยคตัวอย่างหนึ่งครั้ง")
    source.add_argument("--serial", nargs="?", const="", metavar="PORT",
                        help="อ่านพิกัดจริงจากตัวรับ GPS USB (BE-609U) ที่พูด NMEA "
                             "ไม่ใส่พอร์ต = หาให้อัตโนมัติ · ระบุเองได้ เช่น /dev/ttyUSB0")
    source.add_argument("--checkgps", nargs="?", const="", metavar="PORT",
                        help="ตรวจว่าตัวรับ GPS ทำงานไหม จับดาวได้กี่ดวง (ไม่ยิง API)")
    source.add_argument("--gpsd", action="store_true", help="อ่านพิกัดจริงจาก gpsd")
    parser.add_argument("--gps-hz", type=float, metavar="HZ", default=DEFAULT_GPS_UPDATE_HZ,
                        help=f"อัตราที่สั่งให้โมดูลส่งข้อมูล (ค่าเริ่มต้น {DEFAULT_GPS_UPDATE_HZ}) "
                             "0 = ไม่ตั้งค่า ใช้ค่าที่โมดูลจำไว้ · เขียนลง RAM เท่านั้น")
    source.add_argument("--test", nargs=2, type=float, metavar=("LAT", "LNG"),
                        help="โหมดทดสอบ: ใช้พิกัดคงที่")
    source.add_argument("--route", metavar="FILE",
                        help="โหมดจำลอง: อ่านพิกัดจากไฟล์ (.geojson เส้นทางเดียวกับเว็บ ?mock=1 "
                             "หรือ .csv บรรทัดละ lat,lng)")
    parser.add_argument("--alert-radius", type=float, default=DEFAULT_ALERT_RADIUS_M, metavar="M",
                        help=f"ระยะที่เริ่มเตือน (เมตร, ค่าเริ่มต้น {DEFAULT_ALERT_RADIUS_M}) "
                             "สนามทดสอบในอุทยานวิทยาศาสตร์ฯ ใช้ 60 (ต้องตรงกับ test-nstda.html)")
    parser.add_argument("--exit-radius", type=float, default=DEFAULT_EXIT_RADIUS_M, metavar="M",
                        help=f"ระยะที่ถือว่าออกนอกรัศมีแล้ว เตือนจุดเดิมซ้ำได้ "
                             f"(เมตร, ค่าเริ่มต้น {DEFAULT_EXIT_RADIUS_M}) สนามทดสอบใช้ 80")
    parser.add_argument("--heading-window", type=float, metavar="DEG",
                        default=DEFAULT_HEADING_WINDOW_DEG,
                        help=f"มุมที่ถือว่าอยู่ข้างหน้ารถ (องศา ค่าเริ่มต้น {DEFAULT_HEADING_WINDOW_DEG}) "
                             "180 = ปิดการกรองทิศ เตือนทุกทิศรอบตัว "
                             "180 = ปิดการกรอง เตือนทุกทิศเหมือนเดิม")
    parser.add_argument("--no-speak", action="store_true",
                        help="ปิดเสียงพูด ใช้แค่ beep อย่างเดียว")
    parser.add_argument("--no-report", action="store_true",
                        help="ไม่ต้องส่งพิกัดขึ้นเว็บ (หน้าแผนที่จะไม่เห็นหมุดรถ)")
    parser.add_argument("--once", action="store_true",
                        help="ใช้กับ --route เท่านั้น: วิ่งจบเส้นทางครั้งเดียวแล้วหยุด แทนที่จะวนซ้ำ")
    args = parser.parse_args()

    global AUDIO_DEVICE, VOLUME_PCT, ALERT_RADIUS_M, EXIT_RADIUS_M, REPORT_LOCATION
    global HEADING_WINDOW_DEG, GPS_UPDATE_HZ
    AUDIO_DEVICE = args.audio_device
    VOLUME_PCT = max(10, min(1000, args.volume))
    ALERT_RADIUS_M = args.alert_radius
    EXIT_RADIUS_M = max(args.exit_radius, ALERT_RADIUS_M)
    REPORT_LOCATION = not args.no_report
    HEADING_WINDOW_DEG = max(0.0, min(180.0, args.heading_window))
    # 18Hz คือเพดานที่สเปก BE-609U ระบุ — สูงกว่านั้นโมดูลจะ NAK ทิ้งอยู่ดี
    GPS_UPDATE_HZ = max(0.0, min(18.0, args.gps_hz))

    if args.checkvoice:
        sys.exit(0 if check_voice(args.api.rstrip("/")) else 1)
    if args.checkgps is not None:
        sys.exit(0 if check_gps(args.checkgps or None) else 1)

    if args.serial is not None:
        position_source = NmeaSerialReader(args.serial or None)
    elif args.gpsd:
        position_source = GpsdReader()
    elif args.test:
        position_source = FixedPosition(*args.test)
    else:
        position_source = RoutePlayer(args.route, loop=not args.once)

    try:
        run(args.api.rstrip("/"), position_source, speak_enabled=not args.no_speak)
    except KeyboardInterrupt:
        print("\nหยุดการทำงาน")


if __name__ == "__main__":
    main()
