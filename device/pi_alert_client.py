#!/usr/bin/env python3
"""
pi_alert_client.py — ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi (สำหรับติดบนรถเมล์)

หลักการทำงาน (วนลูปทุก POLL_INTERVAL_S วินาที):
  1. อ่านพิกัด GPS ปัจจุบันของรถ (จากตัวรับ GPS ต่อ USB, gpsd หรือโหมดจำลอง)
  2. ยิง GET /api/risk-points/nearby?lat=..&lng=..&radius=600 ไปที่เซิร์ฟเวอร์
  3. ถ้ามีจุดเสี่ยงใกล้กว่า 500 เมตรและยังไม่เคยเตือน -> สั่ง buzzer ที่ต่อขา GPIO13 (เลขแบบ BCM)
     ร้อง 1 วิ เป็นเสียงนำ แล้วพูดประโยคเตือนภาษาไทยที่ได้จาก alert_message ของ API
     (เสียงพูดมี 4 ชั้น ดูหัวข้อ "เสียงพูดแจ้งเตือน" ด้านล่าง ปิดด้วย --no-speak ได้)
  4. ส่งพิกัดตัวเองขึ้น POST /api/device/location ทุกรอบ เพื่อให้หน้าเว็บบนมือถือ
     เห็นหมุดรถแบบเรียลไทม์ (ปิดด้วย --no-report ได้ · ส่งไม่สำเร็จไม่กระทบการเตือน)

กติกา cooldown ต่อจุด:
  - เตือนครั้งแรกเมื่อเข้ามาในรัศมี ALERT_RADIUS_M (500 ม.)
  - เตือนจุดเดิมซ้ำได้ต่อเมื่อออกไกลกว่า EXIT_RADIUS_M (600 ม.) แล้วกลับเข้ามาใหม่

กติกาทิศทาง (ต้องตรงกับ js/alert.js เสมอ):
  - เตือนเฉพาะจุดในมุม ±HEADING_WINDOW_DEG (90) จากทิศที่รถมุ่งหน้า จุดที่ผ่านไปแล้วเงียบ
  - ยังไม่รู้ทิศ (รถเพิ่งออก/จอดนิ่ง) หรือใกล้กว่า 30 ม. = ไม่กรอง เตือนไว้ก่อน
  - แยกได้แค่ข้างหน้า/ข้างหลัง ไม่ได้แยกเลนขาขึ้น-ขาล่อง (ดูหมายเหตุที่ค่าคงที่ด้านล่าง)
  - ปิดด้วย --heading-window 180 ถ้าอยากได้พฤติกรรมก่อนมีฟีเจอร์นี้

ใช้ Python standard library เป็นหลัก ยกเว้นส่วนคุม buzzer ที่ต้องมี RPi.GPIO
(มากับ Raspberry Pi OS อยู่แล้ว ไม่ต้อง pip install เพิ่ม — ถ้าไม่มีจะแค่ข้ามการสั่ง buzzer เฉยๆ)
ส่วนเสียงพูดไม่ได้ใช้ audio library ของ Python เลย — สั่ง mpg123/espeak-ng ผ่าน subprocess

ฮาร์ดแวร์ที่ใช้จริง (Raspberry Pi 5):
  - เสียงพูด  MAX98357A (I2S DAC + แอมป์ Class-D 3W ในตัว) -> ลำโพง 8Ω 2W
              Vin ขา2(5V) · GND ขา6 · BCLK ขา12 · LRC ขา35 · DIN ขา40
              SD/GAIN ปล่อยลอย · ต้องมี dtoverlay=max98357a,no-sdmode ใน config.txt
              ** Pi 5 ไม่มีแจ็ค 3.5 มม. และจอ HDMI ที่ใช้ไม่รับเสียง จึงต้องมีโมดูลนี้ **
  - GPS       Beltian BE-609U (ตัวรับ GPS แบบ USB) เสียบพอร์ต USB ช่องไหนก็ได้
              คุยด้วยโปรโตคอล NMEA 0183 ผ่าน serial — โผล่เป็น /dev/ttyACM0 (ชิป u-blox
              ต่อ USB ตรง) หรือ /dev/ttyUSB0 (ชิปแปลง UART เช่น PL2303/CP210x)
              โค้ดหาพอร์ตให้เองจาก /dev/serial/by-id/ ไม่ต้องระบุถ้าเสียบตัวเดียว
  - buzzer    GPIO13 (ขา 33) — ไม่ชนกับ I2S ที่ใช้ GPIO18/19/21
  รายละเอียดการต่อสายทั้งหมดอยู่ใน README หัวข้อ "ต่อลำโพงกับ Raspberry Pi 5"

ตัวอย่างการใช้งาน (ค่า --audio-device/--volume ตั้ง default ให้ตรงกับชุดข้างบนแล้ว
ไม่ต้องพิมพ์เองถ้าใช้ฮาร์ดแวร์ชุดนี้):
  # ตรวจว่าเสียงพูดออกลำโพงไหม พร้อมบอกว่าติดตรงไหนถ้าไม่ออก
  python3 device/pi_alert_client.py --checkvoice

  # จำลองการขับด้วยเส้นทางเดียวกับที่เว็บใช้ตอน ?mock=1 (เตือน 7 ครั้ง ครบสามระดับ)
  python3 device/pi_alert_client.py --route data/mock_route.geojson --once

  # ใช้งานจริงกับ GPS BE-609U ที่เสียบ USB (แนะนำ — ไม่ต้องติดตั้ง gpsd)
  python3 device/pi_alert_client.py --serial
  python3 device/pi_alert_client.py --serial /dev/ttyUSB0   # ระบุพอร์ตเองถ้าหาไม่เจอ

  # ดู NMEA ดิบ ๆ ว่าตัวรับส่งอะไรมาบ้าง จับดาวได้กี่ดวง (ใช้ตอนหาสาเหตุ GPS ไม่ติด)
  python3 device/pi_alert_client.py --checkgps

  # ใช้งานจริงผ่าน gpsd แทน (ถ้าติดตั้ง gpsd ไว้อยู่แล้ว)
  python3 device/pi_alert_client.py --gpsd

  # ทดสอบภาคสนามในอุทยานวิทยาศาสตร์ฯ — รัศมี 60/80 ต้องตรงกับที่ test-nstda.html ตั้งไว้
  # และ API ต้องรันด้วยชุด risk_points_nstda_test.geojson ไม่งั้น Pi จะเตือนคนละจุดกับเว็บ
  RISK_DATA_FILE=data/risk_points_nstda_test.geojson python3 -m uvicorn api.server:app --host 0.0.0.0
  python3 device/pi_alert_client.py --serial --alert-radius 60 --exit-radius 80

  # ทดสอบด้วยพิกัดคงที่ (ไม่ต้องมี GPS) / ปิดเสียงพูดเหลือแค่ buzzer
  python3 device/pi_alert_client.py --test 13.665 100.534
  python3 device/pi_alert_client.py --route data/mock_route.geojson --no-speak

  # ปรับความดัง: 100 = ไม่ขยายซ้ำ (เสียงสะอาด) · เกิน 100 ดังขึ้นแต่เริ่มแตก
  # ต่ำกว่า 100 เบาลงกว่าไฟล์ต้นฉบับ เช่น 50 = ครึ่งหนึ่ง (ต่ำสุดที่รับคือ 10)
  python3 device/pi_alert_client.py --serial --volume 50
  python3 device/pi_alert_client.py --serial --volume 200

  # เครื่องอื่นที่การ์ดเสียงคนละเลข
  python3 device/pi_alert_client.py --serial --audio-device plughw:1,0
"""

