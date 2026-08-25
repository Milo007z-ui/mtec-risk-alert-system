#!/usr/bin/env python3
"""
loudnorm_one.py — บีบไดนามิกไฟล์เดียวด้วย EBU R128 loudnorm แล้ววัดผลก่อน-หลังให้ดู

ใช้ต่อยอดจากไฟล์ที่ Botnoi บีบมาให้แล้วรอบหนึ่ง (เช่น audio/_test/test_300pct.mp3
ที่วัดได้ peak=1.000 rms=0.159) — Botnoi กดยอดคลื่นจนชนเพดานแล้ว โค้ดนี้ไม่ได้
"เพิ่ม volume" แบบคูณสัญญาณเท่ากันหมด (ทำแบบนั้นจะ clip ทันทีเพราะ peak เต็มแล้ว)
แต่ดันเฉพาะช่วงที่เบาให้ดังขึ้น กดช่วงที่ดังอยู่แล้วให้แบนลงนิดหน่อยแทน

ทำไมใช้ loudnorm ไม่ใช่ dynaudnorm แบบที่ลองมา 2 รอบก่อนหน้า: dynaudnorm ทำนายผล
ได้ยาก (ตั้ง r=0.25 หวังได้ 8 dB ได้จริงแค่ 2.6 dB) ส่วน loudnorm เป็นมาตรฐาน EBU R128
ที่ตั้งเป้าความดังเป็นหน่วย LUFS ตรง ๆ และมี true-peak limiter ในตัว (TP) กันสัญญาณ
ทะลุแม้ผ่าน DAC ราคาถูกที่ไม่รองรับ true-peak แม่นยำ — คาดเดาผลได้แม่นกว่า

⚠️ ยังไม่รู้ว่าจะได้ผลกี่ dB จริง ๆ จนกว่าจะวัด — 2 รอบก่อนหน้าประเมินผิดไปเยอะ
ทั้งคู่ อย่าเชื่อตัวเลขในหัวจนกว่าจะรันแล้ววัดซ้ำด้วย decode_peak

ใช้งาน (รันบน Raspberry Pi ที่มี ffmpeg + mpg123):
    python3 scripts/loudnorm_one.py audio/_test/test_300pct.mp3 audio/_test/test_300pct_squeezed.mp3
"""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from measure_audio_headroom import decode_peak  # noqa: E402

sys.stdout.reconfigure(encoding="utf-8")

# I   = เป้าหมายความดังเฉลี่ย (LUFS) -11 ค่อนข้างดังแล้วสำหรับเสียงพูด (สตรีมมิงทั่วไปใช้ -14 ถึง -16)
# TP  = เพดาน true peak (dBTP) เผื่อ -1 dB ไว้กัน inter-sample peak ทะลุตอนเล่นผ่าน DAC จริง
# LRA = ช่วงไดนามิกที่ยอมให้เหลือ (LU) แคบเพื่อให้ทั้งประโยคดังสม่ำเสมอ ไม่ใช่ดังแค่บางคำ
FILTER = "loudnorm=I=-11:TP=-1:LRA=6"


def main():
    if len(sys.argv) != 3:
        sys.exit("ใช้งาน: python3 scripts/loudnorm_one.py <ไฟล์ต้นทาง> <ไฟล์ปลายทาง>")

    src, dst = Path(sys.argv[1]), Path(sys.argv[2])
    if not src.exists():
        sys.exit(f"ไม่พบไฟล์ {src}")

    proc = subprocess.run(
        ["ffmpeg", "-y", "-loglevel", "error", "-i", str(src),
         "-af", FILTER, "-codec:a", "libmp3lame", "-q:a", "4", str(dst)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        sys.exit(f"ffmpeg ล้มเหลว: {proc.stderr.strip()}")

    with tempfile.TemporaryDirectory() as tmp:
        old_peak, old_rms = decode_peak(src, tmp)
        new_peak, new_rms = decode_peak(dst, tmp)

    print(f"{'':12}{'peak':>8}{'rms':>8}")
    print(f"{'เดิม':<12}{old_peak:>8.3f}{old_rms:>8.3f}")
    print(f"{'บีบแล้ว':<12}{new_peak:>8.3f}{new_rms:>8.3f}")
    if old_rms and new_rms:
        import math
        gain_db = 20 * math.log10(new_rms / old_rms)
        print(f"\nดังขึ้นจริง: {gain_db:+.1f} dB")
    print(f"\nฟังเทียบ:")
    print(f"   mpg123 -a plughw:2,0 {src}")
    print(f"   mpg123 -a plughw:2,0 {dst}")
    print(f"\nถ้าฟังแล้วมีเสียง 'ปั๊มๆ' หรือแบนผิดธรรมชาติ = บีบแรงไป ลด LRA ใน FILTER ลง")


if __name__ == "__main__":
    main()
