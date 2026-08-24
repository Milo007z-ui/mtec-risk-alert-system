/**
 * gps.js — ติดตามตำแหน่งผู้ใช้แบบเรียลไทม์
 * รองรับโหมดจำลอง (?mock=1) สำหรับทดสอบโดยไม่ต้องออกไปข้างนอกจริง
 */

const GPS = (() => {
  let watchId = null;
  let mockTimer = null;
  let plannedRoute = null; // เส้นทางจำลอง (memoized) — [{lat,lng}] รวมจุดตั้งต้น/สิ้นสุด

  // เส้นทางถนนจริง (สร้างจาก OSRM) ให้รถวิ่งตามเลนถนนตลอด ไม่ตัดข้ามอาคาร
  // วิ่งบนถนน "แยกสาครเกษม - คลองมะเดื่อ" (สมุทรสาคร ~6.2 กม.) ทิศทางเดียวไม่สวนเลน
  // ผ่านคลัสเตอร์ 7 วงในรัศมีเตือน ครบทั้งสามระดับ: ต่ำ -> ปานกลาง -> สูง (zone_455)
  // เส้นทางเดิม "บางปะอิน - แขวงรามอินทรา" เก็บไว้ที่ data/mock_route_bangpain.geojson
  // (เส้นนั้นเหลือแค่ระดับต่ำกับปานกลางหลังเปลี่ยนมาใช้ชุดข้อมูล 3 ปี)
  const MOCK_ROUTE_URL = "data/mock_route.geojson";

  // สำรอง: ถ้าโหลดไฟล์เส้นทางไม่ได้ ค่อยร้อยคลัสเตอร์เป็นเส้นตรงแทน
  // (id ตามรอบ calibration v2569-r1-3y — เรียงตามลำดับบนถนน)
  const MOCK_ROUTE_IDS = ["zone_431", "zone_440", "zone_455"];

  // คลัสเตอร์ที่ "ยกเว้นเฉพาะโหมดจำลอง" — ใส่ id วงที่อยู่คนละฝั่งเลน/แรมป์ ที่รถไม่ได้ขับผ่านจริง
  // (รอบ v2568-r10 ยังไม่พบวงที่ต้องยกเว้น)
  const MOCK_EXCLUDE_IDS = [];

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

  /**
   * โหลดเส้นทางถนนจริงจากไฟล์ GeoJSON (LineString) มาเป็นเส้นทางจำลอง
   * เรียกครั้งเดียวตอนเริ่มแอป (มีผลเฉพาะโหมดจำลอง) — ถ้าล้มเหลวเงียบๆ แล้วใช้ fallback
   */
  async function prepare() {
    if (!isMockMode() || plannedRoute) return;
    try {
      // ต่อ query กันเบราว์เซอร์ cache เส้นทางเก่า (ไฟล์อัปเดตบ่อยระหว่างทดสอบ)
      const resp = await fetch(`${MOCK_ROUTE_URL}?_=${Date.now()}`, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const gj = await resp.json();
      const line = gj.features.find((f) => f.geometry.type === "LineString");
      const coords = line && line.geometry.coordinates;
      if (coords && coords.length >= 2) {
        plannedRoute = coords.map(([lng, lat]) => ({ lat, lng })); // GeoJSON = [lng,lat]
        console.log(`[MOCK] โหลดเส้นทางถนนจริง ${plannedRoute.length} จุดพิกัด (${MOCK_ROUTE_URL})`);
      }
    } catch (err) {
      console.warn(`[MOCK] โหลดเส้นทางถนนไม่ได้ (${err.message}) — ใช้เส้นทางสำรองแบบลากจุดเสี่ยง`);
    }
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
   * ระยะทางที่วิ่งได้ ณ วินาทีที่ t — ออกตัวและเบรกจริงแบบรถยนต์ ไม่ใช่ความเร็วคงที่ทันที
   * ช่วงออกตัวเร่งด้วย ACCEL_MS2 จนถึงความเร็วเดินทาง แล้วคงที่ และชะลอลงก่อนถึงปลายทาง
   * (ทำให้หมุดไม่กระโดดจากนิ่งเป็นความเร็วเต็มในเฟรมเดียว ดูเป็นการขับจริง)
   */
  function distanceAtTime(t, cruise, accel, total) {
    const rampS = cruise / accel; // เวลาที่ใช้เร่ง/เบรก
    const rampM = (cruise * cruise) / (2 * accel); // ระยะที่ใช้เร่ง/เบรก
    // เส้นทางสั้นเกินกว่าจะเร่งถึงความเร็วเดินทาง — เร่งครึ่งทางแล้วเบรกครึ่งทาง
    if (2 * rampM >= total) {
      const halfT = Math.sqrt(total / accel);
      if (t <= halfT) return 0.5 * accel * t * t;
      const td = Math.min(t - halfT, halfT);
      return total / 2 + accel * halfT * td - 0.5 * accel * td * td;
    }
    const cruiseS = (total - 2 * rampM) / cruise;
    if (t <= rampS) return 0.5 * accel * t * t;
    if (t <= rampS + cruiseS) return rampM + cruise * (t - rampS);
    const td = Math.min(t - rampS - cruiseS, rampS);
    return total - rampM + cruise * td - 0.5 * accel * td * td;
  }

  /**
   * โหมดจำลอง: ขับตามเส้นทางถนนจริงด้วยความเร็วสมจริง
   * ค่าเริ่มต้น 80 กม./ชม. (เท่าเพดานความเร็วที่โมเดลใช้กับสายทางประเภทนี้)
   * ปรับได้ด้วย ?kmh=<ความเร็ว> เช่น ?kmh=100 ขับเร็วขึ้น หรือ ?kmh=40 ดูจังหวะเตือนแบบช้าๆ
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

    const kmh = Math.max(10, Math.min(160, Number(param("kmh", 80)) || 80));
    const cruise = kmh / 3.6; // m/s
    const ACCEL_MS2 = 2.0; // อัตราเร่ง/หน่วงของรถยนต์ทั่วไป (0-100 กม./ชม. ราว 14 วิ)
    const TICK_MS = 200; // ใกล้เคียงจังหวะที่ GPS จริงส่งตำแหน่ง (1-5 ครั้งต่อวินาที)

    // เวลารวมโดยประมาณ (ช่วงเร่ง+เบรกทำให้ช้ากว่าวิ่งความเร็วคงที่เล็กน้อย)
    const durationS = total / cruise + cruise / ACCEL_MS2;
    console.log(
      `[MOCK] เส้นทางจำลอง ${(total / 1000).toFixed(2)} กม. · ${kmh} กม./ชม. · ~${Math.round(durationS)} วิ` +
        ` (ปรับด้วย ?kmh=)`
    );

    const startedAt = performance.now();
    onUpdate(verts[0].lat, verts[0].lng, 8);
    mockTimer = setInterval(() => {
      const elapsedS = (performance.now() - startedAt) / 1000;
      let dist = distanceAtTime(elapsedS, cruise, ACCEL_MS2, total);
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

  return { start, stop, isMockMode, getMockRoute, prepare, mockExcludes: () => MOCK_EXCLUDE_IDS };
})();
