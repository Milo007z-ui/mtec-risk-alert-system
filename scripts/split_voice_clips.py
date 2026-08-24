"""
split_voice_clips.py — ตัดไฟล์เสียงรวมจาก Botnoi ออกเป็นประโยคละไฟล์

ใช้เมื่อ Botnoi จำกัดจำนวนไฟล์ต่อการดาวน์โหลด (เสียงพรีเมียมได้ครั้งละ 3 ไฟล์)
จึงเลือก "รวมเป็นไฟล์เดียว" แล้วมาตัดเองทีหลัง

วิธีทำงาน: หาช่วงเงียบระหว่างประโยคด้วย ffmpeg silencedetect แล้วตัดที่กึ่งกลาง
ช่วงเงียบ เหลือหางเสียงไว้เล็กน้อยทั้งสองฝั่งเพื่อไม่ให้คำแรก/คำท้ายขาด

ใช้:
  py scripts/split_voice_clips.py <ไฟล์รวม.mp3> --start 4 --count 9
  py scripts/split_voice_clips.py <ไฟล์รวม.mp3> --start 4 --count 9 --noise -35 --min-gap 0.25

ถ้าจำนวนที่ตัดได้ไม่ตรงกับ --count สคริปต์จะไม่เขียนไฟล์ใดๆ แต่จะบอกว่าเจอกี่ท่อน
ให้ปรับ --noise (ยิ่งใกล้ 0 ยิ่งไวต่อเสียงเบา) หรือ --min-gap (ช่วงเงียบขั้นต่ำ) แล้วลองใหม่
"""

import argparse
import os
import re
import subprocess
import sys

import imageio_ffmpeg

FF = imageio_ffmpeg.get_ffmpeg_exe()
OUT_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "audio")

# หางเสียงที่เก็บไว้รอบประโยค กันคำแรก/คำท้ายขาด
PAD_S = 0.12


def duration_of(path):
    r = subprocess.run([FF, "-i", path, "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"Duration: (\d+):(\d+):([\d.]+)", r.stderr)
    if not m:
        sys.exit("อ่านความยาวไฟล์ไม่ได้ — ไฟล์เสียงเสียหรือไม่ใช่ไฟล์เสียง?")
    h, mi, s = m.groups()
    return int(h) * 3600 + int(mi) * 60 + float(s)


def find_silences(path, noise_db, min_gap):
    """คืน [(เริ่ม, จบ)] ของทุกช่วงเงียบ"""
    r = subprocess.run(
        [FF, "-i", path, "-af", f"silencedetect=noise={noise_db}dB:d={min_gap}", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    starts = [float(x) for x in re.findall(r"silence_start: ([\d.]+)", r.stderr)]
    ends = [float(x) for x in re.findall(r"silence_end: ([\d.]+)", r.stderr)]
    return list(zip(starts, ends))


def segments_from(silences, total):
    """
    ช่วง 'เสียงพูด' = ส่วนที่เหลือหลังตัดช่วงเงียบออก

    ตัดชิดขอบเสียงพูดจริง ไม่ใช่กึ่งกลางช่วงเงียบ เพราะความเงียบที่ติดมาท้ายไฟล์
    จะหน่วงจังหวะปลดล็อกเสียงเตือนถัดไป (alert.js รอ onended ก่อนเตือนจุดต่อไป)
    """
    speech = []
    cur = 0.0
    for start, end in silences:
        if start > cur:
            speech.append((cur, start))
        cur = max(cur, end)
    if cur < total:
        speech.append((cur, total))

    segs = []
    for a, b in speech:
        if b - a < 0.4:  # สั้นกว่านี้ไม่ใช่ประโยค (เสียงลมหายใจ/สัญญาณรบกวน)
            continue
        segs.append((max(0.0, a - PAD_S), min(total, b + PAD_S)))
    return segs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="ไฟล์เสียงรวมจาก Botnoi")
    ap.add_argument("--start", type=int, required=True, help="เลขไฟล์เริ่มต้น เช่น 4 = alert_04.mp3")
    ap.add_argument("--count", type=int, required=True, help="จำนวนประโยคที่ควรได้")
    ap.add_argument("--noise", type=float, default=-40, help="ระดับที่ถือว่าเงียบ (dB, ค่าเริ่มต้น -40)")
    ap.add_argument("--min-gap", type=float, default=0.35, help="ช่วงเงียบขั้นต่ำที่นับเป็นรอยต่อ (วินาที)")
    ap.add_argument("--dry-run", action="store_true", help="ดูผลการตัดโดยยังไม่เขียนไฟล์")
    a = ap.parse_args()

    if not os.path.exists(a.input):
        sys.exit(f"ไม่พบไฟล์ {a.input}")

    total = duration_of(a.input)
    silences = find_silences(a.input, a.noise, a.min_gap)
    segs = segments_from(silences, total)

    print(f"ไฟล์รวม {os.path.basename(a.input)} ยาว {total:.2f} วินาที")
    print(f"เจอช่วงเงียบ {len(silences)} ช่วง -> ตัดได้ {len(segs)} ประโยค (ต้องการ {a.count})\n")
    for i, (s, e) in enumerate(segs):
        print(f"  ท่อน {i+1}: {s:6.2f} - {e:6.2f}  ({e-s:.2f} วินาที)")

    if len(segs) != a.count:
        sys.exit(
            f"\nตัดได้ {len(segs)} ท่อน ไม่ตรงกับที่ต้องการ {a.count} — ยังไม่เขียนไฟล์\n"
            f"  ตัดได้น้อยไป = ช่วงเงียบสั้นเกิน ลอง --min-gap {a.min_gap/2:.2f}\n"
            f"  ตัดได้มากไป = มีช่วงเงียบกลางประโยค ลอง --min-gap {a.min_gap*1.5:.2f} หรือ --noise {a.noise-5:.0f}"
        )

    if a.dry_run:
        print("\n--dry-run: ไม่เขียนไฟล์")
        return

    os.makedirs(OUT_DIR, exist_ok=True)
    print()
    for i, (s, e) in enumerate(segs):
        name = f"alert_{a.start + i:02d}.mp3"
        out = os.path.join(OUT_DIR, name)
        r = subprocess.run(
            [FF, "-y", "-i", a.input, "-ss", f"{s:.3f}", "-to", f"{e:.3f}",
             "-c:a", "libmp3lame", "-b:a", "64k", out],
            capture_output=True, text=True,
        )
        if r.returncode != 0:
            sys.exit(f"ตัด {name} ไม่สำเร็จ:\n{r.stderr[-500:]}")
        print(f"  เขียน audio/{name}  ({os.path.getsize(out)/1024:.1f} KB, {e-s:.2f} วินาที)")

    print(f"\nเสร็จ {len(segs)} ไฟล์ — ฟังทุกไฟล์ทวนก่อนใช้จริง")


if __name__ == "__main__":
    main()
