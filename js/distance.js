/**
 * distance.js — เรขาคณิตบนพื้นโลก: ระยะทาง (Haversine), กรองหยาบด้วย bounding box
 * และทิศทาง (bearing) สำหรับกรองเฉพาะจุดเสี่ยงที่รถกำลังมุ่งหน้าไป
 * ไฟล์นี้ไม่แตะ DOM เลย เพื่อให้รัน unit test ใน Node ได้ด้วย
 */

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

/**
 * กรองหยาบ: จุดอยู่ในกรอบสี่เหลี่ยมรอบตำแหน่งผู้ใช้หรือไม่
 * ถูกกว่า Haversine มาก ใช้คัดทิ้งจุดไกลๆ ก่อนคำนวณละเอียด
 */
function inBoundingBox(userLat, userLon, pointLat, pointLon, radiusMeters) {
  const dLat = radiusMeters / 111320; // 1 องศาละติจูด ≈ 111.32 กม.
  const dLon = radiusMeters / (111320 * Math.cos((userLat * Math.PI) / 180));
  return (
    Math.abs(pointLat - userLat) <= dLat &&
    Math.abs(pointLon - userLon) <= dLon
  );
}

/**
 * หาจุดเสี่ยงทั้งหมดในรัศมี radiusMeters จากตำแหน่งผู้ใช้
 * points: [{lat, lng, ...}] — คืน [{point, distance}] เรียงใกล้ -> ไกล
 */
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

/**
 * ทิศจากจุดหนึ่งไปอีกจุด เป็นองศา 0-360 (0 = เหนือ, 90 = ตะวันออก)
 * ใช้สูตร initial bearing ของ great-circle เหมือน Haversine ไม่ใช่การลบพิกัดตรง ๆ
 * เพราะเส้นลองจิจูดลู่เข้าหากันเมื่อเข้าใกล้ขั้วโลก การลบตรง ๆ จะเพี้ยน
 */
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

/**
 * ตัวติดตามทิศที่รถกำลังมุ่งหน้า — คำนวณจากตำแหน่งที่ขยับไปจริง
 *
 * ทำไมต้องมี minMoveM: GPS มีความคลาดเคลื่อนอยู่ตลอดแม้รถจอดนิ่ง ถ้าคิดทิศจาก
 * ทุกคู่พิกัดที่ได้มา รถจอดอยู่กับที่จะได้ทิศสุ่มไปมา แล้วการกรอง "ข้างหน้า"
 * จะกลายเป็นสุ่มว่าจะเตือนหรือไม่เตือน ต้องรอให้ขยับพอที่ระยะจะชนะ noise ก่อน
 *
 * คืน null จนกว่าจะรู้ทิศจริง — ผู้เรียกต้องถือว่า "ไม่รู้ทิศ = ไม่กรอง"
 * ปลอดภัยกว่าเดาแล้วเงียบจุดที่ควรเตือน
 */
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

/**
 * ระยะที่ใกล้เกินกว่าจะเชื่อทิศ — ต่ำกว่านี้ให้ผ่านเสมอ ไม่ต้องกรอง
 *
 *  * เหตุผล: ทิศจากรถไปยังจุดที่แทบจะทับกันอยู่แล้วไม่มีความหมาย ความคลาดเคลื่อนของ GPS
 * (ปกติ 5-15 ม.) ครอบงำการคำนวณจนได้ทิศสุ่ม เช่น ยืนทับจุดพอดีอาจคำนวณได้ว่า
 * "จุดอยู่ข้างหลัง 177 องศา" แล้วโดนกรองทิ้งทั้งที่กำลังอยู่บนจุดเสี่ยงนั้น
 *
 * เจอจริงตอนจำลองขับวนรอบสนามทดสอบ สวทช.: เส้นทางสุ่มตัวอย่างห่างกัน ~39 ม.
 * ทำให้รถกระโดดจาก 71 ม. -> 0 ม. -> 72 ม. มีตัวอย่างเดียวที่อยู่ในรัศมี 60 ม.
 * และตัวอย่างนั้นทับจุดพอดี ผลคือจุด nstda_w3 ไม่ถูกเตือนเลยทั้งรอบ
 * สถานการณ์เดียวกันเกิดกับ GPS จริงได้ เพราะโพลทุก 3 วิ ที่ 60 กม./ชม. = 50 ม./ตัวอย่าง
 *
 * 30 ม. มาจากการเผื่อความคลาดเคลื่อน GPS สองเท่า และถึงระยะนั้นก็ควรเตือนอยู่แล้ว
 * ไม่ว่าจะหันไปทางไหน เพราะอยู่ตรงจุดเสี่ยงพอดี
 */
const HEADING_NEAR_BYPASS_M = 30;

/**
 * จุดนี้อยู่ "ข้างหน้า" รถหรือไม่
 * headingDeg = null (ยังไม่รู้ทิศ เช่น รถเพิ่งออก) -> ถือว่าอยู่ข้างหน้าไว้ก่อน
 * windowDeg >= 180 -> ปิดการกรอง (ทุกทิศถือว่าข้างหน้า)
 */
function isAhead(headingDeg, userLat, userLng, pointLat, pointLng, windowDeg) {
  if (headingDeg === null || headingDeg === undefined) return true;
  if (windowDeg >= 180) return true;
  if (haversineMeters(userLat, userLng, pointLat, pointLng) <= HEADING_NEAR_BYPASS_M) return true;
  const toPoint = bearingDegrees(userLat, userLng, pointLat, pointLng);
  return angleDiffDegrees(headingDeg, toPoint) <= windowDeg;
}

// export ให้ทั้งเบราว์เซอร์ (global) และ Node (module.exports)
if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    haversineMeters, inBoundingBox, findNearbyPoints,
    bearingDegrees, angleDiffDegrees, createHeadingTracker, isAhead,
    HEADING_NEAR_BYPASS_M,
  };
}
