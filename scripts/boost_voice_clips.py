#!/usr/bin/env python3
"""
boost_voice_clips.py — สร้างไฟล์เสียงชุด "ดัง" สำหรับอุปกรณ์ ลงใน audio/loud/

ปัญหาที่แก้: ไฟล์ Botnoi ต้นฉบับมียอดสัญญาณชนเพดานแล้ว (peak ~1.0) แต่ความดัง
เฉลี่ยต่ำมาก (rms ~0.09) ช่วงห่างระหว่างยอดกับค่าเฉลี่ยกว้างราว 21 dB ทั้งที่
เสียงพูดที่ปรับแต่งมาดีอยู่ที่ 12-14 dB แปลว่ายอดแหลมไม่กี่จุดกินโควตาความดัง
ไปหมด เร่งด้วย --volume ไม่ได้เลยเพราะจะ clip ทันที

วิธีแก้: กดยอดแหลมลงแล้วดันทั้งประโยคขึ้น (speechnorm) + ตัดย่านต่ำที่ลำโพงจิ๋ว
เล่นไม่ออกอยู่แล้วทิ้งไป (highpass) ได้ความดังที่หูรับรู้เพิ่มราว 6-8 dB
โดยยอดยังไม่เกินเพดาน

** ทำไมต้องแยกโฟลเดอร์ ไม่ทับของเดิม **
ไฟล์ใน audio/ เว็บใช้ร่วมด้วย และ audio/README.md ระบุว่าระดับความดังของเสียงนำ
(CHIME_PATTERNS ใน js/tts.js) คำนวณมาจาก RMS ของไฟล์พูดชุดนั้น ถ้าทับของเดิม
เสียงนำบนเว็บจะกลายเป็นเบากว่าประโยคที่ตามมาแล้วไม่ดึงความสนใจอีกต่อไป
แยกไว้ที่ audio/loud/ ให้เฉพาะอุปกรณ์ใช้ เว็บจึงไม่กระทบเลย
(pi_alert_client.py จะเลือกโฟลเดอร์นี้เองอัตโนมัติถ้ามี)

ใช้งาน (รันบน Raspberry Pi ที่มี ffmpeg):
    python3 scripts/boost_voice_clips.py

ล้างทิ้งกลับไปใช้ชุดเดิม:
    rm -rf audio/loud
"""

import math
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_audio_headroom import decode_peak  # noqa: E402

AUDIO_DIR = Path(__file__).resolve().parent.parent / "audio"
OUT_DIR = AUDIO_DIR / "loud"

# highpass 250 Hz  ตัดย่านที่ลำโพง 35x25 มม. เล่นไม่ออกอยู่แล้ว คืนกำลังแอมป์ให้ย่านเสียงพูด
# speechnorm      ดันความดังเสียงพูดขึ้นแบบไม่ให้เกินเพดาน (ออกแบบมาสำหรับเสียงพูดโดยเฉพาะ)
#   e=12.5        ขยายได้สูงสุด 12.5 เท่าในช่วงที่เบา
#   r=0.0001      ค่อย ๆ ไต่ขึ้น ไม่กระชากจนได้ยินเป็นเสียงหายใจ
# alimiter        กันยอดทะลุเป็นด่านสุดท้าย level=disabled กันไม่ให้มันไป normalize ซ้ำ
FILTER = "highpass=f=250,speechnorm=e=12.5:r=0.0001:l=1,alimiter=limit=0.97:level=disabled"


def main():
    if not shutil.which("ffmpeg"):
        sys.exit("ต้องมี ffmpeg ก่อน — sudo apt install -y ffmpeg")
    if not shutil.which("mpg123"):
        sys.exit("ต้องมี mpg123 ก่อน (ใช้ตรวจผลลัพธ์) — sudo apt install -y mpg123")

    clips = sorted(AUDIO_DIR.glob("alert_*.mp3"))
    if not clips:
        sys.exit(f"ไม่พบไฟล์ alert_*.mp3 ใน {AUDIO_DIR}")

    OUT_DIR.mkdir(exist_ok=True)
    print(f"สร้างไฟล์ชุดดังจาก {len(clips)} ไฟล์ -> {OUT_DIR}")
    print()
    print(f"{'ไฟล์':<16}{'peak เดิม':>11}{'rms เดิม':>11}{'peak ใหม่':>11}{'rms ใหม่':>11}{'ดังขึ้น':>10}")
    print("-" * 70)

    gains = []
    with tempfile.TemporaryDirectory() as tmp:
        for src in clips:
            dst = OUT_DIR / src.name
            proc = subprocess.run(
                ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
                 "-af", FILTER, "-codec:a", "libmp3lame", "-q:a", "4", str(dst)],
                capture_output=True, text=True,
            )
            if proc.returncode != 0:
                print(f"{src.name:<16}  ffmpeg ล้มเหลว: {proc.stderr.strip()[:60]}")
                continue

            old_peak, old_rms = decode_peak(src, tmp)
            new_peak, new_rms = decode_peak(dst, tmp)
            if None in (old_peak, new_peak) or not old_rms:
                print(f"{src.name:<16}  วัดผลไม่ได้")
                continue

            gain_db = 20 * math.log10(new_rms / old_rms)
            gains.append(gain_db)
            flag = "  <-- ยอดเกิน!" if new_peak > 0.99 else ""
            print(f"{src.name:<16}{old_peak:>11.3f}{old_rms:>11.3f}"
                  f"{new_peak:>11.3f}{new_rms:>11.3f}{gain_db:>9.1f} dB{flag}")

    print("-" * 70)
    print()
    if gains:
        print(f"ดังขึ้นเฉลี่ย {sum(gains) / len(gains):.1f} dB "
              f"(น้อยสุด {min(gains):.1f} · มากสุด {max(gains):.1f})")
    print()
    print("ทดสอบเทียบกันได้เลย:")
    print("   mpg123 -a plughw:2,0 audio/alert_05.mp3        # ของเดิม")
    print("   mpg123 -a plughw:2,0 audio/loud/alert_05.mp3   # ชุดใหม่")
    print()
    print("pi_alert_client.py จะหยิบชุดใน audio/loud/ ไปใช้เองอัตโนมัติ")
    print("ไม่พอใจผลลัพธ์ก็ลบทิ้งได้:  rm -rf audio/loud")


if __name__ == "__main__":
    main()
