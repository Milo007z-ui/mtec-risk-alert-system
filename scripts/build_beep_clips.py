# -*- coding: utf-8 -*-
"""สร้างไฟล์เสียง beep สำหรับอุปกรณ์ Pi — รันซ้ำได้ ผลลัพธ์เหมือนเดิมทุกครั้ง"""
import math
import pathlib
import sys
import wave

import numpy as np

# คอนโซล Windows ตั้งต้นเป็น cp1252 พิมพ์ภาษาไทยแล้วพัง — บังคับเป็น UTF-8
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")

SAMPLE_RATE = 22050          # พอสำหรับโทน 2.4 kHz + ฮาร์มอนิกที่ 3 (7.2 kHz < 11 kHz)
OUT_DIR = pathlib.Path(__file__).resolve().parent.parent / "audio" / "beep"

# โทนหลัก — เลือก 2400 Hz ด้วยเหตุผลสองข้อ:
TONE_HZ = 2400.0

# ยืมมาจาก CHIME_PATTERNS ใน js/tts.js — เสียงที่มีฮาร์มอนิกลอยพ้นเสียงรบกวนในรถ
HARMONICS = [(1, 1.0), (2, 0.30), (3, 0.12)]

BEEP_S = 0.12                # ความยาวเสียงหนึ่งครั้ง
ATTACK_S = 0.020             # ไล่ความดังขึ้น — js/tts.js ใช้ 0.04 กับ chime เพื่อกัน startle
                             # reflex  ที่นี่สั้นกว่าเพราะ beep ต้องคม แต่ยังไม่ใช่ขอบตั้งฉาก
RELEASE_S = 0.040            # ไล่ลง ยาวกว่าขาขึ้นเพื่อไม่ให้เกิดเสียงคลิกตอนตัด
PEAK = 0.70                  # เผื่อ headroom ไม่ให้ clip ตอน mpg123/aplay ปรับความดังต่อ

LOOP_S = 2.0                 # ความยาวไฟล์ที่วนซ้ำ — เปลี่ยนจังหวะได้ทุก 2 วินาที
                             # spawn โปรเซสแค่ 0.5 ครั้ง/วินาที Pi รับไหวสบาย
# จังหวะตามระยะ (แบบเซ็นเซอร์ถอยรถ: ใกล้ขึ้น = ถี่ขึ้น)
PATTERNS = {
    "far":  1.0,   # 1 ครั้ง/วินาที  — ระยะ 100-66% ของ DSD
    "mid":  2.0,   # 2 ครั้ง/วินาที  — 66-33%
    "near": 4.0,   # 4 ครั้ง/วินาที  — ต่ำกว่า 33% (เร็วสุดที่ยอมให้ไต่ถึง)
}

# เสียงนำหน้าประโยคพูด แทน chime เดิม — beep สองครั้งแล้วเงียบ ไม่วนซ้ำ
LEAD_TIMES = [0.0, 0.22]
LEAD_TAIL_S = 0.28           # เงียบท้ายไฟล์ ให้แยกเสียงนำกับประโยคออกจากกัน


def one_beep():
    """คลื่นเสียง beep หนึ่งครั้ง พร้อม envelope กันคลิกหัวท้าย"""
    n = int(SAMPLE_RATE * BEEP_S)
    t = np.arange(n) / SAMPLE_RATE
    wave_ = np.zeros(n)
    for mult, amp in HARMONICS:
        wave_ += amp * np.sin(2 * math.pi * TONE_HZ * mult * t)
    wave_ /= sum(a for _, a in HARMONICS)

    env = np.ones(n)
    a = int(SAMPLE_RATE * ATTACK_S)
    r = int(SAMPLE_RATE * RELEASE_S)
    # ครึ่งโคไซน์ทั้งขาขึ้นและขาลง — นุ่มกว่าเส้นตรง ไม่มีหักมุมให้ได้ยินเป็นคลิก
    env[:a] = 0.5 - 0.5 * np.cos(np.linspace(0, math.pi, a))
    env[n - r:] = 0.5 + 0.5 * np.cos(np.linspace(0, math.pi, r))
    return wave_ * env


def render(times, total_s):
    """วาง beep ตามเวลาที่กำหนดลงบนความเงียบยาว total_s วินาที"""
    buf = np.zeros(int(SAMPLE_RATE * total_s))
    b = one_beep()
    for at in times:
        i = int(SAMPLE_RATE * at)
        end = min(i + len(b), len(buf))
        buf[i:end] += b[:end - i]
    peak = np.max(np.abs(buf))
    if peak > 0:
        buf = buf / peak * PEAK
    return buf


def write_wav(path, samples):
    pcm = np.clip(samples, -1.0, 1.0)
    data = (pcm * 32767).astype("<i2").tobytes()
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SAMPLE_RATE)
        w.writeframes(data)
    return len(data)


def main():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print(f"โทน {TONE_HZ:.0f} Hz · beep ละ {BEEP_S * 1000:.0f} มิลลิวินาที · "
          f"{SAMPLE_RATE} Hz mono 16-bit")
    print(f"ปลายทาง: {OUT_DIR}")
    print()

    for name, rate in PATTERNS.items():
        step = 1.0 / rate
        times = [i * step for i in range(int(LOOP_S * rate))]
        # ต้องหารลงตัวพอดี ไม่งั้นวนซ้ำแล้วจังหวะจะสะดุดตรงรอยต่อ
        assert abs(LOOP_S * rate - round(LOOP_S * rate)) < 1e-9, \
            f"จังหวะ {rate}/วินาที หารกับความยาวลูป {LOOP_S} วิ ไม่ลงตัว"
        p = OUT_DIR / f"beep_{name}.wav"
        size = write_wav(p, render(times, LOOP_S))
        print(f"  beep_{name}.wav   {rate:.0f} ครั้ง/วินาที · {len(times)} ครั้งต่อลูป · "
              f"{LOOP_S:.1f} วิ · {size / 1024:.0f} KB")

    p = OUT_DIR / "beep_lead.wav"
    total = LEAD_TIMES[-1] + BEEP_S + LEAD_TAIL_S
    size = write_wav(p, render(LEAD_TIMES, total))
    print(f"  beep_lead.wav     นำหน้าเสียงพูด · {len(LEAD_TIMES)} ครั้ง · "
          f"{total:.2f} วิ · {size / 1024:.0f} KB")


if __name__ == "__main__":
    main()
