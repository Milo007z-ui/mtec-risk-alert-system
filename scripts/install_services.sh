#!/usr/bin/env bash
# install_services.sh — ติดตั้งให้ระบบทั้งชุดเริ่มเองตอนเสียบไฟ (ทำครั้งเดียว)
#
# หลังติดตั้งเสร็จ เวลาออกภาคสนามแค่ "เสียบไฟ Pi" อย่างเดียว ไม่ต้องมีคอม ไม่ต้องพิมพ์อะไร
# แล้วเปิดลิงก์ที่ bookmark ไว้ในมือถือดูตำแหน่งได้เลย
#
#   sudo bash scripts/install_services.sh
#
# ทำอะไรบ้าง:
#   1. คัดลอก systemd/*.service ไป /etc/systemd/system/
#   2. สร้าง /etc/mtec.env จากไฟล์ตัวอย่าง (ถ้ายังไม่มี)
#   3. enable ให้เริ่มเองตอนบูต
#
# ⚠️ ต้องกรอก NGROK_AUTHTOKEN กับ NGROK_DOMAIN ใน /etc/mtec.env ก่อน tunnel จะทำงาน
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
  echo "ต้องรันด้วย sudo:  sudo bash scripts/install_services.sh"
  exit 1
fi

cd "$(dirname "$0")/.."
REPO_DIR="$(pwd)"

# unit ทั้งหมดตั้ง WorkingDirectory=/home/pi/mtec-risk-alert-system ไว้ตายตัว
# ถ้า clone ไว้ที่อื่นจะ start ไม่ขึ้นแล้วหาสาเหตุยาก เลยตรวจให้ตั้งแต่ต้น
if [ "$REPO_DIR" != "/home/pi/mtec-risk-alert-system" ]; then
  echo "!!! โปรเจกต์อยู่ที่ $REPO_DIR"
  echo "    แต่ไฟล์ .service ตั้งค่าไว้ที่ /home/pi/mtec-risk-alert-system"
  echo "    แก้ WorkingDirectory ในไฟล์ systemd/*.service ให้ตรงก่อน แล้วรันใหม่"
  exit 1
fi

echo "==> คัดลอกไฟล์ service"
cp systemd/mtec-api.service systemd/mtec-alert-client.service /etc/systemd/system/

# path ของ ngrok ต่างกันตามวิธีติดตั้ง (snap -> /snap/bin, apt -> /usr/local/bin)
# systemd บังคับให้ ExecStart เป็น absolute path จึงต้องหาให้ตอนติดตั้ง ล็อกไว้ในไฟล์ไม่ได้
NGROK_BIN="$(command -v ngrok || true)"
if [ -z "$NGROK_BIN" ]; then
  # command -v ไม่เห็น /snap/bin ตอนรันผ่าน sudo เพราะ PATH ถูกล้าง จึงเช็คตรง ๆ อีกที
  for c in /snap/bin/ngrok /usr/local/bin/ngrok /usr/bin/ngrok; do
    [ -x "$c" ] && NGROK_BIN="$c" && break
  done
fi
if [ -z "$NGROK_BIN" ]; then
  echo "    ยังไม่พบ ngrok — ข้ามการติดตั้ง mtec-tunnel ไปก่อน"
  echo "    ติดตั้งแล้วรันสคริปต์นี้ซ้ำได้ ไม่มีผลกับ service อื่น"
else
  sed "s|__NGROK_BIN__|$NGROK_BIN|" systemd/mtec-tunnel.service \
    > /etc/systemd/system/mtec-tunnel.service
  echo "    พบ ngrok ที่ $NGROK_BIN"
fi
echo "    /etc/systemd/system/mtec-{api,alert-client,tunnel}.service"

echo "==> ตั้งค่า /etc/mtec.env"
if [ -f /etc/mtec.env ]; then
  echo "    มีอยู่แล้ว — ไม่เขียนทับ (ค่าที่ตั้งไว้เดิมยังอยู่ครบ)"
else
  cp systemd/mtec.env.example /etc/mtec.env
  # มี NGROK_AUTHTOKEN อยู่ในไฟล์ อ่านได้เฉพาะ root
  chmod 600 /etc/mtec.env
  echo "    สร้างใหม่จากไฟล์ตัวอย่างแล้ว"
fi

echo "==> ให้ผู้ใช้ pi อ่านพอร์ต GPS ได้"
usermod -a -G dialout pi

echo "==> เปิดให้เริ่มเองตอนบูต"
systemctl daemon-reload
systemctl enable mtec-api.service mtec-alert-client.service >/dev/null

# tunnel enable ให้เฉพาะเมื่อกรอกโดเมนแล้ว ไม่งั้นจะ restart วนไม่รู้จบตอนบูต
# แล้ว log เต็มไปด้วย error จนกลบปัญหาจริงของ service อื่น
if grep -q '^NGROK_DOMAIN=.\+' /etc/mtec.env 2>/dev/null \
   && [ -f /etc/systemd/system/mtec-tunnel.service ]; then
  systemctl enable mtec-tunnel.service >/dev/null
  echo "    เปิด mtec-tunnel ด้วย (พบ NGROK_DOMAIN แล้ว)"
else
  echo "    ยังไม่เปิด mtec-tunnel (ต้องมีทั้ง ngrok ติดตั้งแล้ว และกรอก NGROK_DOMAIN)"
fi

cat <<'EOF'

================================================================
ติดตั้งเสร็จแล้ว — เหลืออีก 2 ขั้นตอน (ทำครั้งเดียว ตอนอยู่กับคอม)

1) ติดตั้ง ngrok แล้วผูก authtoken (ถ้ายังไม่ได้ทำ)
   sudo snap install ngrok
   ngrok config add-authtoken <TOKEN จาก dashboard.ngrok.com > Your Authtoken>
   sudo bash scripts/install_services.sh     # รันซ้ำ เพื่อให้สคริปต์เจอ ngrok

2) กรอกโดเมนคงที่ลงไฟล์ตั้งค่า แล้วเปิดทั้งหมด
   บัญชีใหม่ของ ngrok แถมโดเมนคงที่มาให้แล้ว ดูที่เมนู Domains
   หน้าตาแบบ  xxxx-yyyy-zzzz.ngrok-free.dev   (ไม่ต้องใส่ https:// นำหน้า)

   sudo nano /etc/mtec.env          # ใส่ NGROK_AUTHTOKEN กับ NGROK_DOMAIN
   sudo systemctl enable --now mtec-tunnel
   sudo systemctl start mtec-api mtec-alert-client

ลิงก์ที่จะ bookmark ไว้ในมือถือ (คงที่ ไม่เปลี่ยนอีกเลย):

   https://<NGROK_DOMAIN>/test-nstda.html

ตรวจสถานะ:  systemctl status mtec-api mtec-alert-client mtec-tunnel
ดู log:      journalctl -u mtec-alert-client -f
================================================================
EOF