import argparse
import glob
import json
import math
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

try:
    import RPi.GPIO as GPIO
except ImportError:
    GPIO = None

# ระยะเตือนมาตรฐานบนถนนนอกพื้นที่ — ปรับได้ด้วย --alert-radius / --exit-radius
# ตอนทดสอบในสนามเล็ก (ถนนวงรอบอุทยานวิทยาศาสตร์ฯ ยาว 1.4 กม. จุดฝั่งตะวันตกห่างกัน 71-125 ม.)
# ต้องย่อลงเหลือ 60/80 ม. ไม่งั้นทุกจุดจะร้องพร้อมกันตั้งแต่ยังไม่ออกรถ
# ** ค่านี้ต้องตรงกับที่ test-nstda.html ตั้งไว้ (alertM 60 / exitM 80) เสมอ **
# ไม่งั้น Pi กับเว็บจะเตือนคนละระยะ แล้วผลทดสอบภาคสนามจะเทียบกันไม่ได้
DEFAULT_ALERT_RADIUS_M = 500
DEFAULT_EXIT_RADIUS_M = 600  # hysteresis กันเด้งเข้าออกตรงขอบรัศมี
ALERT_RADIUS_M = DEFAULT_ALERT_RADIUS_M
EXIT_RADIUS_M = DEFAULT_EXIT_RADIUS_M

# มุมที่ถือว่า "ข้างหน้า" นับจากทิศที่รถมุ่งหน้า (องศา ไปทางละเท่านี้)
# ** ต้องตรงกับ HEADING_WINDOW_DEG ใน js/alert.js เสมอ ไม่งั้นอุปกรณ์กับเว็บเตือนคนละชุด **
#
# 90 = เตือนเฉพาะครึ่งวงกลมด้านหน้า ตัดจุดที่ขับผ่านไปแล้วออก
# วัดกับเส้นทางจริงแล้ว: ลดการเตือนซ้ำซ้อน 41% (สมุทรสาคร รัศมี 500 ม.)
# และ 9% (สนามทดสอบ สวทช. รัศมี 60 ม.) โดยไม่พลาดจุดเสี่ยงใดเลยทั้งสองเส้นทาง
#
# ทำไมไม่แคบกว่า 90: บนถนนโค้ง จุดที่อยู่ข้างหน้าจริงตามแนวถนนเบนจากทิศรถได้มาก
# (รัศมีความโค้งเท่าระยะเตือน -> เบนราว 30 องศา) การพลาดจุดที่ควรเตือนอันตราย
# กว่าการเตือนเกิน จึงเลือกค่าที่ตัดเฉพาะสิ่งที่อยู่ด้านหลังจริง ๆ
#
# ** ข้อจำกัดที่ต้องบอกในรายงาน ** แยกได้แค่ข้างหน้า/ข้างหลัง ไม่ได้แยกเลนขาขึ้น-ขาล่อง
# เลนสวนที่อยู่ข้างหน้า 100 ม. เบนจากทิศรถแค่ 8.5 องศา (ห่างด้านข้างราว 15 ม.)
# ซึ่งน้อยกว่าความคลาดเคลื่อนของ GPS เอง (5-15 ม.) จะแยกเลนได้ต้องทำ map matching กับ OSM
#
# ปิดการกรองได้ด้วย --heading-window 180 (พฤติกรรมก่อนมีฟีเจอร์นี้)
DEFAULT_HEADING_WINDOW_DEG = 90
HEADING_WINDOW_DEG = DEFAULT_HEADING_WINDOW_DEG

# ต้องขยับอย่างน้อยเท่านี้ถึงจะเชื่อทิศ — กัน GPS แกว่งตอนรถจอดทำให้ทิศสุ่มไปมา
HEADING_MIN_MOVE_M = 15
POLL_INTERVAL_S = 3
HTTP_TIMEOUT_S = 5

BUZZER_PIN = 13  # เลข GPIO แบบ BCM (ไม่ใช่ตำแหน่งจริงบนขาเข็มแบบ BOARD — ทดสอบแล้วว่า BCM13 ตรงกับ buzzer ที่ต่อไว้)

GPSD_HOST, GPSD_PORT = "127.0.0.1", 2947

# ตัวรับ GPS แบบ USB (Beltian BE-609U) — คุย NMEA 0183 ผ่าน serial
# ลำดับการหาพอร์ต: /dev/serial/by-id/* ก่อน เพราะชื่อคงที่ ไม่สลับเลขเมื่อเสียบ USB อื่นเพิ่ม
# แล้วค่อย ttyACM* (u-blox ต่อ USB ตรง) และ ttyUSB* (ชิปแปลง UART เช่น PL2303)
GPS_PORT_GLOBS = ["/dev/serial/by-id/*GPS*", "/dev/serial/by-id/*u-blox*",
                  "/dev/ttyACM*", "/dev/ttyUSB*"]
