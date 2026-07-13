/**
 * distance.js — คำนวณระยะทางระหว่างพิกัด (Haversine) + กรองหยาบด้วย bounding box
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

// export ให้ทั้งเบราว์เซอร์ (global) และ Node (module.exports)
if (typeof module !== "undefined" && module.exports) {
  module.exports = { haversineMeters, inBoundingBox, findNearbyPoints };
}
