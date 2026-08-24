#!/usr/bin/env python3
"""
measure_audio_headroom.py — วัดว่าไฟล์เสียงแจ้งเตือนเร่งได้อีกกี่เท่าก่อนเสียงแตก

ทำไมต้องมี: MAX98357A ไม่มีตัวคุมระดับเสียงในตัว ต้องเร่งด้วยซอฟต์แวร์ผ่าน --volume
ของ pi_alert_client.py ซึ่งคือการคูณสัญญาณตรง ๆ เกินเพดาน 16 บิตเมื่อไหร่ก็ตัดยอด
กลายเป็นเสียงแตก คำถามคือเร่งได้ถึงกี่เปอร์เซ็นต์ — ตอบได้จากค่ายอดสูงสุด (peak)
ของไฟล์จริงเท่านั้น เดาไม่ได้

    max_gain = 32767 / peak

วิธีวัด: ให้ mpg123 ถอดรหัสเป็น WAV แล้วอ่านด้วยโมดูล wave ของ Python
(ไม่ต้องพึ่ง numpy/ffmpeg — บน Pi มี mpg123 อยู่แล้ว)

    python3 scripts/measure_audio_headroom.py

หมายเหตุ: อย่าเชื่อเลข clip จาก `mpg123 -t -f ...` — โหมด test ข้ามขั้นตอนแปลงขาออก
จึงรายงาน 0 clip ทุกระดับแม้ตั้ง 400% ซึ่งทำให้เข้าใจผิดว่าเร่งเท่าไหร่ก็ปลอดภัย
"""

import array
import shutil
import subprocess
import sys
import tempfile
import wave
from pathlib import Path

CLIP_DIR = Path(__file__).resolve().parent.parent / "audio"
FULL_SCALE = 32767  # ยอดสูงสุดของ PCM 16 บิตแบบมีเครื่องหมาย

sys.stdout.reconfigure(encoding="utf-8")


def decode_peak(mp3_path, tmpdir):
    """ถอด mp3 เป็น WAV แล้วคืน (peak, rms) เป็นสัดส่วน 0-1 ของ full scale"""
    wav_path = Path(tmpdir) / (mp3_path.stem + ".wav")
    proc = subprocess.run(
        ["mpg123", "-q", "-w", str(wav_path), str(mp3_path)],
        capture_output=True,
    )
    if proc.returncode != 0 or not wav_path.exists():
        return None, None

    with wave.open(str(wav_path), "rb") as w:
        if w.getsampwidth() != 2:
            return None, None  # รองรับเฉพาะ 16 บิต ซึ่งเป็นค่าที่ mpg123 -w ให้มาเสมอ
        frames = w.readframes(w.getnframes())

    samples = array.array("h")
    samples.frombytes(frames)
    if not samples:
        return None, None

    peak = max(max(samples), -min(samples))
    rms = (sum(s * s for s in samples) / len(samples)) ** 0.5
    return peak / FULL_SCALE, rms / FULL_SCALE


def main():
    if not shutil.which("mpg123"):
        sys.exit("ต้องมี mpg123 ก่อน — sudo apt install -y mpg123")

    clips = sorted(CLIP_DIR.glob("alert_*.mp3"))
    if not clips:
        sys.exit(f"ไม่พบไฟล์ alert_*.mp3 ใน {CLIP_DIR}")

    print(f"วัดจาก {len(clips)} ไฟล์ใน {CLIP_DIR}")
    print()
    print(f"{'ไฟล์':<16}{'peak':>8}{'rms':>8}{'เร่งได้สูงสุด':>16}")
    print("-" * 48)

    limits = []
    with tempfile.TemporaryDirectory() as tmpdir:
        for mp3 in clips:
            peak, rms = decode_peak(mp3, tmpdir)
            if peak is None:
                print(f"{mp3.name:<16}{'ถอดรหัสไม่ได้':>32}")
                continue
            max_pct = int(100 / peak) if peak > 0 else 0
            limits.append((max_pct, mp3.name))
            print(f"{mp3.name:<16}{peak:>8.3f}{rms:>8.3f}{max_pct:>13}%")

    if not limits:
        sys.exit("วัดไม่ได้สักไฟล์")

    worst_pct, worst_name = min(limits)
    print("-" * 48)
    print()
    print(f"ไฟล์ที่ดังที่สุด (เป็นตัวกำหนดเพดาน): {worst_name}")
    print(f"เร่งได้สูงสุด --volume {worst_pct}  โดยไม่มีเสียงแตกสักไฟล์")
    print()
    print(f"แนะนำให้ใช้ --volume {int(worst_pct * 0.9)} "
          f"(เผื่อขอบ 10% กันยอดแหลมที่ระดับสัญญาณจริงหลัง resample)")


if __name__ == "__main__":
    main()
