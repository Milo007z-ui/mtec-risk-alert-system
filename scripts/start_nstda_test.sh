#!/usr/bin/env bash
# start_nstda_test.sh — เปิดระบบทดสอบภาคสนาม สวทช. ด้วยคำสั่งเดียว
#
# รวบขั้นตอนที่ต้องทำมือทั้งหมดไว้ที่เดียว เพราะลำดับมันพลาดง่ายและอาการที่ได้
# ก็ชวนเข้าใจผิด: ลืม pkill -> uvicorn ตัวใหม่ตาย แต่ตัวเก่ายังตอบด้วยชุดข้อมูล
# กรุงเทพฯ ทำให้เหมือนใช้งานได้แต่อุปกรณ์เตือนคนละจุดกับหมุดบนแผนที่
#
#   bash scripts/start_nstda_test.sh              # ไม่มีเสียงพูด (ค่าเริ่มต้น)
#   bash scripts/start_nstda_test.sh --speak      # เปิดเสียงพูดด้วย
#   bash scripts/start_nstda_test.sh --tunnel     # เปิด URL สาธารณะ https ให้ดูจากที่ไหนก็ได้
#
# --tunnel มีไว้ตอนมือถือไม่ได้อยู่วงเดียวกับ Pi (เช่น Pi ใช้เน็ตจาก USB dongle)
# ซึ่งลิงก์ IP วงใน 192.168.x.x เปิดจากมือถือไม่ได้ ต้องมี URL สาธารณะแทน
#
# กด Ctrl+C ครั้งเดียวหยุดทั้ง API และไคลเอนต์
set -euo pipefail

cd "$(dirname "$0")/.."

DATASET="data/risk_points_nstda_test.geojson"
PORT=8000
# 60/80 ม. ต้องตรงกับที่ test-nstda.html ตั้งไว้ ไม่งั้น Pi กับเว็บเตือนคนละระยะ
# แล้วผลทดสอบจะไม่ตอบคำถามว่าอุปกรณ์ทำงานตรงกับระบบหรือไม่
ALERT_M=60
EXIT_M=80

SPEAK_FLAG="--no-speak"
USE_TUNNEL=0
for arg in "$@"; do
  case "$arg" in
    --speak)  SPEAK_FLAG="" ;;
    --tunnel) USE_TUNNEL=1 ;;
    *) echo "ไม่รู้จักตัวเลือก: $arg (ใช้ได้: --speak --tunnel)"; exit 1 ;;
  esac
done

echo "==> ปิด uvicorn ตัวเก่าที่อาจค้างพอร์ต $PORT"
# ตัวเก่ายังตอบ curl ได้ด้วยข้อมูลเก่า ทำให้ตรวจไม่เจอว่าตัวใหม่ไม่ได้ขึ้น
pkill -f "uvicorn api.server:app" 2>/dev/null || true
sleep 1

echo "==> เปิด API ด้วยชุดข้อมูลสนามทดสอบ ($DATASET)"
RISK_DATA_FILE="$DATASET" python3 -m uvicorn api.server:app \
  --host 0.0.0.0 --port "$PORT" --log-level warning &
API_PID=$!
# ปิด API ตามเมื่อสคริปต์จบ ไม่งั้นรอบหน้าจะเจอ address already in use อีก
trap 'echo; echo "==> ปิด API (pid $API_PID)"; kill $API_PID 2>/dev/null || true' EXIT

echo "==> รอ API พร้อม"
for i in $(seq 30); do
  if curl -sf "http://localhost:$PORT/api/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done

HEALTH=$(curl -s "http://localhost:$PORT/api/health" || echo '{}')
echo "    $HEALTH"
case "$HEALTH" in
  *nstda*) ;;
  *) echo "!!! API ไม่ได้แจกชุดสนามทดสอบ — น่าจะมี uvicorn ตัวเก่าค้างอยู่"
     echo "    ลอง: pkill -f uvicorn  แล้วรันสคริปต์นี้ใหม่"; exit 1 ;;
esac

if [ "$USE_TUNNEL" = "1" ]; then
  if ! command -v cloudflared >/dev/null 2>&1; then
    echo "!!! ยังไม่ได้ติดตั้ง cloudflared — ติดตั้งครั้งเดียวด้วย:"
    echo "    curl -L https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-arm64.deb -o /tmp/cf.deb"
    echo "    sudo dpkg -i /tmp/cf.deb"
    exit 1
  fi

  echo "==> เปิด tunnel สาธารณะ (https)"
  TUNNEL_LOG=$(mktemp)
  cloudflared tunnel --url "http://localhost:$PORT" >"$TUNNEL_LOG" 2>&1 &
  TUNNEL_PID=$!
  # ปิด tunnel ตามด้วยเมื่อสคริปต์จบ ไม่งั้นจะเหลือ URL สาธารณะเปิดค้างทิ้งไว้
  trap 'echo; echo "==> ปิด API + tunnel"; kill $API_PID $TUNNEL_PID 2>/dev/null || true; rm -f "$TUNNEL_LOG"' EXIT

  # cloudflared พิมพ์ URL ลง log หลังเชื่อมต่อเสร็จ ใช้เวลาไม่กี่วินาที
  PUBLIC_URL=""
  for i in $(seq 40); do
    PUBLIC_URL=$(grep -o 'https://[a-z0-9-]*\.trycloudflare\.com' "$TUNNEL_LOG" | head -1 || true)
    [ -n "$PUBLIC_URL" ] && break
    sleep 0.5
  done

  if [ -z "$PUBLIC_URL" ]; then
    echo "!!! ไม่ได้ URL จาก cloudflared ภายใน 20 วิ — ดู log: $TUNNEL_LOG"
    echo "    (ยังใช้ลิงก์วงในต่อได้ ไม่ต้องหยุดสคริปต์)"
  else
    echo
    echo "  ================================================================"
    echo "   เปิดลิงก์นี้จากมือถือได้เลย ใช้เน็ตมือถือก็ได้ ไม่ต้องอยู่วงเดียวกัน"
    echo
    echo "   $PUBLIC_URL/test-nstda.html"
    echo
    echo "   (ปิดสคริปต์เมื่อไหร่ ลิงก์นี้ใช้ไม่ได้ทันที และรอบหน้าจะได้ URL ใหม่)"
    echo "  ================================================================"
    echo
  fi
fi

echo
echo "==> เริ่มไคลเอนต์ (Ctrl+C เพื่อหยุดทั้งหมด)"
echo
exec python3 device/pi_alert_client.py \
  --api "http://localhost:$PORT" --serial \
  --alert-radius "$ALERT_M" --exit-radius "$EXIT_M" $SPEAK_FLAG
