#!/usr/bin/env bash
# status.sh — ดูสถานะทั้งระบบในคำสั่งเดียว
#
#   bash scripts/status.sh
#
# ตอบคำถามที่ต้องถามซ้ำทุกครั้งก่อนออกภาคสนาม:
#   - service ครบไหม · โหลดชุดข้อมูลไหนอยู่ · เตือนที่กี่เมตร
#   - GPS จับดาวได้กี่ดวงแล้ว · ต้องเปิดลิงก์ไหนในมือถือ
#
# ตั้งใจอ่านค่าจาก "ของที่กำลังรันอยู่จริง" ไม่ใช่จาก /etc/mtec.env
# เพราะสองอย่างนี้ต่างกันได้ถ้าแก้ไฟล์แล้วลืม restart — ซึ่งเป็นกับดักที่เจอมาแล้ว
# (แก้ค่าแล้วเข้าใจว่ามีผลทันที ทั้งที่โปรเซสเก่ายังถือค่าเดิมอยู่)
set -uo pipefail
cd "$(dirname "$0")/.."

echo "=============================================================="
echo " สถานะระบบแจ้งเตือนจุดเสี่ยง (EMMA)"
echo "=============================================================="

echo
echo "-- service --"
for u in mtec-api mtec-tunnel mtec-alert-client mtec-autoheal.timer; do
  s="$(systemctl is-active "$u" 2>/dev/null)"
  [ "$s" = "active" ] && mark="[ok]  " || mark="[หยุด]"
  printf "  %s %-24s %s\n" "$mark" "$u" "$s"
done

echo
echo "-- ชุดข้อมูลที่ API แจกอยู่จริง --"
health="$(curl -s --max-time 5 localhost:8000/api/health)"
if [ -z "$health" ]; then
  echo "  เรียก API ไม่ได้ — mtec-api ไม่ทำงาน หรือมีโปรเซสเก่าค้างพอร์ต 8000"
  echo "  แก้: sudo systemctl restart mtec-api"
else
  # ดึงค่าด้วย python เพราะ Pi OS ไม่มี jq ติดมาให้ และไม่อยากเพิ่ม dependency
  python3 -c "
import json,sys
d = json.loads(sys.argv[1])
name = d.get('dataset','?')
ui = 'test-nstda.html' if 'nstda' in name else 'index.html'
print(f\"  ไฟล์      : {name}\")
print(f\"  จำนวนจุด  : {d.get('total_points','?')} คลัสเตอร์\")
print(f\"  เวอร์ชัน   : {d.get('version','?')}\")
print()
print(f\"  ** ต้องเปิดหน้าเว็บ {ui} เท่านั้น ไม่งั้นเห็นคนละชุดกับที่อุปกรณ์เตือน **\")
" "$health"
fi

echo
echo "-- ค่าที่ไคลเอนต์ใช้อยู่จริง (จากตอนเริ่มทำงานล่าสุด) --"
line="$(journalctl -u mtec-alert-client -n 400 --no-pager 2>/dev/null \
        | grep 'เริ่มเฝ้าระวัง' | tail -1)"
if [ -z "$line" ]; then
  echo "  ยังไม่เจอ — ไคลเอนต์อาจเพิ่งเริ่ม หรือไม่ได้ทำงาน"
else
  echo "  ${line#*: }"
fi

echo
echo "-- GPS --"
loc="$(curl -s --max-time 5 localhost:8000/api/device/location)"
if [ -z "$loc" ]; then
  echo "  เรียก API ไม่ได้"
else
  python3 -c "
import json,sys
d = json.loads(sys.argv[1])
sats = d.get('satellites')
sats = '?' if sats is None else sats
if d.get('online'):
    print(f\"  [ok] ได้พิกัดแล้ว {d['lat']:.6f}, {d['lng']:.6f} · เห็นดาว {sats} ดวง\")
    print(f\"       https://www.google.com/maps?q={d['lat']:.6f},{d['lng']:.6f}\")
elif d.get('searching'):
    print(f\"  [หา] กำลังค้นหาสัญญาณ · เห็นดาว {sats} ดวง\")
    print('       0 ดวงค้าง = ตัวรับมองไม่เห็นฟ้า ต้องย้ายที่วาง (ในอาคารไม่มีทางจับได้)')
else:
    print('  [ดับ] อุปกรณ์ไม่ได้ส่งอะไรมาเลย — ไคลเอนต์ไม่ทำงาน หรือเพิ่งเริ่ม')
" "$loc"
fi

echo
echo "=============================================================="
