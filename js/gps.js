/**
 * gps.js — ติดตามตำแหน่งผู้ใช้แบบเรียลไทม์
 * รองรับโหมดจำลอง (?mock=1) สำหรับทดสอบโดยไม่ต้องออกไปข้างนอกจริง
 */

const GPS = (() => {
  let watchId = null;
  let mockTimer = null;
  let plannedRoute = null; // เส้นทางจำลอง (memoized) — [{lat,lng}] รวมจุดตั้งต้น/สิ้นสุด

  // ชุดจุดเสี่ยงจริงที่เรียงต่อกันเป็น "ถนน" เดียว (ทางเหนือ ถ.รามอินทรา-บางพลี)
  // ขับตรงขึ้นเหนือ ~15 กม. ผ่านจุดเสี่ยงระดับสูงหลายจุดติดกัน
  const MOCK_ROUTE_IDS = ["zone_25", "zone_29", "zone_58", "zone_48", "zone_69"];

  const ERROR_MESSAGES = {
    1: "คุณไม่ได้อนุญาตให้เข้าถึงตำแหน่ง — เปิดสิทธิ์ Location ในการตั้งค่าเบราว์เซอร์แล้วรีเฟรชหน้า",
    2: "หาตำแหน่งไม่ได้ — ตรวจสอบว่าเปิด GPS แล้วและอยู่ในที่โล่ง",
    3: "หาตำแหน่งนานเกินไป (timeout) — กำลังลองใหม่...",
  };

  function isMockMode() {
    return new URLSearchParams(location.search).get("mock") === "1";
  }

  function param(name, def) {
    const v = new URLSearchParams(location.search).get(name);
    return v === null ? def : v;
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

  /** เลือกจุดเสี่ยงจริงมาร้อยเป็นเส้นทางขับ (fallback: ต่ออัตโนมัติจากจุด high) */
  function buildWaypoints() {
    const all = RiskPoints.all();
    const byId = new Map(all.map((p) => [p.id, p]));
    const wps = MOCK_ROUTE_IDS.map((id) => byId.get(id)).filter(Boolean);
    return wps.length >= 2 ? wps : autoChain(all);
  }

  /**
   * ต่อเส้นทางอัตโนมัติแบบ nearest-neighbor เผื่อชุดจุดที่กำหนดไว้ไม่มีในข้อมูล
   * เริ่มจากจุด high จุดแรก แล้วไล่ไปจุดใกล้สุดที่ยังไปในทิศทางเดิม (กันวกไปมา)
   */
  function autoChain(all, N = 4, maxHopM = 5000) {
    const seed = all.find((p) => p.level === "high") || all[0];
    if (!seed) return [];
    const route = [seed];
    const used = new Set([seed.id]);
    let heading = null;
    while (route.length < N) {
      const cur = route[route.length - 1];
      let best = null;
      for (const p of all) {
        if (used.has(p.id)) continue;
        const d = haversineMeters(cur.lat, cur.lng, p.lat, p.lng);
        if (d > maxHopM) continue;
        const vy = p.lat - cur.lat;
        const vx = p.lng - cur.lng;
        const mag = Math.hypot(vx, vy) || 1e-9;
        let score = d;
        if (heading) {
          const dot = (vx * heading[0] + vy * heading[1]) / mag;
          if (dot < 0.3) continue; // ต้องมุ่งไปข้างหน้าเป็นหลัก
          score = d * (1.5 - dot);
        }
        if (!best || score < best.score) best = { score, p, h: [vx / mag, vy / mag] };
      }
      if (!best) break;
      route.push(best.p);
      used.add(best.p.id);
      heading = best.h;
    }
    return route;
  }

  /** จุดที่ยื่นออกจาก `from` ไปด้านตรงข้าม `toward` เป็นระยะ meters (ทางเข้า/ออกก่อนถึงจุดแรก) */
  function leadPoint(from, toward, meters) {
    const cos = Math.cos((from.lat * Math.PI) / 180);
    let mLat = (from.lat - toward.lat) * 111320;
    let mLng = (from.lng - toward.lng) * 111320 * cos;
    const mag = Math.hypot(mLat, mLng) || 1e-9;
    mLat = (mLat / mag) * meters;
    mLng = (mLng / mag) * meters;
    return { lat: from.lat + mLat / 111320, lng: from.lng + mLng / (111320 * cos) };
  }

  /** สร้าง (และ cache) เส้นทางจำลองเต็ม: [ทางเข้า, ...จุดเสี่ยง, ทางออก] */
  function getMockRoute() {
    if (plannedRoute) return plannedRoute;
    const wps = buildWaypoints();
    if (wps.length === 0) return (plannedRoute = []);
    const first = { lat: wps[0].lat, lng: wps[0].lng };
    const last = { lat: wps[wps.length - 1].lat, lng: wps[wps.length - 1].lng };
    const leadIn = wps.length >= 2 ? leadPoint(first, wps[1], 700) : first;
    const leadOut = wps.length >= 2 ? leadPoint(last, wps[wps.length - 2], 700) : last;
    plannedRoute = [leadIn, ...wps.map((p) => ({ lat: p.lat, lng: p.lng })), leadOut];
    return plannedRoute;
  }

  /**
   * โหมดจำลอง: ขับตามเส้นทางที่ร้อยจากจุดเสี่ยงจริงหลายจุด
   * เลื่อนตำแหน่งตามเวลาที่ผ่านไปจริง (interpolate) จึงลื่นไหลและจบภายในเวลาที่กำหนด
   * ปรับจังหวะได้ด้วย ?mockpace=<วินาที/กม.> (ค่าเริ่มต้น 6 → ~15 กม. ราว 90 วิ)
   */
  function startMock(onUpdate) {
    const verts = getMockRoute();
    if (verts.length < 2) return;

    const seg = [];
    let total = 0;
    for (let i = 0; i < verts.length - 1; i++) {
      const d = haversineMeters(verts[i].lat, verts[i].lng, verts[i + 1].lat, verts[i + 1].lng);
      seg.push(d);
      total += d;
    }

    const pace = Number(param("mockpace", 6)); // วินาทีต่อกิโลเมตร
    const durationS = Math.max(45, Math.min(150, (total / 1000) * pace));
    const speed = total / durationS; // m/s (เร่งเวลาให้ดูจบไว แต่ยังลื่น)
    const TICK_MS = 120;

    console.log(
      `[MOCK] เส้นทางจำลอง ${verts.length - 2} จุดเสี่ยง · ${(total / 1000).toFixed(1)} กม. · ~${durationS.toFixed(0)} วิ`
    );

    const startedAt = performance.now();
    onUpdate(verts[0].lat, verts[0].lng, 8);
    mockTimer = setInterval(() => {
      let dist = (speed * (performance.now() - startedAt)) / 1000;
      if (dist >= total) {
        onUpdate(verts[verts.length - 1].lat, verts[verts.length - 1].lng, 8);
        clearInterval(mockTimer);
        mockTimer = null;
        console.log("[MOCK] จบเส้นทางจำลอง");
        return;
      }
      let i = 0;
      while (i < seg.length - 1 && dist > seg[i]) {
        dist -= seg[i];
        i++;
      }
      const t = seg[i] ? dist / seg[i] : 0;
      const lat = verts[i].lat + (verts[i + 1].lat - verts[i].lat) * t;
      const lng = verts[i].lng + (verts[i + 1].lng - verts[i].lng) * t;
      onUpdate(lat, lng, 6 + Math.random() * 6); // ความแม่นยำแกว่งเล็กน้อยให้เหมือนจริง
    }, TICK_MS);
  }

  return { start, stop, isMockMode, getMockRoute };
})();
