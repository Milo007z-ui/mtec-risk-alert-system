/** distance.js — เรขาคณิตบนพื้นโลก: ระยะทาง (Haversine), กรองหยาบด้วย bounding box */

const EARTH_RADIUS_M = 6371000;

/** ระยะทางเป็นเมตรระหว่างสองพิกัด (สูตร Haversine) */
function haversineMeters(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const dLat = toRad(lat2 - lat1);
  const dLon = toRad(lon2 - lon1);
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(toRad(lat1)) * Math.cos(toRad(lat2)) * Math.sin(dLon / 2) ** 2;
  return 2 * EARTH_RADIUS_M * Math.asin(Math.sqrt(a));
}

/** กรองหยาบ: จุดอยู่ในกรอบสี่เหลี่ยมรอบตำแหน่งผู้ใช้หรือไม่ */
function inBoundingBox(userLat, userLon, pointLat, pointLon, radiusMeters) {
  const dLat = radiusMeters / 111320; // 1 องศาละติจูด ≈ 111.32 กม.
  const dLon = radiusMeters / (111320 * Math.cos((userLat * Math.PI) / 180));
  return (
    Math.abs(pointLat - userLat) <= dLat &&
    Math.abs(pointLon - userLon) <= dLon
  );
}

/** หาจุดเสี่ยงทั้งหมดในรัศมี radiusMeters จากตำแหน่งผู้ใช้ */
function findNearbyPoints(userLat, userLon, points, radiusMeters) {
  const nearby = [];
  for (const p of points) {
    if (!inBoundingBox(userLat, userLon, p.lat, p.lng, radiusMeters)) continue;
    const distance = haversineMeters(userLat, userLon, p.lat, p.lng);
    if (distance <= radiusMeters) nearby.push({ point: p, distance });
  }
  nearby.sort((a, b) => a.distance - b.distance);
  return nearby;
}

/** ทิศจากจุดหนึ่งไปอีกจุด เป็นองศา 0-360 (0 = เหนือ, 90 = ตะวันออก) */
function bearingDegrees(lat1, lon1, lat2, lon2) {
  const toRad = (d) => (d * Math.PI) / 180;
  const phi1 = toRad(lat1);
  const phi2 = toRad(lat2);
  const dLon = toRad(lon2 - lon1);
  const y = Math.sin(dLon) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLon);
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/** ผลต่างของสองมุม เอาทางที่สั้นกว่า คืน 0-180 (เช่น 350 กับ 10 ต่างกัน 20 ไม่ใช่ 340) */
function angleDiffDegrees(a, b) {
  const d = Math.abs(a - b) % 360;
  return d > 180 ? 360 - d : d;
}

/** ตัวติดตามทิศที่รถกำลังมุ่งหน้า — คำนวณจากตำแหน่งที่ขยับไปจริง */
function createHeadingTracker(minMoveM = 15) {
  let anchorLat = null;
  let anchorLng = null;
  let heading = null;

  return {
    /** ป้อนตำแหน่งใหม่ คืนทิศล่าสุดที่มั่นใจ (องศา) หรือ null ถ้ายังไม่รู้ */
    update(lat, lng) {
      if (anchorLat === null) {
        anchorLat = lat;
        anchorLng = lng;
        return heading;
      }
      const moved = haversineMeters(anchorLat, anchorLng, lat, lng);
      if (moved >= minMoveM) {
        heading = bearingDegrees(anchorLat, anchorLng, lat, lng);
        anchorLat = lat;
        anchorLng = lng;
      }
      return heading;
    },
    get() {
      return heading;
    },
    reset() {
      anchorLat = anchorLng = heading = null;
    },
  };
}

/** มุมที่ถือว่า "ข้างหน้า" นับจากทิศที่รถมุ่งหน้า (องศา ไปทางละเท่านี้) */
const FRONT_CONE_DEG = 90;

/** ความเร็วต่ำสุดที่ยอมเชื่อค่า COG จากตัวรับ GPS */
const COG_MIN_SPEED_KMH = 5;

/** อายุสูงสุดของค่าทิศที่ค้างไว้ตอนรถจอด — เกินแล้วถือว่าไม่รู้ทิศ */
const COG_HOLD_MAX_MS = 120 * 1000;