# 9600 เป็นค่าโรงงานของตัวรับ NMEA ส่วนใหญ่ แต่ตัว Beltian BE-609U ที่ใช้จริง
# ตั้งมาจากโรงงานที่ 115200 — ยืนยันแล้วด้วยการไล่ค่า stty ทีละตัว (2026-08-27)
# ที่ 9600/4800/38400/19200/57600 ได้แต่ข้อมูลขยะ (baud ผิดทำให้ตีความบิตพลาด)
# พอลอง 115200 ได้ NMEA ที่อ่านออกทันที ($GNRMC, $GPGSV, ...) — ไม่ใช่ฮาร์ดแวร์เสีย
# ถ้าเปลี่ยนไปใช้ตัวรับรุ่นอื่น ต้องตรวจ baud ใหม่ด้วยวิธีเดียวกัน (ดู README หัวข้อ GPS)
# ถ้าเป็น CDC-ACM (ttyACM) ค่านี้ไม่มีผลจริง เพราะ USB ไม่ได้ใช้ baud rate — ตั้งไว้ก็ไม่เสียหาย
GPS_BAUD = 115200
GPS_CHECK_SECONDS = 20  # ระยะเวลาที่ --checkgps ฟัง NMEA

# ส่งพิกัดขึ้นเซิร์ฟเวอร์ให้หน้าเว็บวาดหมุดรถแบบเรียลไทม์ (ปิดด้วย --no-report)
REPORT_LOCATION = True

# จอง GPIO ของ buzzer สำเร็จหรือยัง — ถ้าไม่สำเร็จยังเดินต่อได้ เหลือแต่เสียงพูด
BUZZER_READY = False

# ให้ log ขึ้นทันทีแม้ stdout ถูก redirect (เช่น รันผ่าน systemd/journald บน Pi)
sys.stdout.reconfigure(line_buffering=True)


# ---------- ทิศทาง (พอร์ตจาก js/distance.js — ต้องให้ผลตรงกันเสมอ) ----------

