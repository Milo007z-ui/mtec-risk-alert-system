/**
 * gps.js — ติดตามตำแหน่งผู้ใช้แบบเรียลไทม์
 * รองรับโหมดจำลอง (?mock=1) สำหรับทดสอบโดยไม่ต้องออกไปข้างนอกจริง
 */

const GPS = (() => {
  let watchId = null;
  let mockTimer = null;

  const ERROR_MESSAGES = {
    1: "คุณไม่ได้อนุญาตให้เข้าถึงตำแหน่ง — เปิดสิทธิ์ Location ในการตั้งค่าเบราว์เซอร์แล้วรีเฟรชหน้า",
    2: "หาตำแหน่งไม่ได้ — ตรวจสอบว่าเปิด GPS แล้วและอยู่ในที่โล่ง",
    3: "หาตำแหน่งนานเกินไป (timeout) — กำลังลองใหม่...",
  };

  function isMockMode() {
    return new URLSearchParams(location.search).get("mock") === "1";
  }

  /**
   * เริ่มติดตามตำแหน่ง
   * onUpdate(lat, lng, accuracyM), onError(messageThai)
   */
  function start(onUpdate, onError) {
    if (isMockMode()) {
      startMock(onUpdate);
      return;
    }
    if (!("geolocation" in navigator)) {
      onError("เบราว์เซอร์นี้ไม่รองรับการหาตำแหน่ง (Geolocation)");
      return;
    }
    watchId = navigator.geolocation.watchPosition(
      (pos) => onUpdate(pos.coords.latitude, pos.coords.longitude, pos.coords.accuracy),
      (err) => onError(ERROR_MESSAGES[err.code] || `เกิดข้อผิดพลาด: ${err.message}`),
      { enableHighAccuracy: true, maximumAge: 1000, timeout: 15000 }
    );
  }

  function stop() {
    if (watchId !== null) navigator.geolocation.clearWatch(watchId);
    if (mockTimer !== null) clearInterval(mockTimer);
    watchId = mockTimer = null;
  }

  /**
   * โหมดจำลอง: ขับผ่านจุดเสี่ยงจริงจุดแรกที่ระดับ high
   * เริ่มห่าง ~1.5 กม. แล้ววิ่งเข้าหา-ผ่านจุดนั้นด้วยความเร็ว ~40 กม./ชม.
   */
  function startMock(onUpdate) {
    const target = RiskPoints.all().find((p) => p.level === "high") || RiskPoints.all()[0];
    if (!target) return;

    const START_OFFSET_DEG = 0.0135; // ≈ 1.5 กม. ทางทิศใต้ของจุดเสี่ยง
    const SPEED_MPS = 11; // ≈ 40 กม./ชม.
    const TICK_MS = 1000;
    const stepDeg = (SPEED_MPS * (TICK_MS / 1000)) / 111320;

    let lat = target.lat - START_OFFSET_DEG;
    const lng = target.lng;

    console.log(`[MOCK] จำลองขับผ่านจุดเสี่ยง: ${target.road} (${target.id})`);
    onUpdate(lat, lng, 10);
    mockTimer = setInterval(() => {
      lat += stepDeg; // วิ่งขึ้นเหนือผ่านจุดเสี่ยง
      onUpdate(lat, lng, 10);
      if (lat > target.lat + START_OFFSET_DEG) {
        clearInterval(mockTimer);
        console.log("[MOCK] จบเส้นทางจำลอง");
      }
    }, TICK_MS);
  }

  return { start, stop, isMockMode };
})();