/** หน้าต่างเวลาที่ใช้เฉลี่ยทิศ (มิลลิวินาที) — ต้องตรงกับ COURSE_WINDOW_S ใน */
const COURSE_WINDOW_MS = 500;

/** ค่าเฉลี่ยของมุมหลายค่า แบบวงกลม (circular mean) */
function circularMeanDegrees(anglesDeg) {
  if (!anglesDeg || anglesDeg.length === 0) return null;
  if (anglesDeg.length === 1) return ((anglesDeg[0] % 360) + 360) % 360; // เลี่ยงเศษจาก atan2
  let x = 0;
  let y = 0;
  for (const a of anglesDeg) {
    const r = (a * Math.PI) / 180;
    x += Math.cos(r);
    y += Math.sin(r);
  }
  // ความยาวเวกเตอร์ลัพธ์ = ตัวอย่างไปทางเดียวกันแค่ไหน (1 = ตรงกันหมด, 0 = กระจายสุด)
  if (Math.hypot(x, y) / anglesDeg.length < 0.3) return null;
  return ((Math.atan2(y, x) * 180) / Math.PI + 360) % 360;
}

/** ตัวติดตามทิศจากค่า COG ของตัวรับ GPS โดยตรง (ไม่ใช่จากการลบพิกัด) */
function createCourseTracker(
  minSpeedKmh = COG_MIN_SPEED_KMH,
  holdMaxMs = COG_HOLD_MAX_MS,
  windowMs = COURSE_WINDOW_MS
) {
  let course = null;      // ทิศล่าสุดที่เชื่อได้ (last-known-good)
  let updatedAt = 0;
  let samples = [];       // [{ t, deg }] ภายในหน้าต่างเวลาเท่านั้น

  function expire(nowMs) {
    if (course !== null && nowMs - updatedAt > holdMaxMs) course = null;
    return course;
  }

  return {
    /** ป้อน COG + ความเร็วที่ได้จาก GPS รอบนี้ คืนทิศล่าสุดที่เชื่อได้ (องศา) หรือ null */
    update(courseDeg, speedKmh, nowMs = Date.now()) {
      expire(nowMs);
      const usable =
        courseDeg !== null && courseDeg !== undefined && !Number.isNaN(courseDeg) &&
        speedKmh !== null && speedKmh !== undefined && !Number.isNaN(speedKmh) &&
        speedKmh >= minSpeedKmh;
      if (usable) samples.push({ t: nowMs, deg: courseDeg });
      samples = samples.filter((s) => nowMs - s.t <= windowMs);
      if (samples.length === 0) return course; // ไม่มีตัวอย่างที่ใช้ได้ -> ใช้ค่าเดิมค้างไว้
      const mean = circularMeanDegrees(samples.map((s) => s.deg));
      if (mean === null) return course;        // กระจายจนหาทิศกลางไม่ได้ -> ใช้ค่าเดิม
      course = mean;
      updatedAt = nowMs;
      return course;
    },
    get(nowMs = Date.now()) {
      return expire(nowMs);
    },
    reset() {
      course = null;
      updatedAt = 0;
      samples = [];
    },
  };
}

/** ระยะที่ใกล้เกินกว่าจะเชื่อทิศ — ต่ำกว่านี้ให้ผ่านเสมอ ไม่ต้องกรอง */
const HEADING_NEAR_BYPASS_M = 30;

/** จุดนี้อยู่ "ข้างหน้า" รถหรือไม่ */
function isAhead(headingDeg, userLat, userLng, pointLat, pointLng, windowDeg) {
  if (headingDeg === null || headingDeg === undefined) return true;
  if (windowDeg >= 180) return true;
  if (haversineMeters(userLat, userLng, pointLat, pointLng) <= HEADING_NEAR_BYPASS_M) return true;
  const toPoint = bearingDegrees(userLat, userLng, pointLat, pointLng);
  return angleDiffDegrees(headingDeg, toPoint) <= windowDeg;
}

// AASHTO Green Book 7th ed. Table 3-3 — Decision Sight Distance (เมตร), Maneuver E
const DSD_E_M = { 50: 200, 60: 235, 70: 275, 80: 315, 90: 360,
                  100: 405, 110: 435, 120: 470 };

