/** alert.js — ตรวจจับการเข้าใกล้จุดเสี่ยงและแจ้งเตือน (เสียง + ภาพ) */

const AlertSystem = (() => {
  // หน้าเว็บตั้ง window.ALERT_RADIUS_M / window.EXIT_RADIUS_M ไว้ก่อนโหลดสคริปต์นี้ได้
  const ALERT_RADIUS_M = window.ALERT_RADIUS_M || 500;
  const EXIT_RADIUS_M = window.EXIT_RADIUS_M || 600; // hysteresis กันเด้งเข้าออกตรงขอบรัศมี
  const REALERT_MS = 5 * 60 * 1000;

  // id จุดเสี่ยง -> ระยะต่ำสุดที่เคยวัดได้ ใช้ดูว่าขับผ่านจุดไปแล้วหรือยัง
  const closestSeen = new Map();

  // ความเร็วรถ ใช้เลือกระยะเริ่ม beep — Geolocation API ไม่ได้ส่ง coords.speed มาที่นี่
  const speedTracker = createSpeedTracker(15);
  let lastMovingSpeedKmh = null; // ความเร็วล่าสุดตอนที่รถยังเคลื่อนที่จริง
  // รถจอดนิ่งเกิน 3 วิ -> หยุด beep (เสียงพูดไม่เกี่ยว)
  const parked = createParkedDetector();

  // มุมที่ถือว่า "ข้างหน้า" นับจากทิศที่รถมุ่งหน้า (องศา ไปทางละเท่านี้)
  const HEADING_WINDOW_DEG = (() => {
    const q = Number(new URLSearchParams(location.search).get("heading"));
    return Number.isFinite(q) && q > 0 ? q : window.HEADING_WINDOW_DEG || FRONT_CONE_DEG;
  })();

  // ทิศหลัก: COG จากตัวรับ GPS (คำนวณจากเวกเตอร์ความเร็ว ไม่ใช่ผลต่างพิกัด)
  const course = createCourseTracker();
  // ทิศสำรอง: ประมาณจากพิกัดที่ขยับไป ใช้เมื่อเครื่องไม่ให้ coords.heading (พบบ่อยบน
  const heading = createHeadingTracker(15);
  let headingSource = null; // "COG" / "พิกัด" / null — ใช้ใน log และหมุนหมุด

  // ภาพนิ่งของรอบล่าสุด ให้แผงตัวเลขบนแผนที่อ่านไปแสดง (ไม่มีผลกับการตัดสินใจ)
  let lastTelemetry = {
    rawCourse: null, heading: null, trueCourse: null,
    speedKmh: null, inRadius: { off: 0, c90: 0, c30: 0 },
    beep: null, beepFrom: null,
  };

  const LEVEL_RANK = { low: 1, medium: 2, high: 3 };

  // id จุดเสี่ยง -> { lastAlertAt } (มี entry = ยังอยู่ในสถานะ "เตือนแล้ว")
  const alerted = new Map();

  // ระดับของเสียงเตือนที่กำลังเล่นอยู่ (null = ว่าง พร้อมเตือนจุดใหม่)
  let speakingLevel = null;
  let speakSeq = 0;

  // ข้อความเตือน (สาเหตุ + คำแนะนำ) สร้างโดยกติกา Dynamic Alert ใน riskrules.js
  function showBanner(text, level) {
    const banner = document.getElementById("alert-banner");
    banner.textContent = text;
    banner.className = `alert-banner alert-${level}`;
    banner.classList.remove("hidden");
    clearTimeout(showBanner._timer);
    showBanner._timer = setTimeout(() => banner.classList.add("hidden"), 10000);
  }

  /** เรียกทุกครั้งที่ตำแหน่ง GPS อัปเดต */
  function onPositionUpdate(lat, lng, courseDeg = null, gpsSpeedKmh = null) {
    const now = Date.now();

    // ความเร็วสำหรับ speed gate ของ COG — ใช้ค่าจาก GPS ก่อน ถ้าไม่มีค่อยประมาณจากพิกัด
    const measuredSpeed = speedTracker.update(lat, lng, now);
    const speedForGate = gpsSpeedKmh !== null && gpsSpeedKmh !== undefined
      ? gpsSpeedKmh
      : measuredSpeed;

    const cogDeg = course.update(courseDeg, speedForGate, now);
    const fallbackDeg = heading.update(lat, lng);
    const headingDeg = cogDeg !== null ? cogDeg : fallbackDeg;
    headingSource = cogDeg !== null ? "COG" : (fallbackDeg !== null ? "พิกัด" : null);
    // visible() = จุดที่ผ่านตัวกรองบนแผนที่ — เตือนเฉพาะสิ่งที่ผู้ใช้เลือกดูอยู่
    const nearby = findNearbyPoints(lat, lng, RiskPoints.visible(), EXIT_RADIUS_M);
    const nearbyIds = new Set(nearby.map((n) => n.point.id));

    // จุดที่เคยเตือนแล้วแต่ตอนนี้ออกนอกรัศมี EXIT ไปแล้ว -> รีเซ็ตให้เตือนใหม่ได้
    for (const id of alerted.keys()) {
      if (!nearbyIds.has(id)) alerted.delete(id);
    }
    for (const id of closestSeen.keys()) {
      if (!nearbyIds.has(id)) closestSeen.delete(id);
    }

    // จุดที่ขับผ่านไปแล้ว/อยู่ด้านหลัง ไม่ต้องเตือน (ยังไม่รู้ทิศ = เตือนไว้ก่อน)
    const ahead = nearby.filter(({ point }) =>
      isAhead(headingDeg, lat, lng, point.lat, point.lng, HEADING_WINDOW_DEG)
    );

    // รถจอด/คลานช้า -> คงความเร็วเดิมไว้ ไม่งั้นระยะเริ่ม beep จะร่วงลงไปที่ขั้นต่ำสุด
    if (speedForGate !== null && speedForGate >= SPEED_HOLD_MIN_KMH) {
      lastMovingSpeedKmh = speedForGate;
    }

    // beep บอกระยะ — คิดแยกจาก cooldown ของเสียงพูด อัปเดตทุกรอบจนกว่าจะขับผ่านไป
    // ยังคิดจังหวะทุกรอบ (ให้ closestSeen ตามระยะจริงต่อไป) แต่ถ้ารถจอดนิ่งเกิน 3 วิ ให้เงียบ
    const isParked = parked.update(speedForGate, now);
    const movingPattern = beepPatternFor(ahead, closestSeen, lastMovingSpeedKmh);
    const beepPattern = isParked ? null : movingPattern;
    TTS.setBeepPattern(beepPattern);

    // นับจุดในระยะเตือนของกรวยแต่ละความกว้าง — ไว้เทียบให้เห็นว่าการกรองตัดอะไรออก
    const within = nearby.filter(({ distance }) => distance <= ALERT_RADIUS_M);
    const countCone = (deg) =>
      within.filter(({ point }) =>
        isAhead(headingDeg, lat, lng, point.lat, point.lng, deg)
      ).length;
    lastTelemetry = {
      rawCourse: courseDeg,
      heading: headingDeg,
      trueCourse: typeof window.MOCK_TRUE_COURSE === "number" ? window.MOCK_TRUE_COURSE : null,
      speedKmh: speedForGate,
      inRadius: { off: within.length, c90: countCone(90), c30: countCone(HEADING_WINDOW_DEG) },
      beep: beepPattern,
      parked: isParked, // true = รถจอดนิ่งเกิน 3 วิ beep จึงเงียบ (แผงตัวเลขใช้บอกเหตุผล)
      // ความเร็วที่ใช้คิดระยะเริ่ม beep (ค้างค่าล่าสุดที่ ≥ 5 กม./ชม. ตอนรถจอด) + ระยะที่ได้
      beepSpeedKmh: lastMovingSpeedKmh,
      beepStartM: beepStartM(lastMovingSpeedKmh),
      // จุดที่ทำให้ beep ร้องอยู่ตอนนี้ — ไว้ไล่หาเวลาที่เสียงไม่หยุดอย่างที่คาด
      beepFrom: beepPattern === null ? null : (() => {
        const r = beepStartM(lastMovingSpeedKmh);
        const inBeep = ahead.filter(({ distance }) => distance <= r);
        if (!inBeep.length) return null;
        const near = inBeep.reduce((a, b) => (b.distance < a.distance ? b : a));
        return `${near.point.id} ${Math.round(near.distance)} ม.`;
      })(),
    };


    // เตือนเฉพาะจุดที่ใกล้ที่สุดที่เข้าเงื่อนไข (กันพูดรัวเมื่อหลายจุดติดกัน)
    for (const { point, distance } of ahead) {
      if (distance > ALERT_RADIUS_M) continue;
      const state = alerted.get(point.id);
      if (state && now - state.lastAlertAt < REALERT_MS) continue;

      // ยังพูดจุดก่อนหน้าไม่จบ — รอก่อน เว้นแต่จุดนี้ระดับสูงกว่า จึงตัดเข้าแทนได้
      if (speakingLevel && LEVEL_RANK[point.level] <= LEVEL_RANK[speakingLevel]) break;

      alerted.set(point.id, { lastAlertAt: now });
      // log ไว้ตรวจลำดับการเตือน: บอกจุดที่เตือน + จุดอื่นที่อยู่ในระยะขณะนั้น
      console.log(
        `[ALERT] ${point.level} ${point.id} ที่ ${distance.toFixed(0)} ม. | ` +
          `ทิศรถ ${headingDeg === null ? "ยังไม่รู้" : `${headingDeg.toFixed(0)}° (${headingSource})`} ` +
          `(กรอง ±${HEADING_WINDOW_DEG}°) | ในระยะ ${EXIT_RADIUS_M} ม. ตอนนี้: ` +
          nearby
            .map((n) => `${n.point.id} ${n.distance.toFixed(0)}ม.${alerted.has(n.point.id) ? "*" : ""}`)
            .join(", ") +
          " (* = เตือนไปแล้ว)"
      );
      const msg = RiskRules.buildAlertMessage(point, distance);
      showBanner("🔊 " + msg, point.level);
      // beep นำสองครั้งก่อน แล้วค่อยพูดข้อความ (Botnoi -> Google -> Web Speech)
      speakingLevel = point.level;
      const seq = ++speakSeq;
      TTS.playLeadBeep()
        // ถ้าระหว่างเล่น beep นำมีจุดที่เร่งด่วนกว่าตัดเข้ามา ให้ทิ้งประโยคนี้ไปเลย
        .then(() => (seq === speakSeq ? TTS.speak(msg) : true))
        .then((spoken) => {
          if (!spoken) showBanner("⚠️ " + msg, point.level);
        })
        .finally(() => {
          if (seq === speakSeq) speakingLevel = null; // ปลดล็อกเฉพาะชุดล่าสุด
        });
      break;
    }

    updateNearestInfo(lat, lng);
  }

  /** แสดงระยะจุดเสี่ยงที่ใกล้ที่สุดใน status bar ตลอดเวลา */
  function updateNearestInfo(lat, lng) {
    const el = document.getElementById("nearest-info");
    let best = null;
    for (const p of RiskPoints.visible()) {
      const d = haversineMeters(lat, lng, p.lat, p.lng);
      if (!best || d < best.d) best = { p, d };
    }
    if (!best) {
      el.textContent = "ไม่มีจุดเสี่ยงตามตัวกรองที่เลือก";
      return;
    }
    el.textContent =
      best.d < 10000
        ? `จุดเสี่ยงใกล้สุด: ${best.p.road_label || best.p.road} ${(best.d / 1000).toFixed(2)} กม.`
        : "ไม่มีจุดเสี่ยงในระยะ 10 กม.";
  }

  return {
    onPositionUpdate,
    ALERT_RADIUS_M,
    HEADING_WINDOW_DEG,
    telemetry: () => lastTelemetry,
    // ทิศที่ใช้กรองอยู่จริง (null = ยังไม่รู้ทิศ = ไม่กรอง) — map.js ใช้หมุนหมุด
    heading: () => (course.get() !== null ? course.get() : heading.get()),
    headingSource: () => headingSource,
  };
})();
