/**
 * app.js — จุดเริ่มต้น: ประกอบทุกโมดูลเข้าด้วยกัน
 */

(async function main() {
  const statusEl = document.getElementById("gps-status");
  const overlay = document.getElementById("start-overlay");
  const startBtn = document.getElementById("btn-start");

  TTS.init();
  const map = MapView.init();

  // โหลดจุดเสี่ยงก่อน — ถ้าโหลดไม่ได้แอปทำอะไรต่อไม่ได้ ให้แจ้งชัดๆ
  try {
    const points = await RiskPoints.load();
    RiskPoints.drawOnMap(map);
    statusEl.textContent = `โหลดจุดเสี่ยง ${points.length} จุดแล้ว — กด "เริ่มใช้งาน" เพื่อเปิดการติดตาม`;
  } catch (err) {
    statusEl.textContent = `❌ ${err.message} — ตรวจว่าเปิดผ่าน local server ไม่ใช่ file://`;
    startBtn.disabled = true;
    return;
  }

  // ปุ่มเริ่มใช้งาน: ปลดล็อก TTS (ต้องเป็น user gesture) + เริ่ม GPS
  startBtn.addEventListener("click", () => {
    TTS.unlock();
    overlay.classList.add("hidden");

    if (!TTS.isSupported()) {
      showStatus("⚠️ เครื่องนี้ไม่รองรับเสียงพูด จะแจ้งเตือนด้วยแบนเนอร์บนจอแทน");
    }

    showStatus(GPS.isMockMode() ? "🧪 โหมดจำลอง GPS" : "กำลังค้นหาตำแหน่ง...");

    // โหมดจำลอง: วาดเส้นทางที่จะขับ (ผ่านจุดเสี่ยงจริงหลายจุด) ก่อนเริ่มเคลื่อนที่
    if (GPS.isMockMode()) {
      const route = GPS.getMockRoute();
      if (route.length) MapView.drawRoute(route.map((p) => [p.lat, p.lng]));
    }

    GPS.start(
      (lat, lng, accuracy) => {
        MapView.updateUserPosition(lat, lng, accuracy);
        AlertSystem.onPositionUpdate(lat, lng);
        if (!GPS.isMockMode()) {
          showStatus(`📍 GPS ทำงาน (ความแม่นยำ ±${Math.round(accuracy)} ม.)`);
        }
      },
      (message) => showStatus(`❌ ${message}`)
    );
  });

  function showStatus(text) {
    statusEl.textContent = text;
  }
})();
