"""แปลง log ของ mtec-alert-client (journalctl) เป็นไฟล์เล่นย้อนบนแผนที่

ใช้:
    python scripts/build_replay_from_log.py LOG.txt 15:43:00 16:22:30 data/replay_xxx.json
        [--lag 16:16:08=52] [--sats 12]

--lag HH:MM:SS=วินาที  ตำแหน่งตั้งแต่เวลานั้นใน log ช้ากว่าความจริงกี่วินาที (วัดจากวิดีโอกล้องหน้ารถ)
                      เลื่อนตำแหน่งช่วงนั้นกลับมาให้ตรงเวลาจริง ส่วนเวลาที่ Pi พูดเตือนไม่เลื่อน
                      เพราะนาฬิกาของ Pi ตรงกับเสียงในวิดีโออยู่แล้ว
--sats N              จำนวนดาวเทียมที่ผู้ขับเห็นบนจอ (log ไม่ได้บันทึกค่านี้)

Pi พิมพ์บรรทัดตำแหน่งทุกรอบ (ราว 1 วินาที) และบรรทัด ">> ..." ทุกครั้งที่พูด
ไฟล์ที่ได้จึงเป็นตำแหน่ง/ทิศ/การเตือนที่ Pi ทำจริง ไม่ได้คำนวณใหม่
"""

import json
import re
import sys

POS_RE = re.compile(
    r"\[(\d\d:\d\d:\d\d)\] \((-?\d+\.\d+), (-?\d+\.\d+)\) ทิศ (\?|(\d+)°)"
)
SAY_RE = re.compile(r"^\S+ \d+ (\d\d:\d\d:\d\d) .*?>> (.+)$")
# เฉพาะประโยคเตือนจุดเสี่ยง — ประโยคบอกสถานะ (พร้อมทำงาน/รับสัญญาณแล้ว) ไม่ขึ้นป้าย
LEVEL_OF = [("เสี่ยงสูง", "high"), ("เสี่ยงปานกลาง", "medium"), ("เสี่ยงต่ำ", "low")]


def secs(hms):
    h, m, s = map(int, hms.split(":"))
    return h * 3600 + m * 60 + s


def main(log_path, start, end, out_path, lag=None, sats=None):
    t0, t1 = secs(start), secs(end)
    frames, alerts, last_t = [], [], None
    with open(log_path, encoding="utf-8", errors="replace") as f:
        for line in f:
            m = POS_RE.search(line)
            if m:
                t = secs(m.group(1))
                if t0 <= t <= t1 and t != last_t:  # บรรทัดเวลาซ้ำในวินาทีเดียวกันเก็บตัวแรก
                    hdg = None if m.group(4) == "?" else int(m.group(5))
                    frames.append([t - t0, float(m.group(2)), float(m.group(3)), hdg])
                    last_t = t
                continue
            m = SAY_RE.match(line.rstrip())
            if m and t0 <= secs(m.group(1)) <= t1:
                msg = m.group(2).strip()
                level = next((lv for key, lv in LEVEL_OF if key in msg), None)
                if level:
                    alerts.append({"t": secs(m.group(1)) - t0, "message": msg, "level": level})

    if lag:
        at, shift = lag.split("=")
        cut, shift = secs(at) - t0, int(shift)
        # ตำแหน่งค้างช่วง [cut-shift, cut) ทิ้งไป แล้วเลื่อนท่อนหลังกลับมาแทนที่
        frames = ([f for f in frames if f[0] < cut - shift]
                  + [[f[0] - shift] + f[1:] for f in frames if f[0] >= cut])
    out = {"date": "2026-11-08", "start": start, "end": end, "frames": frames, "alerts": alerts}
    if lag:
        out["gps_lag"] = {"from_log": at, "seconds": shift}
    if sats:
        out["satellites"] = int(sats)
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, separators=(",", ":"))
    gaps = [(a[0], b[0]) for a, b in zip(frames, frames[1:]) if b[0] - a[0] > 10]
    print(f"{len(frames)} ตำแหน่ง · เตือน {len(alerts)} ครั้ง · ช่วงขาด {len(gaps)} ช่วง -> {out_path}")
    for a, b in gaps:
        print(f"   ขาด {b - a} วิ หลังวินาทีที่ {a}")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")  # คอนโซล Windows เป็น cp1252 พิมพ์ภาษาไทยไม่ได้
    args, opts = sys.argv[1:5], dict(zip(sys.argv[5::2], sys.argv[6::2]))
    main(*args, lag=opts.get("--lag"), sats=opts.get("--sats"))
