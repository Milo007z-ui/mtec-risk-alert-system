#!/usr/bin/env python3
"""unit test ของ device/pi_alert_client.py — รันด้วย: python3 tests/test_pi_client.py"""

import pathlib
import sys
import threading

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "device"))

import pi_alert_client as pac  # noqa: E402

# บน Pi (Linux) stdout เป็น utf-8 อยู่แล้ว แต่ Windows console เป็น cp1252 ซึ่งพิมพ์
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

passed = 0
failed = 0


def check(name, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ✓ {name}")
    else:
        failed += 1
        print(f"  ✗ {name}")


def close(name, actual, expected, tol=1e-6):
    check(f"{name} (ได้ {actual})", actual is not None and abs(actual - expected) <= tol)


def nmea(body):
    """เติม checksum ท้ายประโยคให้ถูกต้อง — ตัวอ่านจะทิ้งบรรทัดที่ checksum ไม่ตรง"""
    csum = 0
    for ch in body:
        csum ^= ord(ch)
    return f"${body}*{csum:02X}"


def new_reader():
    """สร้าง NmeaSerialReader โดยไม่ผ่าน __init__"""
    r = object.__new__(pac.NmeaSerialReader)
    r.last_fix = None
    r.speed_kmh = None
    r.course = None
    r.course_raw = None
    r.satellites = None
    r.fix_quality = 0
    r._vtg_seen = False
    r._smoother = pac.CircularCourseSmoother()
    r._lock = threading.Lock()
    return r


print("_nmea_float:")
close("ตัวเลขปกติ", pac._nmea_float("123.4"), 123.4)
# ฟิลด์ COG ว่างได้จริงเมื่อรถจอดนิ่ง ถ้าไม่ดัก float("") จะโยน ValueError ทุกวินาที
check("ฟิลด์ว่าง -> None (เกิดจริงตอนรถจอด)", pac._nmea_float("") is None)
check("ค่าขยะ -> None ไม่ใช่ระเบิด", pac._nmea_float("abc") is None)

print()
print("อ่าน COG จากประโยค RMC (field 8):")
# $GPRMC,time,A,lat,N,lon,E,speedKnots,courseTrue,date,,
r = new_reader()
r._handle(nmea("GPRMC,081836,A,1345.3379,N,10030.1080,E,20.5,145.7,130998,,"))
close("อ่าน COG = 145.7° ได้ (ไม่ใช่ค่า speed ที่อยู่คอลัมน์ก่อนหน้า)", r.course, 145.7)
close("ความเร็ว 20.5 knot -> 37.97 กม./ชม.", r.speed_kmh, 20.5 * 1.852, 0.01)
check("พิกัดยังอ่านได้เหมือนเดิม", r.last_fix is not None)
close("ละติจูด 1345.3379 -> 13.7556°", r.last_fix[0], 13 + 45.3379 / 60, 1e-6)

r = new_reader()
# รถจอดนิ่ง: ตัวรับปล่อยฟิลด์ COG ว่างไว้เพราะไม่มีเวกเตอร์ความเร็วจะรายงาน
r._handle(nmea("GPRMC,081836,A,1345.3379,N,10030.1080,E,0.0,,130998,,"))
check("รถจอด COG ว่าง -> None (ไม่ใช่ 0 องศา ซึ่งแปลว่ามุ่งหน้าทิศเหนือ)", r.course is None)

r = new_reader()
r._handle(nmea("GPRMC,081836,V,,,,,,,130998,,"))  # V = ยังไม่ได้ fix
check("fix ไม่ valid (V) -> ไม่รับอะไรเลย", r.course is None and r.last_fix is None)

print()
print("อ่าน COG จากประโยค VTG (field 1) และลำดับความสำคัญ:")
# $GPVTG,courseTrue,T,courseMag,M,knots,N,kmh,K,mode
r = new_reader()
r._handle(nmea("GPVTG,89.68,T,,M,0.00,N,25.30,K,A"))
close("อ่าน COG true = 89.68°", r.course, 89.68)
close("ความเร็วจาก VTG เป็น กม./ชม. อยู่แล้ว ไม่ต้องแปลง", r.speed_kmh, 25.30)

# BE-609U ส่งทั้ง VTG และ RMC ทุกวินาที ต้องยึด VTG เพราะมี COG กับความเร็วอยู่ประโยค
r = new_reader()
r._handle(nmea("GPVTG,89.68,T,,M,0.00,N,25.30,K,A"))
r._handle(nmea("GPRMC,081836,A,1345.3379,N,10030.1080,E,20.5,145.7,130998,,"))
close("เห็น VTG แล้ว RMC ต้องไม่เขียนทับค่าทิศ", r.course, 89.68)

r = new_reader()
r._handle(nmea("GPRMC,081836,A,1345.3379,N,10030.1080,E,20.5,145.7,130998,,"))
close("ตัวรับที่ไม่ส่ง VTG -> ใช้ค่าจาก RMC ได้ตามปกติ", r.course, 145.7)

r = new_reader()
_line = nmea("GPVTG,89.68,T,,M,0.00,N,25.30,K,A")
r._handle(_line[:-2] + "00")  # ทำ checksum ให้ผิด
check("checksum ผิด -> ทิ้งทั้งบรรทัด (สัญญาณกวนทำให้ตัวเลขเพี้ยนได้)", r.course is None)

print()
print("CourseTracker (speed gate + last-known-good):")
t = pac.CourseTracker()
check("เพิ่งเริ่ม -> None (ไม่รู้ทิศ = ไม่กรอง เตือนไว้ก่อน)", t.get(now=0) is None)
check("รถยังคลาน 3 กม./ชม. -> ยังไม่รับค่า", t.update(90, 3, now=0) is None)
close("วิ่ง 60 กม./ชม. -> รับค่า 90°", t.update(90, 60, now=1), 90)
# หัวใจของ gate: ตอนจอดนิ่ง COG ที่โมดูลส่งมาหมุนสุ่มทั้ง 360 องศา
close("จอดนิ่ง COG สุ่มมา 270° -> ไม่รับ คงค่าเดิม", t.update(270, 0, now=2), 90)
close("คลาน 4.9 กม./ชม. -> ยังคงค่าเดิม", t.update(180, 4.9, now=3), 90)
close("ถึง 5 กม./ชม. พอดี -> รับค่าใหม่", t.update(180, 5, now=4), 180)
close("โมดูลไม่ส่ง COG รอบนี้ -> คงค่าเดิม", t.update(None, 80, now=5), 180)
close("ไม่รู้ความเร็ว -> ไม่กล้ารับค่าใหม่", t.update(45, None, now=6), 180)
close("จอดไฟแดง 119 วิ -> ค่าเก่ายังใช้ได้", t.get(now=4 + 119), 180)
check("จอดเกิน 2 นาที -> ทิ้งค่า (กลับรถ/เข้าอู่แล้วทิศเก่าอันตรายกว่าไม่รู้ทิศ)",
      t.get(now=4 + 121) is None)

t = pac.CourseTracker()
close("360° -> 0°", t.update(360, 50, now=0), 0)
close("ทศนิยมสูงสุดที่ตัวรับส่งได้ 359.9°", t.update(359.9, 50, now=1), 359.9)

print()
print("UBX frame builder (ตรวจกับเฟรมมาตรฐานที่เอกสาร u-blox ระบุไว้):")
# สองเฟรมนี้เป็นค่าที่ตีพิมพ์ไว้ในเอกสาร u-blox ใช้เป็นหลักฐานว่าสูตร checksum ถูก
check("MON-VER poll = B5 62 0A 04 00 00 0E 34",
      pac._ubx_frame(0x0A, 0x04) == bytes.fromhex("B5620A0400000E34"))
check("CFG-RATE poll = B5 62 06 08 00 00 0E 30",
      pac._ubx_frame(0x06, 0x08) == bytes.fromhex("B5620608 00000E30".replace(" ", "")))

f = pac._ubx_frame(0x06, 0x8A, bytes.fromhex("010203"))
check("ความยาว payload เขียนเป็น little-endian 2 ไบต์", f[4:6] == bytes.fromhex("0300"))
check("ขึ้นต้นด้วย sync bytes B5 62 เสมอ", f[:2] == bytes.fromhex("B562"))

print()
print("UBX-CFG-VALSET (คำสั่งตั้งค่าที่ส่งจริง):")
frame = pac._ubx_valset([(pac.UBX_KEY_RATE_MEAS, 100)])
check("class/id = 0x06/0x8A (CFG-VALSET)", frame[2] == 0x06 and frame[3] == 0x8A)
check("เขียนลง RAM เท่านั้น (layers = 0x01) ไม่แตะ FLASH", frame[7] == pac.UBX_LAYER_RAM)
check("layers ที่ใช้ ไม่มีบิต FLASH (0x04) ติดมาด้วย",
      pac.UBX_LAYER_RAM & 0x04 == 0)
# คีย์ 0x30210001 บิต 28-30 = 0x3 = ค่าขนาด 2 ไบต์ -> 100 ms = 0x0064 little-endian
check("คีย์เขียน little-endian", frame[10:14] == (0x30210001).to_bytes(4, "little"))
check("ค่า 100 ms เขียนเป็น U2 ตามขนาดที่ฝังในคีย์", frame[14:16] == bytes.fromhex("6400"))
check("payload ยาว 4 + 4 + 2 = 10 ไบต์", frame[4:6] == (10).to_bytes(2, "little"))

# 10Hz ต้องแปลงเป็นคาบ 100 ms — ผิดตรงนี้ = ตั้งอัตราผิดโดยไม่มีใครรู้
for hz, ms in [(1, 1000), (5, 200), (10, 100)]:
    fr = pac._ubx_valset([(pac.UBX_KEY_RATE_MEAS, int(round(1000 / hz)))])
    check(f"{hz}Hz -> คาบ {ms} ms", fr[14:16] == ms.to_bytes(2, "little"))

# ทุกคีย์ NMEA ต้องเป็นขนาด 1 ไบต์ (0x2091xxxx) ไม่งั้นประกอบเฟรมผิดขนาด
check("คีย์ NMEA ทุกตัวเป็นขนาด 1 ไบต์ตามที่ฝังในเลขคีย์",
      all((k >> 28) & 0x07 == 0x02 for k in pac.UBX_KEY_MSGOUT_UART1.values()))
check("ประโยคที่เก็บกับที่ปิด ไม่ทับกัน", not set(pac.NMEA_KEEP) & set(pac.NMEA_DROP))
check("ประโยคที่ระบบอ่านจริง (RMC/VTG/GGA) อยู่ในชุดที่เก็บไว้ครบ",
      set(pac.NMEA_KEEP) == {"RMC", "VTG", "GGA"})
check("ทุกชื่อประโยคที่อ้างถึง มีคีย์รองรับครบ",
      all(n in pac.UBX_KEY_MSGOUT_UART1 for n in pac.NMEA_KEEP + pac.NMEA_DROP))

print()
print("งบประมาณ bandwidth ที่ 10Hz (เหตุผลที่ต้องปิด GSV/GSA/GLL):")
# 115200 8N1 = 10 บิตต่อ 1 ไบต์
budget = pac.GPS_BAUD / 10
keep_bytes = 80 + 45 + 80          # GGA + VTG + RMC โดยประมาณ
all_bytes = keep_bytes + 50 + 65 * 4 + 70 * 12   # + GLL + GSA×4 + GSV×12 (multi-GNSS)
check(f"เปิดครบทุกประโยคที่ 10Hz ล้นสาย ({all_bytes * 10 / budget * 100:.0f}% > 100%)",
      all_bytes * 10 > budget)
check(f"เหลือ {'+'.join(pac.NMEA_KEEP)} ที่ 10Hz อยู่ในงบ ({keep_bytes * 10 / budget * 100:.0f}%)",
      keep_bytes * 10 < budget * 0.8)

print()
print("CircularCourseSmoother (เฉลี่ยทิศแบบวงกลม):")
sm = pac.CircularCourseSmoother(window_s=0.5)
check("ยังไม่มีตัวอย่าง -> None", sm.get(now=0) is None)
# จำลอง 10Hz คร่อมรอย 0/360 — เฉลี่ยองศาตรง ๆ จะได้ ~180 ซึ่งชี้ตรงข้ามพอดี
for i, deg in enumerate([358, 359, 0, 1, 2]):
    out = sm.add(deg, 60, now=i * 0.1)
check(f"คร่อมรอย 0/360 เฉลี่ยได้ ~0° ไม่ใช่ ~180° (ได้ {out:.1f}°)",
      out < 2 or out > 358)
sm = pac.CircularCourseSmoother(window_s=0.5)
for i in range(4):
    sm.add(90, 60, now=i * 0.1)
spiked = sm.add(200, 60, now=0.4)   # ค่าหลุดจาก multipath 1 เฟรม
check(f"ค่าหลุด 1 เฟรมถูกกลืนไว้ (ได้ {spiked:.1f}° ไม่ใช่ 200°)",
      90 < spiked < 130)
sm = pac.CircularCourseSmoother(window_s=0.5)
sm.add(0, 60, now=0)
check("ตัวอย่างเก่าเกินหน้าต่างถูกทิ้ง -> ได้ 90 เป๊ะ", sm.add(90, 60, now=2.0) == 90)
sm = pac.CircularCourseSmoother(window_s=0.5)
sm.add(120, 60, now=0)
# ตอนรถจอด COG หมุนสุ่ม ห้ามเก็บเข้าหน้าต่าง และต้องคืนค่าล่าสุดที่เชื่อได้แทน
check("จอดนิ่ง (0 กม./ชม.) -> ไม่เก็บตัวอย่าง คืนค่าเดิม 120°",
      sm.add(45, 0, now=0.1) == 120)
check("หน้าต่างหมดอายุแล้วยังคืน last-known-good ไม่ใช่ None",
      sm.get(now=5.0) == 120)
check("ไม่คืน 0 (0 แปลว่ามุ่งหน้าทิศเหนือ ซึ่งเป็นข้อมูลผิด)", sm.get(now=99.0) != 0)
sm = pac.CircularCourseSmoother(window_s=0.5)
sm.add(10, 60, now=0)
sm.add(0, 60, now=1.0)          # หน้าต่างเก่าหมดอายุแล้ว -> ทิศที่เชื่อได้ล่าสุด = 0
# ตัวอย่างที่ชี้ตรงข้ามกันพอดีหักล้างกันหมด หาทิศกลางไม่ได้ -> ต้องใช้ค่าเดิม ไม่ใช่เดามั่ว
after = sm.add(180, 60, now=1.05)
check("0° กับ 180° หักล้างกัน -> ไม่เชื่อ ใช้ last-known-good", after == 0)
check("เรียกซ้ำก็ยังได้ค่าเดิม ไม่แกว่ง", sm.get(now=1.05) == 0)
sm = pac.CircularCourseSmoother(window_s=0.5, min_speed_kmh=5)
check("COG ว่าง (None) -> ไม่เก็บ", sm.add(None, 60, now=0) is None)
check("ไม่รู้ความเร็ว -> ไม่เก็บ", sm.add(90, None, now=0.1) is None)
check("ช้ากว่าเกณฑ์ -> ไม่เก็บ", sm.add(90, 4.9, now=0.2) is None)
check("ถึงเกณฑ์พอดี -> เก็บ", sm.add(90, 5.0, now=0.3) == 90)

print()
print("_angle_diff_deg — มุมวนรอบ 360 องศา:")
close("350° กับ 10° ต่างกัน 20° ไม่ใช่ 340°", pac._angle_diff_deg(350, 10), 20)
close("ไม่ขึ้นกับลำดับ", pac._angle_diff_deg(10, 350), 20)
close("359.9° กับ 0.1° ต่างกัน 0.2°", pac._angle_diff_deg(359.9, 0.1), 0.2, 1e-9)
close("ตรงข้ามกัน = 180°", pac._angle_diff_deg(0, 180), 180)
close("มุมเดียวกัน = 0°", pac._angle_diff_deg(90, 90), 0)
check("ไม่เกิน 180 เสมอ",
      all(pac._angle_diff_deg(a, b) <= 180
          for a, b in [(0, 359), (180, 0), (90, 271), (359, 181), (720, 0)]))

print()
print("_bearing_deg:")
O = (13.7563, 100.5018)
close("ไปทางเหนือ = 0°", pac._bearing_deg(*O, 13.8563, 100.5018), 0, 0.5)
close("ไปทางตะวันออก = 90°", pac._bearing_deg(*O, 13.7563, 100.6018), 90, 0.5)
close("ไปทางใต้ = 180°", pac._bearing_deg(*O, 13.6563, 100.5018), 180, 0.5)
close("ไปทางตะวันตก = 270°", pac._bearing_deg(*O, 13.7563, 100.4018), 270, 0.5)

print()
print("is_ahead (ต้องให้ผลตรงกับ isAhead ใน js/distance.js ทุกเคส):")
N = (13.7663, 100.5018)   # เหนือ ~1.1 กม.
S = (13.7463, 100.5018)   # ใต้  ~1.1 กม.
E = (13.7563, 100.5118)   # ตะวันออก ~1.1 กม. = ตั้งฉากกับหัวรถพอดี
check("จุดข้างหน้า -> เตือน", pac.is_ahead(0, *O, *N, 90))
check("จุดข้างหลัง -> ข้าม", not pac.is_ahead(0, *O, *S, 90))
check("จุดตั้งฉาก 90° -> เตือน (นับขอบเข้าด้วย)", pac.is_ahead(0, *O, *E, 90))
check("ยังไม่รู้ทิศ -> เตือนไว้ก่อน", pac.is_ahead(None, *O, *S, 90))
check("window 180 = ปิดการกรอง -> เตือนทุกทิศ", pac.is_ahead(0, *O, *S, 180))
check("รถทับจุดพอดี -> เตือน (ทิศไม่มีความหมายที่ระยะนั้น)", pac.is_ahead(0, *O, *O, 90))
check("จุดข้างหลังห่างแค่ 10 ม. -> ยังเตือน (ใกล้เกินกว่าจะเชื่อทิศ)",
      pac.is_ahead(0, *O, 13.75621, 100.5018, 90))
check("จุดข้างหลังห่าง 100 ม. -> ข้าม (พ้นระยะยกเว้น 30 ม. แล้ว)",
      not pac.is_ahead(0, *O, 13.7554, 100.5018, 90))
# รถวิ่งขึ้นเหนือ = เคสที่พังง่ายที่สุดถ้าเทียบมุมด้วยการลบตรง ๆ
check("ทิศ 359.5° จุดทางเหนือ -> ข้างหน้า (ข้ามรอย 0/360)", pac.is_ahead(359.5, *O, *N, 90))
check("ทิศ 0.5° จุดทางใต้ -> ข้างหลัง", not pac.is_ahead(0.5, *O, *S, 90))
check("ทิศ 350° จุดทางเหนือ -> ข้างหน้า (ต่างกัน 10° ไม่ใช่ 350°)",
      pac.is_ahead(350, *O, *N, 90))

print()
print("ค่าตั้งต้นต้องตรงกับฝั่งเว็บ (js/distance.js):")
check("มุมกรวยเริ่มต้น = 30", pac.DEFAULT_HEADING_WINDOW_DEG == 30)
check("ระยะยกเว้นการกรองทิศ = 30 ม.", pac.HEADING_NEAR_BYPASS_M == 30)
check("เกณฑ์ความเร็วของ COG = 5 กม./ชม.", pac.COG_MIN_SPEED_KMH == 5)
check("อายุทิศที่ค้างไว้ = 120 วิ", pac.COG_HOLD_MAX_S == 120)
check("หน้าต่างเฉลี่ยทิศ = 0.5 วิ (ตรงกับ COURSE_WINDOW_MS = 500 ใน js/distance.js)",
      pac.COURSE_WINDOW_S == 0.5)
check("อัตราที่สั่งโมดูล = 10Hz", pac.GPS_UPDATE_HZ == 10)

print()
print(f"ผล: ผ่าน {passed} / {passed + failed}")
sys.exit(1 if failed else 0)