// ความเร็วสูงสุดที่รองรับ = เพดานทางพิเศษของไทย  เกินจากนี้ใช้ค่าที่ 120
const MAX_DESIGN_SPEED_KMH = 120;

// ใช้เมื่อยังไม่รู้ความเร็ว (เพิ่งจับดาวได้ / เบราว์เซอร์ไม่ให้ค่า) — เลือกค่ากลางของตาราง
const DEFAULT_SPEED_KMH = 90;

// ต่ำกว่านี้ถือว่ารถไม่ได้เคลื่อนที่ — คงค่าความเร็วเดิมไว้ ไม่ให้ระยะ beep เด้งไปมาตอน
const SPEED_HOLD_MIN_KMH = 5;

const BEEP_FAR_FRAC = 0.66; // เกิน 66% ของระยะเริ่ม beep = จังหวะช้า
const BEEP_MID_FRAC = 0.33; // 33-66% = ปานกลาง · ต่ำกว่านั้น = ถี่สุด

// ถือว่า "ขับผ่านไปแล้ว" เมื่อระยะเพิ่มจากค่าต่ำสุดที่เคยวัดได้เกินค่านี้ แล้วหยุด beep
const BEEP_RECEDE_MIN_M = 25;

/** ระยะที่เริ่ม beep บอกระยะ = DSD Maneuver E ที่ความเร็วรถขณะนั้น */
function beepStartM(speedKmh) {
  let v = (speedKmh === null || speedKmh === undefined || Number.isNaN(speedKmh))
    ? DEFAULT_SPEED_KMH
    : Math.min(speedKmh, MAX_DESIGN_SPEED_KMH);
  const speeds = Object.keys(DSD_E_M).map(Number).sort((a, b) => a - b);
  for (const s of speeds) if (v <= s) return DSD_E_M[s];
  return DSD_E_M[speeds[speeds.length - 1]];
}

/** ประเมินความเร็วจากพิกัดที่เปลี่ยนไป — ใช้เมื่อ coords.speed ของเบราว์เซอร์เป็น null */
function createSpeedTracker(minMoveM = 15) {
  let last = null;
  let speedKmh = null;
  return {
    update(lat, lng, nowMs = Date.now()) {
      if (last === null) {
        last = { lat, lng, t: nowMs };
        return speedKmh;
      }
      const moved = haversineMeters(last.lat, last.lng, lat, lng);
      const dt = (nowMs - last.t) / 1000;
      if (moved < minMoveM || dt <= 0) return speedKmh; // ยังขยับไม่พอให้เชื่อ
      speedKmh = (moved / dt) * 3.6;
      last = { lat, lng, t: nowMs };
      return speedKmh;
    },
    get() {
      return speedKmh;
    },
  };
}

/** เลือกจังหวะ beep จากจุดที่ใกล้ที่สุดเทียบกับระยะเริ่ม beep ของความเร็วปัจจุบัน */
function beepPatternFor(entries, closestSeen, speedKmh) {
  const radius = beepStartM(speedKmh);
  let best = null;
  for (const { point, distance } of entries) {
    const low = closestSeen.get(point.id);
    if (low === undefined || distance < low) closestSeen.set(point.id, distance);
    if (distance > radius) continue;
    if (distance > closestSeen.get(point.id) + BEEP_RECEDE_MIN_M) continue; // ผ่านไปแล้ว
    const frac = distance / radius;
    if (best === null || frac < best) best = frac;
  }
  if (best === null) return null;
  if (best > BEEP_FAR_FRAC) return "far";
  if (best > BEEP_MID_FRAC) return "mid";
  return "near";
}

// export ให้ทั้งเบราว์เซอร์ (global) และ Node (module.exports)
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    haversineMeters, inBoundingBox, findNearbyPoints,
    bearingDegrees, angleDiffDegrees, createHeadingTracker, isAhead,
    createCourseTracker, circularMeanDegrees,
    HEADING_NEAR_BYPASS_M, FRONT_CONE_DEG, COG_MIN_SPEED_KMH, COG_HOLD_MAX_MS,
    COURSE_WINDOW_MS,
    beepStartM, beepPatternFor, createSpeedTracker,
    DSD_E_M, BEEP_RECEDE_MIN_M, SPEED_HOLD_MIN_KMH, DEFAULT_SPEED_KMH,
  };
}
