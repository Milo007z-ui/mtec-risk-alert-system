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
cp systemd/mtec-api.service systemd/mtec-alert-client.service systemd/mtec-tunnel.service \
   /etc/systemd/system/
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
if grep -q '^NGROK_DOMAIN=.\+' /etc/mtec.env 2>/dev/null; then
  systemctl enable mtec-tunnel.service >/dev/null
  echo "    เปิด mtec-tunnel ด้วย (พบ NGROK_DOMAIN แล้ว)"
else
  echo "    ยังไม่เปิด mtec-tunnel เพราะยังไม่ได้กรอก NGROK_DOMAIN"
fi

cat <<'EOF'

================================================================
ติดตั้งเสร็จแล้ว — เหลืออีก 2 ขั้นตอน (ทำครั้งเดียว ตอนอยู่กับคอม)

1) สมัคร ngrok ฟรีเพื่อขอโดเมนคงที่ https://dashboard.ngrok.com
   - Your Authtoken          -> คัดลอกไว้
   - Domains > New Domain    -> จะได้ชื่อแบบ xxxx-yyyy.ngrok-free.app

2) กรอกลงไฟล์ตั้งค่า แล้วเปิด tunnel
   sudo nano /etc/mtec.env          # ใส่ NGROK_AUTHTOKEN กับ NGROK_DOMAIN
   sudo systemctl enable --now mtec-tunnel
   sudo systemctl start mtec-api mtec-alert-client

   ถ้ายังไม่ได้ติดตั้ง ngrok:
   curl -sSL https://bin.equinox.io/c/bNyj1mQVY4c/ngrok-v3-stable-linux-arm64.tgz \
     | sudo tar xz -C /usr/local/bin

ลิงก์ที่จะ bookmark ไว้ในมือถือ (คงที่ ไม่เปลี่ยนอีกเลย):

   https://<NGROK_DOMAIN>/test-nstda.html

ตรวจสถานะ:  systemctl status mtec-api mtec-alert-client mtec-tunnel
ดู log:      journalctl -u mtec-alert-client -f
================================================================
EOF