def _haversine_m(lat1, lon1, lat2, lon2):
    d_lat = math.radians(lat2 - lat1)
    d_lon = math.radians(lon2 - lon1)
    a = (math.sin(d_lat / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(d_lon / 2) ** 2)
    return 2 * 6371000 * math.asin(math.sqrt(a))


def _bearing_deg(lat1, lon1, lat2, lon2):
    """ทิศจากจุดหนึ่งไปอีกจุด 0-360 องศา (0 = เหนือ, 90 = ตะวันออก)

    ใช้สูตร initial bearing ของ great-circle ไม่ใช่การลบพิกัดตรง ๆ เพราะเส้นลองจิจูด
    ลู่เข้าหากันเมื่อเข้าใกล้ขั้วโลก การลบตรง ๆ จะเพี้ยน
    """
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
    """ติดตามทิศที่รถมุ่งหน้า จากตำแหน่งที่ขยับไปจริง

    ทำไมต้องรอให้ขยับครบ HEADING_MIN_MOVE_M: GPS คลาดเคลื่อนตลอดแม้รถจอดนิ่ง
    ถ้าคิดทิศจากทุกคู่พิกัด รถจอดอยู่กับที่จะได้ทิศสุ่มไปมา แล้วการกรอง "ข้างหน้า"
    จะกลายเป็นสุ่มว่าจะเตือนหรือไม่ ต้องรอให้ระยะที่ขยับชนะ noise ก่อน

    get() คืน None จนกว่าจะมั่นใจ — ผู้เรียกต้องถือว่า "ไม่รู้ทิศ = ไม่กรอง"
    ปลอดภัยกว่าเดาแล้วเงียบจุดที่ควรเตือน
    """

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


# ระยะที่ใกล้เกินกว่าจะเชื่อทิศ — ต่ำกว่านี้ให้ผ่านเสมอ ไม่ต้องกรอง
#
# เหตุผล: ทิศจากรถไปยังจุดที่แทบจะทับกันอยู่แล้วไม่มีความหมาย ความคลาดเคลื่อนของ GPS
# (ปกติ 5-15 ม.) ครอบงำการคำนวณจนได้ทิศสุ่ม เช่น ยืนทับจุดพอดีอาจคำนวณได้ว่า
# "จุดอยู่ข้างหลัง 177 องศา" แล้วโดนกรองทิ้งทั้งที่กำลังอยู่บนจุดเสี่ยงนั้น
#
# เจอจริงตอนจำลองขับวนรอบสนามทดสอบ สวทช.: เส้นทางสุ่มตัวอย่างห่างกัน ~39 ม.
# ทำให้รถกระโดดจาก 71 ม. -> 0 ม. -> 72 ม. มีตัวอย่างเดียวที่อยู่ในรัศมี 60 ม.
# และตัวอย่างนั้นทับจุดพอดี ผลคือจุด nstda_w3 ไม่ถูกเตือนเลยทั้งรอบ
# สถานการณ์เดียวกันเกิดกับ GPS จริงได้ เพราะโพลทุก 3 วิ ที่ 60 กม./ชม. = 50 ม./ตัวอย่าง
#
# 30 ม. มาจากการเผื่อความคลาดเคลื่อน GPS สองเท่า และถึงระยะนั้นก็ควรเตือนอยู่แล้ว
# ไม่ว่าจะหันไปทางไหน เพราะอยู่ตรงจุดเสี่ยงพอดี
HEADING_NEAR_BYPASS_M = 30


def is_ahead(heading_deg, user_lat, user_lng, point_lat, point_lng, window_deg):
    """จุดนี้อยู่ข้างหน้ารถไหม — ยังไม่รู้ทิศ / window >= 180 / ใกล้มาก = ถือว่าใช่เสมอ"""
    if heading_deg is None or window_deg >= 180:
        return True
    if _haversine_m(user_lat, user_lng, point_lat, point_lng) <= HEADING_NEAR_BYPASS_M:
        return True
    to_point = _bearing_deg(user_lat, user_lng, point_lat, point_lng)
    return _angle_diff_deg(heading_deg, to_point) <= window_deg


# ---------- แหล่งพิกัด GPS ----------

class FixedPosition:
    """โหมดทดสอบ: พิกัดคงที่"""

    name = "fixed"

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
    """แปลงพิกัดรูปแบบ NMEA (ddmm.mmmm / dddmm.mmmm) เป็นองศาทศนิยม

    NMEA เก็บเป็น "องศา 2-3 หลักแรก ตามด้วยลิปดา" ไม่ใช่องศาทศนิยมตรง ๆ
    เช่น 1345.6789 = 13 องศา 45.6789 ลิปดา = 13.761315 องศา
    ถ้าตีความผิดเป็น 1345.68 องศา จะได้ตำแหน่งหลุดออกนอกโลกไปเลย
    """
    if not value or not hemi:
        return None
    dot = value.find(".")
    if dot < 3:
        return None
    deg = float(value[:dot - 2])
    minutes = float(value[dot - 2:])
    result = deg + minutes / 60.0
    return -result if hemi in ("S", "W") else result


def _nmea_checksum_ok(line):
    """ตรวจ checksum ท้ายประโยค NMEA (*XX = XOR ของทุกตัวอักษรระหว่าง $ กับ *)

    จำเป็นเพราะสัญญาณกวนทำให้ได้บรรทัดที่ตัวเลขเพี้ยนแต่ยังแยกคอลัมน์ได้ปกติ
    ถ้าไม่ตรวจ หมุดจะกระโดดไปคนละที่เป็นครั้งคราวโดยหาสาเหตุไม่เจอ
    """
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


class NmeaSerialReader:
    """อ่านพิกัดจากตัวรับ GPS USB (BE-609U) ที่พูด NMEA 0183 — ไม่ต้องมี pyserial/gpsd

    ทำไมไม่ใช้ pyserial: ทั้งโปรเจกต์ยึด standard library อย่างเดียว และบน Linux
    พอร์ต serial เปิดเป็นไฟล์ธรรมดาได้เลย ส่วนการตั้ง baud rate ยืมคำสั่ง stty ของระบบ

    ทำไมต้องอ่านในเธรดแยก: ตัวรับส่ง NMEA มา 1 ครั้งต่อวินาที แต่ลูปหลักโพลทุก 3 วินาที
    ถ้าอ่านในลูปหลัก จะได้ข้อมูลค้างเก่า และถ้า GPS ยังไม่จับดาว การอ่านจะบล็อกจน
    ลูปเตือนหยุดตามไปด้วย เธรดนี้จึงคอยอ่านทิ้งไว้ตลอด เก็บแต่ fix ล่าสุด
    (หลักการเดียวกับที่ GpsdReader เก็บ last_fix) ลูปหลักแค่มาหยิบไปใช้
    """

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
        self.satellites = None
        self.fix_quality = 0
        self._lock = threading.Lock()
        self._configure_port()
        threading.Thread(target=self._reader_loop, daemon=True).start()

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
                # errors="replace" กันบรรทัดที่สัญญาณกวนจนไม่ใช่ ASCII ทำให้เธรดตายทั้งเธรด
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
        # ตัดตัวอักษรบอกระบบดาวเทียม (GP=GPS, GN=หลายระบบรวม, GL=GLONASS) เอาแต่ชนิดประโยค
        kind = parts[0][3:]

        if kind == "GGA" and len(parts) >= 10:
            # GGA: $--GGA,เวลา,lat,N/S,lng,E/W,คุณภาพfix,จำนวนดาว,HDOP,ความสูง,...
            quality = parts[6]
            self.fix_quality = int(quality) if quality.isdigit() else 0
            if parts[7].isdigit():
                self.satellites = int(parts[7])
            if self.fix_quality > 0:  # 0 = ยังไม่จับดาว พิกัดในบรรทัดนี้เชื่อไม่ได้
                lat = _nmea_degrees(parts[2], parts[3])
                lng = _nmea_degrees(parts[4], parts[5])
                if lat is not None and lng is not None:
                    with self._lock:
                        self.last_fix = (lat, lng)

        elif kind == "RMC" and len(parts) >= 8:
            # RMC: $--RMC,เวลา,สถานะ,lat,N/S,lng,E/W,ความเร็ว(นอต),ทิศ,วันที่,...
            if parts[2] != "A":  # A = ใช้ได้, V = เตือนว่าข้อมูลยังไม่นิ่ง
                return
            lat = _nmea_degrees(parts[3], parts[4])
            lng = _nmea_degrees(parts[5], parts[6])
            if lat is not None and lng is not None:
                with self._lock:
                    self.last_fix = (lat, lng)
            try:
                self.speed_kmh = float(parts[7]) * 1.852  # นอต -> กม./ชม.
            except ValueError:
                pass

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
    """เตรียมขา GPIO ของ buzzer (เรียกครั้งเดียวตอนเริ่มโปรแกรม)

    จองขาไม่ได้ไม่ถือว่าโปรแกรมพัง — ข้ามแค่ buzzer แล้วเตือนด้วยเสียงพูดต่อไป
    เคสที่เจอบ่อยคือ "GPIO busy": ไคลเอนต์รอบก่อนยังไม่ตาย หรือถูก kill -9
    จนไม่ได้เรียก GPIO.cleanup() ขาเลยค้างว่าถูกจองอยู่
    """
    global BUZZER_READY
    if GPIO is None:
        print("   (ไม่พบ RPi.GPIO — buzzer จะไม่ทำงาน ติดตั้งด้วย: sudo apt install python3-rpi.gpio)", file=sys.stderr)
        return
    try:
        GPIO.setmode(GPIO.BCM)  # เลข GPIO แบบ BCM (ยืนยันจากการทดสอบจริงว่าตรงกับ buzzer ที่ต่อไว้ — BUZZER_PIN=13)
        GPIO.setup(BUZZER_PIN, GPIO.OUT, initial=GPIO.LOW)
    except Exception as e:  # noqa: BLE001 — lgpio.error/RuntimeError แล้วแต่เวอร์ชัน
        print(f"   [buzzer] จองขา GPIO{BUZZER_PIN} ไม่ได้: {e}", file=sys.stderr)
        print("   [buzzer] ข้ามเสียง buzzer ใช้เสียงพูดอย่างเดียวต่อไป", file=sys.stderr)
        print("   [buzzer] ถ้าอยากได้ buzzer ด้วย ให้ปิดโปรเซสเก่าก่อน:  pkill -f pi_alert_client.py", file=sys.stderr)
        return
    BUZZER_READY = True


def beep():
    """buzzer ร้อง 1 วิ ผ่านขา GPIO — ตอนเข้าใกล้จุดเสี่ยงในระยะ ALERT_RADIUS_M"""
    print("\a🔔 buzzer")
    if not BUZZER_READY:
        return
    GPIO.output(BUZZER_PIN, GPIO.HIGH)
    time.sleep(1)
    GPIO.output(BUZZER_PIN, GPIO.LOW)


# ---------- เสียงพูดแจ้งเตือน (พอร์ตจาก js/tts.js) ----------
# ลำดับชั้นเดียวกับบนเว็บ ไล่ลงทีละชั้นจนกว่าจะมีชั้นไหนเล่นได้:
#   ชั้น 0  ไฟล์ Botnoi ที่อัดไว้ล่วงหน้าใน audio/ — ไม่ต้องมีเน็ต ไม่เสียพอยท์ เล่นทันที
#   ชั้น 1  Botnoi สดผ่าน /api/tts ของเซิร์ฟเวอร์เอง (ต้องตั้ง BOTNOI_TOKEN ฝั่งเซิร์ฟเวอร์)
#   ชั้น 2  Google translate_tts — ฟรี ไม่ต้องสมัคร แต่ต้องมีเน็ต
#   ชั้น 3  espeak-ng ในเครื่อง — เสียงแข็งกว่ามาก แต่ยังพูดได้ตอนเน็ตหลุด

_AUDIO_DIR = pathlib.Path(__file__).resolve().parent.parent / "audio"


def _pick_clip_dir():
    """เลือกชุดไฟล์เสียง — ชุด "ดัง" ใน audio/loud/ มาก่อนถ้ามี

    audio/loud/ สร้างด้วย scripts/boost_voice_clips.py เป็นชุดที่บีบช่วงไดนามิก
    มาแล้วให้ดังขึ้นราว 6-8 dB สำหรับลำโพงจิ๋วบนอุปกรณ์ ส่วน audio/ ต้นฉบับ
    ปล่อยไว้ให้เว็บใช้ เพราะระดับเสียงนำ (chime) บนเว็บคำนวณจาก RMS ของชุดนั้น
    ลบโฟลเดอร์ loud ทิ้งเมื่อไหร่ก็กลับไปใช้ต้นฉบับเองอัตโนมัติ
    """
    loud = _AUDIO_DIR / "loud"
    if loud.is_dir() and any(loud.glob("alert_*.mp3")):
        return loud
    return _AUDIO_DIR


CLIP_DIR = _pick_clip_dir()

# อุปกรณ์เสียงที่จะส่งให้ mpg123 (-a)
# ใช้ plughw: ไม่ใช่ hw: เพราะ plug ให้ ALSA แปลง sample rate/ช่องสัญญาณให้อัตโนมัติ
# DAC แบบ I2S (MAX98357A) เป็นโมโนและรับบาง sample rate เท่านั้น ถ้าใช้ hw: ตรงๆ
# ไฟล์ที่ rate ไม่ตรงจะเปิดไม่ผ่าน
#
# card 2 คือเลขที่ MAX98357A ได้บนเครื่องที่ใช้จริง (vc4hdmi0/1 กิน card 0/1 ไปก่อน)
# ถ้าย้ายไปเครื่องอื่นหรือเสียบ USB audio เพิ่ม เลขอาจเปลี่ยน เช็คด้วย aplay -l
# แล้วสั่งทับด้วย --audio-device ได้
DEFAULT_AUDIO_DEVICE = "plughw:2,0"
AUDIO_DEVICE = DEFAULT_AUDIO_DEVICE

# ความดังเสียงพูดเป็นเปอร์เซ็นต์ (100 = ระดับเดิมของไฟล์) ตั้งด้วย --volume
# จำเป็นเพราะ MAX98357A ไม่มีตัวคุมระดับเสียงในตัว amixer จึงไม่มี control ให้เร่ง
# เกิน 100 = ขยายสัญญาณด้วยซอฟต์แวร์ ดังขึ้นแลกกับความเสี่ยงที่เสียงจะแตกเมื่อ clip
#
# ทำไม 100 ถึงยังดังพอ: ไฟล์ใน audio/loud/ อัดจาก Botnoi ที่ตั้งระดับเสียง 300%
# มาตั้งแต่ต้นทางแล้ว (วัดได้ peak=1.000 rms=0.159) ค่า 100 ที่นี่จึงไม่ใช่ 'เสียงเบา'
# แต่แปลว่า 'ไม่ขยายซ้ำอีกชั้น' — ซึ่งเป็นค่าเดียวที่การันตีว่าไม่มี clipping เลย
# เพราะ peak ของไฟล์ชนเพดานดิจิทัลอยู่แล้ว คูณอะไรเพิ่มก็ตัดยอดคลื่นทันที
#
# ประวัติ: เคยตั้ง 300 (2026-08-25) ตามที่ผู้ใช้ขอให้ดังที่สุดเท่าที่ได้ ยอมให้เสียงแตก
# ต่อมาผู้ใช้ขอให้เบาลง (2026-08-27) จึงกลับมาที่ 100 ซึ่งเป็นจุดที่เสียงสะอาด
# ปรับสดได้เสมอด้วย --volume โดยไม่ต้องแก้โค้ด เช่น --volume 200 ถ้ารู้สึกเบาไป
# ** เปลี่ยนไฟล์เสียงชุดใหม่เมื่อไหร่ ต้องวัด peak/rms ใหม่แล้วทบทวนค่านี้ **
DEFAULT_VOLUME_PCT = 100
VOLUME_PCT = DEFAULT_VOLUME_PCT

# ชั้น 1 (Botnoi สด) ใช้ได้ไหม — ถ้าเซิร์ฟเวอร์ตอบ 503 แปลว่าไม่ได้ตั้ง BOTNOI_TOKEN
# ปิดชั้นนี้ทิ้งทั้งรอบเลย ไม่ต้องเสียเวลายิงซ้ำแล้วพ่น error ทุกครั้งที่เตือน
BOTNOI_ENABLED = True

# ตารางนี้ต้องตรงกับ VOICE_CLIPS ใน js/tts.js ทุกตัวอักษร (สร้างมาจากไฟล์นั้นโดยตรง)
# match ข้อความแบบตรงตัว ประโยคที่ระยะไม่ใช่ 500 เมตรจะไม่มีไฟล์ตรงแล้วตกไปชั้นถัดไปเอง
# — จงใจไม่บิดระยะให้เป็น 500 เพื่อไม่ให้บอกระยะผิดกับคนขับ พฤติกรรมเดียวกับเว็บ
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
    """เล่น mp3 จาก bytes ผ่าน stdin — คืน True ถ้าเล่นจบปกติ

    label คือชื่อชั้นที่จะ log ต่อเมื่อเล่นสำเร็จจริง ไม่ log ตอนแค่เริ่มลอง
    ไม่งั้นบรรทัด log จะบอกว่าใช้ชั้นนั้นแล้วทั้งที่ยังเล่นไม่ออก
    """
    exe = _player_cmd()
    if exe is None or not data:
        return False
    dev = ["-a", AUDIO_DEVICE] if AUDIO_DEVICE and exe in ("mpg123", "mpg321") else []
    # mpg123 คุมความดังด้วย scale factor ฐาน 32768 = 100% (mpg321 ไม่รองรับแบบเดียวกัน)
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
            # เซิร์ฟเวอร์ไม่ได้ตั้ง BOTNOI_TOKEN — ยิงกี่ครั้งก็ได้ 503 เหมือนเดิม
            # ปิดชั้นนี้ทิ้งเลย ประหยัดเวลาและไม่ทำให้ log ดูเหมือนมี error ทุกครั้ง
            BOTNOI_ENABLED = False
            print("   [เสียง] ข้ามชั้น 1 ทั้งรอบ: เซิร์ฟเวอร์ยังไม่ได้ตั้ง BOTNOI_TOKEN")
        else:
            print(f"   [เสียง] Botnoi สดไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    except Exception as e:  # noqa: BLE001 — ทุก error ให้ตกไปชั้นถัดไป
        print(f"   [เสียง] Botnoi สดไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    return _play_mp3(data, "ชั้น 1 Botnoi สด")


def _speak_google(text):
    """ชั้น 2 — Google translate_tts (ต้องมีเน็ต)"""
    if len(text) > 190:  # translate_tts รับได้จำกัดต่อครั้ง
        return False
    url = "https://translate.google.com/translate_tts?" + urllib.parse.urlencode(
        {"ie": "UTF-8", "q": text, "tl": "th", "client": "tw-ob"}
    )
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = resp.read()
    except Exception as e:  # noqa: BLE001
        print(f"   [เสียง] Google ไม่สำเร็จ: {e}", file=sys.stderr)
        return False
    return _play_mp3(data, "ชั้น 2 Google")


def _speak_espeak(text):
    """ชั้น 3 — espeak-ng ในเครื่อง ใช้ตอนไม่มีเน็ต (เสียงแข็ง ใช้เป็นตัวสำรองเท่านั้น)"""
    if not shutil.which("espeak-ng"):
        return False
    try:
        # -s 150 คำ/นาที ช้ากว่าค่าเริ่มต้นเล็กน้อย ให้คนขับฟังทัน
        # espeak-ng: -a คือ amplitude 0-200 (ค่าเริ่มต้น 100) เพดานตามที่โปรแกรมรับได้
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
    for layer in (
        lambda: _speak_clip(text),
        lambda: _speak_botnoi(text, api_base),
        lambda: _speak_google(text),
        lambda: _speak_espeak(text),
    ):
        if layer():
            return True
    print("   [เสียง] ไม่มีชั้นไหนพูดได้ — เหลือแค่ buzzer", file=sys.stderr)
    return False


def announce(text, speak_enabled, api_base):
    """บอกสถานะของตัวระบบเอง (ไม่ใช่การเตือนจุดเสี่ยง) — ใช้แทนจอตอนออกภาคสนาม

    ต่างจาก speak() ตรงที่ถ้าปิดเสียงพูดไว้ (--no-speak) จะไม่ออกเสียงเลย ไม่ใช้ buzzer
    แทน เพราะ buzzer มีความหมายเดียวคือ "เข้าใกล้จุดเสี่ยง" ถ้าเอามาใช้บอกสถานะด้วย
    คนขับจะแยกไม่ออกว่าเสียงที่ได้ยินหมายถึงอะไร
    """
    print(f"[สถานะ] {text}")
    if speak_enabled:
        speak(text, api_base)


# ---------- เรียก API ----------

def fetch_nearby(api_base, lat, lng):
    query = urllib.parse.urlencode(
        {"lat": f"{lat:.6f}", "lng": f"{lng:.6f}", "radius": EXIT_RADIUS_M}
    )
    url = f"{api_base}/api/risk-points/nearby?{query}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read())["points"]


def report_location(api_base, lat, lng, source):
    """ส่งพิกัดปัจจุบันขึ้น POST /api/device/location ให้หน้าเว็บวาดหมุดรถเรียลไทม์

    เป็นงานเสริม ไม่ใช่งานหลัก — ถ้าส่งไม่สำเร็จต้องไม่กระทบการเตือน จึงกลืน error ทุกชนิด
    และเตือนแค่ครั้งแรกครั้งเดียว ไม่งั้นถ้าเซิร์ฟเวอร์ดับจะมี log ท่วมทุก 3 วินาที
    (ปัญหาเดียวกับที่เคยเจอตอน Botnoi ตอบ 503 รัว ๆ)

    ส่ง source ไปด้วยเพื่อให้เว็บแยกออกว่าหมุดที่เห็นมาจาก GPS จริง (serial/gpsd)
    หรือมาจากโหมดจำลอง (route/fixed) — ไม่งั้นตอนสาธิตจะแยกไม่ออกว่ารถวิ่งจริงหรือไม่
    """
    global _report_failed_once
    if not REPORT_LOCATION:
        return
    body = {"lat": round(lat, 6), "lng": round(lng, 6), "source": source}
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
source_telemetry = None  # ตั้งใน run() = ฟังก์ชันคืน {"speed_kmh":..., "satellites":...}


def _lan_ip():
    """หา IP ของ Pi ในวงแลน เพื่อบอก URL ที่เปิดจากมือถือได้จริง

    localhost ใช้ได้แค่บนตัว Pi เอง เปิดจากมือถือไม่ได้ — ต้องบอก IP จริง
    วิธีหา: เปิด UDP socket ไปยัง IP ภายนอก แล้วอ่านว่าระบบเลือกใช้ขาไหนออก
    UDP ไม่ต้อง handshake จึงไม่มีแพ็กเก็ตถูกส่งออกจริงและไม่ต้องมีเน็ต
    (ใช้ 8.8.8.8 เป็นแค่ปลายทางสมมติ ไม่ได้ติดต่อ Google จริง)
    """
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sk:
            sk.connect(("8.8.8.8", 80))
            return sk.getsockname()[0]
    except OSError:
        return None


def _web_page(api_base):
    """เดาว่าควรเปิดหน้าไหน จากชุดข้อมูลที่ API กำลังแจกอยู่

    เปิดผิดหน้าแล้วจะงงมาก เพราะแผนที่ขึ้นปกติแต่ไม่มีจุดเสี่ยงตรงกับที่อุปกรณ์เตือน
    (index.html โหลด geojson กรุงเทพฯ ของตัวเอง ไม่ได้ถามชุดข้อมูลจาก API)
    """
    try:
        with urllib.request.urlopen(f"{api_base}/api/health", timeout=HTTP_TIMEOUT_S) as r:
            dataset = json.loads(r.read()).get("dataset", "")
    except (OSError, ValueError):
        return "index.html"
    return "test-nstda.html" if "nstda" in dataset else "index.html"


# ---------- ลูปหลัก ----------

def run(api_base, position_source, speak_enabled=True):
    beeped = set()  # point id ที่ร้อง beep ไปแล้ว (รีเซ็ตเมื่อออกนอกรัศมี)

    # ตัวรับ GPS จริงรู้ความเร็ว/จำนวนดาว โหมดจำลองไม่รู้ — ผูกไว้ให้ report_location หยิบไปใช้
    global source_telemetry
    if hasattr(position_source, "satellites"):
        source_telemetry = lambda: {
            "speed_kmh": (round(position_source.speed_kmh, 1)
                          if position_source.speed_kmh is not None else None),
            "satellites": position_source.satellites,
        }
    voice = "เปิด" if speak_enabled else "ปิด"
    player = _player_cmd() or "ไม่พบโปรแกรมเล่น mp3"
    buzzer = "พร้อม" if BUZZER_READY else "ข้าม"
    print(
        f"เริ่มเฝ้าระวังจุดเสี่ยง (API: {api_base}, เตือนที่ {ALERT_RADIUS_M} ม. "
        f"เฉพาะข้างหน้า ±{HEADING_WINDOW_DEG:.0f}°, "
        f"เสียงพูด: {voice} [{player} -> {AUDIO_DEVICE or 'default'} {VOLUME_PCT}%], "
        f"buzzer: {buzzer})"
    )
    if REPORT_LOCATION:
        page = _web_page(api_base)
        ip = _lan_ip()
        print("ส่งตำแหน่งขึ้นเว็บ: เปิด — เปิดลิงก์นี้เพื่อดูหมุด 🚌 บนแผนที่")
        print(f"   บน Pi เครื่องนี้ : {api_base}/{page}")
        if ip:
            # ต้องเป็น IP จริงไม่ใช่ localhost ไม่งั้นเปิดจากมือถือไม่ได้
            print(f"   จากมือถือ       : http://{ip}:8000/{page}  (ต่อ WiFi วงเดียวกัน)")

    heading = HeadingTracker()

    # บอกสถานะด้วยเสียงตอนออกภาคสนาม เพราะไม่มีจอให้ดู
    #
    # เสียเที่ยวทดสอบไปแล้ว 1 รอบเพราะเรื่องนี้ (2026-08-27 18:10-18:25): service
    # ถูกสั่ง stop ไว้ตอนทดสอบ --checkgps แล้วลืมสั่ง start กลับ ออกไปข้างนอกทั้งที่
    # ไม่มีอะไรทำงานเลย กว่าจะรู้ก็ตอนกลับมาเสียบจอแล้วไล่ journalctl ย้อนหลัง
    #
    # แยกสองประโยคเพื่อให้วินิจฉัยได้จากเสียงล้วน ๆ:
    #   เงียบสนิทตั้งแต่แรก      = เครื่องไม่ติด / service ไม่ได้รัน
    #   พูดประโยคแรกแล้วเงียบยาว = ระบบทำงาน แต่ GPS ยังจับดาวไม่ได้
    #   พูดครบสองประโยค          = พร้อมใช้งานจริง
    announce("ระบบพร้อมทำงาน กำลังค้นหาสัญญาณดาวเทียม", speak_enabled, api_base)
    got_first_fix = False

    while True:
        started = time.monotonic()
        pos = position_source.read()
        if pos is None:
            if getattr(position_source, "finished", False):
                print("จบเส้นทางจำลองแล้ว — หยุดทำงาน")
                break
            # บอกจำนวนดาวที่เห็นด้วย ไม่ใช่แค่ "ยังไม่ได้ตำแหน่ง" เฉย ๆ เพราะระหว่างรอ
            # ต้องแยกให้ออกว่า "กำลังคืบหน้า" (ดาวเพิ่มขึ้นเรื่อย ๆ รออีกหน่อยได้พิกัด)
            # กับ "ไม่คืบเลย" (0 ดวงค้าง = ที่วางตัวรับมองไม่เห็นฟ้า ต้องย้ายที่)
            # ดูสดด้วย journalctl -u mtec-alert-client -f ตอนออกภาคสนาม
            #
            # None = ยังไม่เคย parse ประโยค GGA สำเร็จสักครั้ง ต่างจาก 0 ที่ตัวรับบอกเองว่า
            # เห็น 0 ดวง — ถ้าค้างที่ ? นานแปลว่าอ่าน NMEA ไม่ออก (baud ผิด/มีตัวแย่งพอร์ต)
            # ไม่ใช่แค่จับดาวไม่ได้ ดูหมายเหตุที่ GPS_BAUD
            sats = getattr(position_source, "satellites", None)
            print(f"[gps] ยังไม่ได้ตำแหน่ง · เห็นดาว {'?' if sats is None else sats} ดวง"
                  " (รอสัญญาณดาวเทียม)...")
        else:
            lat, lng = pos
            if not got_first_fix:
                got_first_fix = True
                announce("รับสัญญาณดาวเทียมแล้ว เริ่มแจ้งเตือนจุดเสี่ยง",
                         speak_enabled, api_base)
            heading_deg = heading.update(lat, lng)
            report_location(api_base, lat, lng, getattr(position_source, "name", None))
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
                    # ข้ามจุดที่ขับผ่านไปแล้ว/อยู่ด้านหลัง (ยังไม่รู้ทิศ = เตือนไว้ก่อน)
                    if not is_ahead(heading_deg, lat, lng, p["lat"], p["lng"],
                                    HEADING_WINDOW_DEG):
                        continue
                    if p["id"] not in beeped:
                        beeped.add(p["id"])
                        beep()  # เสียงนำ แล้วค่อยพูดประโยคเตือน
                        if speak_enabled:
                            speak(p["alert_message"], api_base)

                nearest = nearby[0] if nearby else None
                status = (
                    f"ใกล้สุด: {nearest.get('road_label') or nearest['road']} "
                    f"{nearest['distance_m']:.0f} ม. ({nearest['level']})"
                    if nearest
                    else f"ไม่มีจุดเสี่ยงในรัศมี {EXIT_RADIUS_M} ม."
                )
                hdg = "ทิศ ?" if heading_deg is None else f"ทิศ {heading_deg:.0f}°"
                print(f"[{time.strftime('%H:%M:%S')}] ({lat:.5f}, {lng:.5f}) {hdg} {status}")

        time.sleep(max(0, POLL_INTERVAL_S - (time.monotonic() - started)))


SAMPLE_TEXT = "ข้างหน้าอีกประมาณ 500 เมตร มีจุดอันตราย กรุณาลดความเร็ว และใช้ความระมัดระวังเป็นพิเศษ"


def check_voice(api_base):
    """ตรวจว่าทำไมเสียงพูดไม่ออก — ไล่ทีละชั้นแล้วบอกว่าติดที่อะไร

    ใช้ตอนอุปกรณ์ร้องแต่ buzzer แล้วไม่พูด:
        python3 device/pi_alert_client.py --checkvoice
    """
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
        print("   >>> ไม่มีตัวเล่น mp3 เลย นี่คือสาเหตุที่ได้ยินแต่ buzzer")
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
    """service ตัวจริงกำลังจับพอร์ต GPS อยู่ไหม

    ตรวจก่อน --checkgps เสมอ เพราะเป็นหลุมพรางที่เสียเวลาไล่หาสาเหตุผิดทางไปมากที่สุด
    (เจอจริงสองรอบ 2026-08-27) — เปิดพอร์ตซ้ำได้โดยไม่ error แต่ NMEA ที่วิ่งเข้ามา
    จะถูกสองโปรเซสแย่งกันอ่านคนละครึ่งบรรทัด checksum เลยไม่ผ่านทุกบรรทัด
    ผลลัพธ์คือขึ้นว่า "ไม่เห็นดาวเลย" เหมือนตอน baud rate ผิดเป๊ะ ๆ ทั้งที่ GPS ปกติดี

    ตรวจด้วย systemctl แทนการดูว่าเปิดพอร์ตได้ไหม เพราะ Linux ยอมให้เปิด tty ซ้ำได้
    ไม่มี error ให้จับ · ไม่มี systemd (เช่นรันบนเครื่องอื่น) = ถือว่าไม่ชน
    """
    try:
        r = subprocess.run(["systemctl", "is-active", "mtec-alert-client"],
                           capture_output=True, text=True, timeout=5)
        return r.stdout.strip() == "active"
    except (FileNotFoundError, subprocess.SubprocessError):
        return False


def check_gps(port=None):
    """ดูว่าตัวรับ GPS ส่งอะไรมาบ้าง จับดาวได้กี่ดวง — ใช้ตอน --serial แล้วไม่ได้พิกัด

        python3 device/pi_alert_client.py --checkgps

    ต่างจาก --serial ตรงที่โหมดนี้ไม่ยิง API เลย แสดงแต่สถานะดิบของตัวรับ
    ทำให้แยกได้ว่าปัญหาอยู่ที่ GPS เอง หรืออยู่ที่เซิร์ฟเวอร์/เครือข่าย
    """
    print("=" * 62)
    print("ตรวจตัวรับ GPS (Beltian BE-609U)")
    print("=" * 62)

    if _alert_client_service_running():
        print("❌ mtec-alert-client.service ทำงานอยู่ — หยุดก่อนแล้วค่อยตรวจ")
        print()
        print("   sudo systemctl stop mtec-alert-client")
        print("   python3 device/pi_alert_client.py --checkgps")
        print("   sudo systemctl start mtec-alert-client      # ค่อยเปิดกลับหลังตรวจเสร็จ")
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

    reader = NmeaSerialReader(port)
    print(f"\nกำลังฟัง NMEA {GPS_CHECK_SECONDS} วินาที...")
    print("(ตัวรับที่เพิ่งเปิดเครื่องต้องใช้เวลาจับดาวครั้งแรก 30 วิ - 2 นาที และต้องอยู่กลางแจ้ง")
    print(" หรือริมหน้าต่าง — ในอาคารลึก ๆ จับดาวไม่ได้เลย)")
    for i in range(GPS_CHECK_SECONDS):
        time.sleep(1)
        fix = reader.read()
        sats = reader.satellites if reader.satellites is not None else "?"
        if fix:
            print(f"  [{i + 1:2d}วิ] ✓ พิกัด {fix[0]:.6f}, {fix[1]:.6f} · ดาว {sats} ดวง")
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
                             "180 = ปิดการกรอง เตือนทุกทิศเหมือนเดิม")
    parser.add_argument("--no-speak", action="store_true",
                        help="ปิดเสียงพูด ใช้แค่ buzzer อย่างเดียว")
    parser.add_argument("--no-report", action="store_true",
                        help="ไม่ต้องส่งพิกัดขึ้นเว็บ (หน้าแผนที่จะไม่เห็นหมุดรถ)")
    parser.add_argument("--once", action="store_true",
                        help="ใช้กับ --route เท่านั้น: วิ่งจบเส้นทางครั้งเดียวแล้วหยุด แทนที่จะวนซ้ำ")
    args = parser.parse_args()

    global AUDIO_DEVICE, VOLUME_PCT, ALERT_RADIUS_M, EXIT_RADIUS_M, REPORT_LOCATION
    global HEADING_WINDOW_DEG
    AUDIO_DEVICE = args.audio_device
    VOLUME_PCT = max(10, min(1000, args.volume))
    ALERT_RADIUS_M = args.alert_radius
    # exit ต้องไม่แคบกว่า alert ไม่งั้น hysteresis จะกลายเป็นเตือนรัวทุกรอบโพล
    EXIT_RADIUS_M = max(args.exit_radius, ALERT_RADIUS_M)
    REPORT_LOCATION = not args.no_report
    HEADING_WINDOW_DEG = max(0.0, min(180.0, args.heading_window))

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

    setup_buzzer()
    try:
        run(args.api.rstrip("/"), position_source, speak_enabled=not args.no_speak)
    except KeyboardInterrupt:
        print("\nหยุดการทำงาน")
    finally:
        if BUZZER_READY:
            GPIO.cleanup()


if __name__ == "__main__":
    main()
