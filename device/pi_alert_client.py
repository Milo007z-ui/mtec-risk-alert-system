#!/usr/bin/env python3
"""
pi_alert_client.py — ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi (สำหรับติดบนรถเมล์)

หลักการทำงาน (วนลูปทุก POLL_INTERVAL_S วินาที):
  1. อ่านพิกัด GPS ปัจจุบันของรถ (จาก gpsd หรือโหมดจำลอง)
  2. ยิง GET /api/risk-points/nearby?lat=..&lng=..&radius=600 ไปที่เซิร์ฟเวอร์
  3. ถ้ามีจุดเสี่ยงใกล้กว่า 500 เมตรและยังไม่เคยเตือน -> สั่ง buzzer ที่ต่อขา GPIO13 (เลขแบบ BCM)
     ร้อง 1 วิ เป็นเสียงนำ แล้วพูดประโยคเตือนภาษาไทยที่ได้จาก alert_message ของ API
     (เสียงพูดมี 4 ชั้น ดูหัวข้อ "เสียงพูดแจ้งเตือน" ด้านล่าง ปิดด้วย --no-speak ได้)

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
import pathlib
import shutil
import socket
import subprocess
import sys
import time
import urllib.error
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

# จอง GPIO ของ buzzer สำเร็จหรือยัง — ถ้าไม่สำเร็จยังเดินต่อได้ เหลือแต่เสียงพูด
BUZZER_READY = False

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

# อุปกรณ์เสียงที่จะส่งให้ mpg123 (-a) — Pi มีทั้ง HDMI และแจ็ค 3.5 มม.
# ปกติปล่อย None ให้ใช้ค่า default ของระบบ ตั้งได้ด้วย --audio-device เช่น plughw:2,0
# ใช้ plughw: ไม่ใช่ hw: เพราะ plug ให้ ALSA แปลง sample rate/ช่องสัญญาณให้อัตโนมัติ
# DAC แบบ I2S (เช่น MAX98357A) เป็นโมโนและรับบาง sample rate เท่านั้น ถ้าใช้ hw: ตรงๆ
# ไฟล์ที่ rate ไม่ตรงจะเปิดไม่ผ่าน
AUDIO_DEVICE = None

# ความดังเสียงพูดเป็นเปอร์เซ็นต์ (100 = ระดับเดิมของไฟล์) ตั้งด้วย --volume
# จำเป็นเพราะ DAC แบบ MAX98357A ไม่มีตัวคุมระดับเสียงในตัว amixer จึงไม่มีอะไรให้เร่ง
# เกิน 100 = ขยายสัญญาณด้วยซอฟต์แวร์ ดังขึ้นแลกกับความเสี่ยงที่เสียงจะแตกเมื่อ clip
VOLUME_PCT = 100

# ชั้น 1 (Botnoi สด) ใช้ได้ไหม — ถ้าเซิร์ฟเวอร์ตอบ 503 แปลว่าไม่ได้ตั้ง BOTNOI_TOKEN
# ปิดชั้นนี้ทิ้งทั้งรอบเลย ไม่ต้องเสียเวลายิงซ้ำแล้วพ่น error ทุกครั้งที่เตือน
BOTNOI_ENABLED = True

# ตารางนี้ต้องตรงกับ VOICE_CLIPS ใน js/tts.js ทุกตัวอักษร (สร้างมาจากไฟล์นั้นโดยตรง)
# match ข้อความแบบตรงตัว ประโยคที่ระยะไม่ใช่ 500 เมตรจะไม่มีไฟล์ตรงแล้วตกไปชั้นถัดไปเอง
# — จงใจไม่บิดระยะให้เป็น 500 เพื่อไม่ให้บอกระยะผิดกับคนขับ พฤติกรรมเดียวกับเว็บ
VOICE_CLIPS = {
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงต่ำ โปรดขับขี่ด้วยความระมัดระวัง":
        "alert_01.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดลดความเร็ว และใช้ความระมัดระวัง":
        "alert_02.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
        "alert_04.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดลดความเร็ว และใช้ความระมัดระวังเป็นพิเศษ":
        "alert_05.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
        "alert_06.mp3",
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดชะลอความเร็ว และระวังรถตัดผ่านทางแยก":
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


# ---------- เรียก API ----------

def fetch_nearby(api_base, lat, lng):
    query = urllib.parse.urlencode(
        {"lat": f"{lat:.6f}", "lng": f"{lng:.6f}", "radius": EXIT_RADIUS_M}
    )
    url = f"{api_base}/api/risk-points/nearby?{query}"
    with urllib.request.urlopen(url, timeout=HTTP_TIMEOUT_S) as resp:
        return json.loads(resp.read())["points"]


# ---------- ลูปหลัก ----------

def run(api_base, position_source, speak_enabled=True):
    beeped = set()  # point id ที่ร้อง beep ไปแล้ว (รีเซ็ตเมื่อออกนอกรัศมี)
    voice = "เปิด" if speak_enabled else "ปิด"
    player = _player_cmd() or "ไม่พบโปรแกรมเล่น mp3"
    buzzer = "พร้อม" if BUZZER_READY else "ข้าม"
    print(
        f"เริ่มเฝ้าระวังจุดเสี่ยง (API: {api_base}, เตือนที่ {ALERT_RADIUS_M} ม., "
        f"เสียงพูด: {voice} [{player} {VOLUME_PCT}%], buzzer: {buzzer})"
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
                print(f"[{time.strftime('%H:%M:%S')}] ({lat:.5f}, {lng:.5f}) {status}")

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


def main():
    parser = argparse.ArgumentParser(description="ไคลเอนต์แจ้งเตือนจุดเสี่ยงบน Raspberry Pi")
    parser.add_argument("--api", default="http://localhost:8000",
                        help="URL ของ EMMA Risk Point API (ค่าเริ่มต้น: http://localhost:8000)")
    parser.add_argument("--volume", type=int, default=100, metavar="PCT",
                        help="ความดังเสียงพูดเป็นเปอร์เซ็นต์ (100 = เดิม, 200 = ดังขึ้นเท่าตัว) "
                             "หาเพดานที่ปลอดภัยด้วย scripts/measure_audio_headroom.py")
    parser.add_argument("--audio-device", metavar="DEV",
                        help="ส่งอุปกรณ์เสียงให้ mpg123 (-a) เช่น plughw:2,0 — ปกติไม่ต้องใส่")
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--checkvoice", action="store_true",
                        help="ตรวจว่าทำไมเสียงพูดไม่ออก แล้วลองพูดประโยคตัวอย่างหนึ่งครั้ง")
    source.add_argument("--gpsd", action="store_true", help="อ่านพิกัดจริงจาก gpsd")
    source.add_argument("--test", nargs=2, type=float, metavar=("LAT", "LNG"),
                        help="โหมดทดสอบ: ใช้พิกัดคงที่")
    source.add_argument("--route", metavar="FILE",
                        help="โหมดจำลอง: อ่านพิกัดจากไฟล์ (.geojson เส้นทางเดียวกับเว็บ ?mock=1 "
                             "หรือ .csv บรรทัดละ lat,lng)")
    parser.add_argument("--no-speak", action="store_true",
                        help="ปิดเสียงพูด ใช้แค่ buzzer อย่างเดียว")
    parser.add_argument("--once", action="store_true",
                        help="ใช้กับ --route เท่านั้น: วิ่งจบเส้นทางครั้งเดียวแล้วหยุด แทนที่จะวนซ้ำ")
    args = parser.parse_args()

    global AUDIO_DEVICE, VOLUME_PCT
    AUDIO_DEVICE = args.audio_device
    VOLUME_PCT = max(10, min(1000, args.volume))

    if args.checkvoice:
        sys.exit(0 if check_voice(args.api.rstrip("/")) else 1)

    if args.gpsd:
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
