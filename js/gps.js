/** gps.js — ติดตามตำแหน่งผู้ใช้แบบเรียลไทม์ */

const GPS = (() => {
  let watchId = null;
  let mockTimer = null;
  let plannedRoute = null; // เส้นทางจำลอง (memoized) — [{lat,lng}] รวมจุดตั้งต้น/สิ้นสุด

  // เส้นทางถนนจริง (สร้างจาก OSRM) ให้รถวิ่งตามเลนถนนตลอด ไม่ตัดข้ามอาคาร
  const MOCK_ROUTE_URL = window.MOCK_ROUTE_URL || "data/mock_route.geojson";

  // สำรอง: ถ้าโหลดไฟล์เส้นทางไม่ได้ ค่อยร้อยคลัสเตอร์เป็นเส้นตรงแทน
  const MOCK_ROUTE_IDS = ["zone_431", "zone_440", "zone_455"];

  // คลัสเตอร์ที่ "ยกเว้นเฉพาะโหมดจำลอง" — ใส่ id วงที่อยู่คนละฝั่งเลน/แรมป์ ที่รถไม่ได้ขับผ่านจริง
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

  /** เริ่มติดตามตำแหน่ง */
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
      (pos) => {
        const c = pos.coords;
        // coords.speed เป็น m/s และเป็น null ได้บ่อย (โน้ตบุ๊ก/Android บางรุ่น)
        const speedKmh = c.speed === null || c.speed === undefined ? null : c.speed * 3.6;
        onUpdate(c.latitude, c.longitude, c.accuracy, c.heading ?? null, speedKmh);
      },
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

  /** ต่อเส้นทางอัตโนมัติแบบ nearest-neighbor เผื่อชุดจุดที่กำหนดไว้ไม่มีในข้อมูล */
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

  /** โหลดเส้นทางถนนจริงจากไฟล์ GeoJSON (LineString) มาเป็นเส้นทางจำลอง */
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

  /** ระยะทางที่วิ่งได้ ณ วินาทีที่ t — ออกตัวและเบรกจริงแบบรถยนต์ ไม่ใช่ความเร็วคงที่ทันที */
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

  /** โหมดจำลอง: ขับตามเส้นทางถนนจริงด้วยความเร็วสมจริง */
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

    // ความเร็วเริ่มต้นตั้งต่อหน้าได้ด้วย window.MOCK_KMH · ?kmh= ใน URL ชนะเสมอ
    const defaultKmh = Number(window.MOCK_KMH) || 80;
    const kmh = Math.max(10, Math.min(240, Number(param("kmh", defaultKmh)) || defaultKmh));
    // ตัวคูณความเร็วการเล่น — ย่นเวลาให้ดูจบไว โดยที่ความเร็วรถบนแผงยังเป็นค่าจริง
    // แยกจาก kmh เพราะถ้าเร่ง kmh แทน แผงจะโชว์ 300 กม./ชม. ซึ่งไม่ใช่ความเร็วที่ควรสาธิต
    const defaultX = Number(window.MOCK_SPEEDUP) || 1;
    const SPEEDUP = Math.max(1, Math.min(30, Number(param("x", defaultX)) || defaultX));
    // เริ่มกลางเส้นทางได้ด้วย ?start=<กิโลเมตร> — ไว้กระโดดไปดูช่วงใกล้จุดเสี่ยงโดยไม่ต้องรอ
    const START_M = Math.max(0, Math.min(total - 50, Number(param("start", 0)) * 1000 || 0));
    const cruise = kmh / 3.6; // m/s
    const ACCEL_MS2 = 2.0; // อัตราเร่ง/หน่วงของรถยนต์ทั่วไป (0-100 กม./ชม. ราว 14 วิ)
    const TICK_MS = 100; // 10 Hz เท่าที่สั่งโมดูล u-blox M10 ไว้จริง

    // เวลารวมโดยประมาณ (ช่วงเร่ง+เบรกทำให้ช้ากว่าวิ่งความเร็วคงที่เล็กน้อย)
    const durationS = (total - START_M) / cruise + cruise / ACCEL_MS2;
    console.log(
      `[MOCK] เส้นทางจำลอง ${(total / 1000).toFixed(2)} กม. · ${kmh} กม./ชม. · ~${Math.round(durationS)} วิ` +
        (SPEEDUP > 1 ? ` · เล่นเร็ว ${SPEEDUP}× = ดูจบใน ~${Math.round(durationS / SPEEDUP)} วิ` : "") +
        ` (ปรับด้วย ?kmh= และ ?x=)`
    );

    // ทิศของแต่ละเซกเมนต์ = COG ที่ตัวรับจริงจะรายงานตอนวิ่งอยู่ช่วงนั้น
    const segCourse = [];
    for (let i = 0; i < verts.length - 1; i++) {
      segCourse.push(bearingDegrees(verts[i].lat, verts[i].lng, verts[i + 1].lat, verts[i + 1].lng));
    }

    // จำลองสัญญาณรบกวนของ COG จริง: สั่นปกติ + สัญญาณสะท้อนตึกเป็นครั้งคราว
    // ปิดได้ด้วย ?noise=0 — ถ้าปิด ค่าที่ส่งจะเป็นทิศของถนนเป๊ะ ๆ ซึ่งไม่เหมือนของจริง
    const NOISE_ON = param("noise", window.MOCK_NOISE === false ? "0" : "1") !== "0";
    const COURSE_SIGMA_DEG = 2.5;
    const SPIKE_CHANCE = 0.012;
    const SPIKE_SIGMA_DEG = 60;
    function gauss(sigma) {
      const u = Math.max(1e-9, Math.random());
      return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random()) * sigma;
    }
    function noisyCourse(trueDeg) {
      // ทิศจริงของถนนเก็บไว้ให้แผงตัวเลขเทียบว่าหลังกรองแล้วเหลือคลาดเท่าไร
      window.MOCK_TRUE_COURSE = trueDeg;
      if (!NOISE_ON) return trueDeg;
      const spike = Math.random() < SPIKE_CHANCE;
      window.MOCK_SPIKE = spike;
      return ((trueDeg + gauss(spike ? SPIKE_SIGMA_DEG : COURSE_SIGMA_DEG)) % 360 + 360) % 360;
    }

    // สถานการณ์ทดสอบ beep (?scenario=brake|accel) — โปรไฟล์ความเร็วกำหนดเองรอบจุดเสี่ยงจุดเดียว
    // ค่าของแต่ละสถานการณ์ตั้งในหน้า HTML (window.MOCK_SCENARIOS) เพราะผูกกับเส้นทางของหน้านั้น
    const scenario = (window.MOCK_SCENARIOS || {})[param("scenario", "")];
    if (scenario) {
      runScenario(scenario);
      return;
    }

    /** พิกัด ณ ระยะ d เมตรตามเส้นทาง + index ของเซกเมนต์ (ไว้หยิบทิศ COG) */
    function pointAt(d) {
      let i = 0;
      while (i < seg.length - 1 && d > seg[i]) { d -= seg[i]; i++; }
      const f = seg[i] ? Math.min(1, d / seg[i]) : 0;
      return {
        lat: verts[i].lat + (verts[i + 1].lat - verts[i].lat) * f,
        lng: verts[i].lng + (verts[i + 1].lng - verts[i].lng) * f,
        i,
      };
    }

    /** ล่วงหน้าทั้งสถานการณ์ทุก 0.05 วิ: [{ t, s, v, phase }] — s = ระยะตามเส้นทาง (ม.), v = ม./วิ */
    function scenarioTimeline(sc) {
      const DT = 0.05;
      const cruise = sc.fromKmh / 3.6;
      let s = Math.max(0, sc.targetM - sc.startBeforeM);
      const endS = Math.min(total, sc.targetM + sc.endAfterM);
      let v = cruise, t = 0, phase = "cruise", hold = 0;
      const out = [{ t, s, v, phase }];
      while (s < endS && t < 900) {
        let a = 0;
        // ถึงระยะที่กำหนด (วัดตามเส้นทางถึงจุดเสี่ยง) -> เริ่มเบรก/เร่ง
        if (phase === "cruise" && sc.targetM - s <= sc.triggerM) phase = sc.kind;
        if (phase === "brake") {
          a = -sc.decel;
          if (v + a * DT <= 0) { v = 0; a = 0; phase = "stopped"; hold = sc.holdS; }
        } else if (phase === "stopped") {
          hold -= DT;
          if (hold <= 0) phase = "go";
        } else if (phase === "go") {
          a = sc.accel;
          if (v + a * DT >= cruise) { v = cruise; a = 0; phase = "resume"; }
        } else if (phase === "accel") {
          a = sc.accel;
          if (v + a * DT >= sc.toKmh / 3.6) { v = sc.toKmh / 3.6; a = 0; phase = "fast"; }
        }
        v = Math.max(0, v + a * DT);
        s += v * DT;
        t += DT;
        out.push({ t, s, v, phase });
      }
      return { DT, out };
    }

    function runScenario(sc) {
      // ค่าเริ่มต้นเล่นเวลาจริง (1×) ให้ได้ยินจังหวะ beep ตรงกับที่รถจริงจะได้ยิน · ?x= ยังเร่งได้
      const x = Math.max(1, Math.min(30, Number(param("x", 1)) || 1));
      const { DT, out } = scenarioTimeline(sc);
      window.MOCK_SCENARIO = { ...sc, phase: out[0].phase };
      console.log(`[MOCK] สถานการณ์ "${sc.title}" · ${Math.round(out[out.length - 1].t)} วิ` +
                  (x > 1 ? ` · เล่นเร็ว ${x}×` : ""));
      const emit = (k, phaseOverride) => {
        const p = out[k];
        const pos = pointAt(p.s);
        window.MOCK_ELAPSED_S = p.t;
        window.MOCK_SCENARIO.phase = phaseOverride || p.phase;
        // ความเร็วจริง ณ ขณะนั้น (ไม่ใช่ค่าเฉลี่ย 1 วิ) — ตอนจอดส่ง 0 เหมือนตัวรับ GPS
        onUpdate(pos.lat, pos.lng, 8, noisyCourse(segCourse[pos.i]), p.v * 3.6);
      };
      const t0 = performance.now();
      emit(0);
      mockTimer = setInterval(() => {
        const k = Math.floor((((performance.now() - t0) / 1000) * x) / DT);
        if (k >= out.length - 1) {
          emit(out.length - 1, "done");
          clearInterval(mockTimer);
          mockTimer = null;
          console.log("[MOCK] จบสถานการณ์");
          return;
        }
        emit(k);
      }, TICK_MS);
    }

    const startedAt = performance.now();
    // ถ้าเริ่มกลางทาง ให้หมุดไปโผล่ตรงนั้นเลย ไม่ต้องเริ่มจากต้นเส้นทาง
    (function seedStart() {
      let d = START_M, k = 0;
      while (k < seg.length - 1 && d > seg[k]) { d -= seg[k]; k++; }
      const f = seg[k] ? d / seg[k] : 0;
      onUpdate(verts[k].lat + (verts[k + 1].lat - verts[k].lat) * f,
               verts[k].lng + (verts[k + 1].lng - verts[k].lng) * f,
               8, noisyCourse(segCourse[k]), 0);
    })();
    mockTimer = setInterval(() => {
      // เวลาที่ "รถ" เดินทางไปแล้ว = เวลาจริง × ตัวคูณ — แผงตัวเลขอ่านค่านี้ไปแสดง
      const elapsedS = ((performance.now() - startedAt) / 1000) * SPEEDUP;
      window.MOCK_ELAPSED_S = elapsedS;
      let dist = START_M + distanceAtTime(elapsedS, cruise, ACCEL_MS2, total - START_M);
      if (dist >= total) {
        onUpdate(verts[verts.length - 1].lat, verts[verts.length - 1].lng, 8,
                 noisyCourse(segCourse[segCourse.length - 1]), 0);
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
      // ความเร็ว ณ วินาทีนั้น (หาจากระยะที่วิ่งได้ในช่วง 1 วิ) — ให้ speed gate ของ
      const dNext = distanceAtTime(elapsedS + 1, cruise, ACCEL_MS2, total - START_M);
      const speedKmh =
        Math.max(0, dNext - distanceAtTime(elapsedS, cruise, ACCEL_MS2, total - START_M)) * 3.6;
      // ความแม่นยำแกว่งเล็กน้อยให้เหมือนจริง
      onUpdate(lat, lng, 6 + Math.random() * 6, noisyCourse(segCourse[i]), speedKmh);
    }, TICK_MS);
  }

  return { start, stop, isMockMode, getMockRoute, prepare, mockExcludes: () => MOCK_EXCLUDE_IDS };
})();
