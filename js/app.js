/**
 * app.js — จุดเริ่มต้น: ประกอบทุกโมดูลเข้าด้วยกัน
 */

(async function main() {
  const statusEl = document.getElementById("gps-status");
  const overlay = document.getElementById("start-overlay");
  const startBtn = document.getElementById("btn-start");

  TTS.init();
  const map = MapView.init();

  // ชั้นตำแหน่งอุปกรณ์ Raspberry Pi บนรถ — เริ่มทันทีโดยไม่ต้องรอกด "เริ่มใช้งาน"
  // เพราะเป็นการ "ดู" ตำแหน่งรถคันอื่น ไม่ต้องขอสิทธิ์ตำแหน่งหรือปลดล็อกเสียงก่อน
  // (ใช้ได้ทั้งแผนที่จริง โหมด ?mock=1 และหน้าทดสอบ สวทช.)
  if (typeof DeviceTracker !== "undefined") DeviceTracker.start(map);

  // โหลดหน่วยวิเคราะห์ (คลัสเตอร์ + จุดเสี่ยงเดี่ยว) — ถ้าโหลดไม่ได้แอปทำอะไรต่อไม่ได้
  //
  // ชั้นจุดเสี่ยงรายอุบัติเหตุ (accidents.js) เป็นชั้นดูอย่างเดียว เริ่มต้นปิดไว้
  // ผู้ใช้ติ๊กเปิดเองในแผงตัวกรอง — ไม่มีผลกับการแจ้งเตือน เพราะ alert.js
  // อ่านจาก RiskPoints.visible() ซึ่งเป็นคลัสเตอร์ล้วน
  const hasAccidentLayer = typeof Accidents !== "undefined";
  try {
    await Promise.all([RiskPoints.load(), hasAccidentLayer ? Accidents.load() : null]);
    if (GPS.isMockMode()) RiskPoints.remove(GPS.mockExcludes()); // ซ่อนวงที่รถไม่ได้ขับผ่านจริง (เฉพาะจำลอง)
    if (hasAccidentLayer) Accidents.drawOnMap(map); // วาดชั้นจุดก่อน ให้คลัสเตอร์อยู่ทับด้านบน
    RiskPoints.drawOnMap(map);
    Filters.init(); // แผงตัวกรองต้องสร้างหลังวาดหมุด (ต้องใช้รายชื่อจังหวัดจากข้อมูล)
    await GPS.prepare(); // โหมดจำลอง: เตรียมเส้นทางถนนจริงไว้ล่วงหน้า
    const clusters = RiskPoints.all().filter((p) => p.unit_type === "cluster").length;
    const accText = hasAccidentLayer
      ? ` · จุดเสี่ยง ${Accidents.all().length.toLocaleString("th-TH")} จุดพร้อมให้เปิดดู`
      : "";
    statusEl.textContent =
      `โหลดคลัสเตอร์ ${clusters} วงแล้ว${accText} — กด "เริ่มใช้งาน" เพื่อเปิดการติดตาม`;
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
