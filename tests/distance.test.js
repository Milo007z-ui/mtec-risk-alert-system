/**
 * unit test ของ js/distance.js — รันด้วย: node tests/distance.test.js
 */

const {
  haversineMeters, inBoundingBox, findNearbyPoints,
  bearingDegrees, angleDiffDegrees, createHeadingTracker, isAhead,
} = require("../js/distance.js");

let passed = 0;
let failed = 0;

function assertClose(name, actual, expected, tolerancePct) {
  const diffPct = Math.abs(actual - expected) / expected * 100;
  if (diffPct <= tolerancePct) {
    passed++;
    console.log(`  ✓ ${name} (ได้ ${actual.toFixed(1)} ม. คลาดเคลื่อน ${diffPct.toFixed(2)}%)`);
  } else {
    failed++;
    console.error(`  ✗ ${name} — ได้ ${actual} คาดหวัง ${expected} (คลาดเคลื่อน ${diffPct.toFixed(2)}% > ${tolerancePct}%)`);
  }
}

function assert(name, condition) {
  if (condition) {
    passed++;
    console.log(`  ✓ ${name}`);
  } else {
    failed++;
    console.error(`  ✗ ${name}`);
  }
}

console.log("haversineMeters:");

// ค่าแม่นตรงทางคณิตศาสตร์บนทรงกลม R=6371km: 1 องศาละติจูด = π/180 × R = 111,194.93 ม.
assertClose("1 องศาละติจูด ≈ 111.19 กม.", haversineMeters(13.0, 100.5, 14.0, 100.5), 111194.93, 0.01);

// ระยะจริง (เส้นตรง) สนามบินดอนเมือง -> สุวรรณภูมิ ≈ 29 กม.
assertClose(
  "ดอนเมือง -> สุวรรณภูมิ ≈ 29 กม.",
  haversineMeters(13.9126, 100.6068, 13.69, 100.7501),
  29000,
  5
);

assert("จุดเดียวกันระยะ = 0", haversineMeters(13.75, 100.5, 13.75, 100.5) === 0);
assert(
  "สมมาตร: d(A,B) = d(B,A)",
  haversineMeters(13.7, 100.5, 13.8, 100.6) === haversineMeters(13.8, 100.6, 13.7, 100.5)
);

console.log("inBoundingBox:");
assert("จุดห่าง ~300 ม. อยู่ในกรอบ 500 ม.", inBoundingBox(13.75, 100.5, 13.7527, 100.5, 500));
assert("จุดห่าง ~1.1 กม. ไม่อยู่ในกรอบ 500 ม.", !inBoundingBox(13.75, 100.5, 13.76, 100.5, 500));

console.log("findNearbyPoints:");
const points = [
  { id: "far", lat: 13.80, lng: 100.5 },   // ~5.5 กม.
  { id: "near", lat: 13.7527, lng: 100.5 }, // ~300 ม.
  { id: "mid", lat: 13.754, lng: 100.5 },   // ~445 ม.
];
const nearby = findNearbyPoints(13.75, 100.5, points, 500);
assert("เจอ 2 จุดในรัศมี 500 ม.", nearby.length === 2);
assert("เรียงใกล้ -> ไกล", nearby.length === 2 && nearby[0].point.id === "near" && nearby[1].point.id === "mid");
assert("ระยะที่คืนมาสมเหตุสมผล", nearby.length === 2 && nearby[0].distance > 250 && nearby[0].distance < 350);

console.log("bearingDegrees:");
const O = [13.7563, 100.5018];
assertClose("ไปทางเหนือ = 0°", bearingDegrees(...O, 13.8563, 100.5018) + 1, 1, 1);
assertClose("ไปทางตะวันออก = 90°", bearingDegrees(...O, 13.7563, 100.6018), 90, 1);
assertClose("ไปทางใต้ = 180°", bearingDegrees(...O, 13.6563, 100.5018), 180, 1);
assertClose("ไปทางตะวันตก = 270°", bearingDegrees(...O, 13.7563, 100.4018), 270, 1);

console.log("angleDiffDegrees:");
assert("350° กับ 10° ต่างกัน 20° (ข้ามรอย 0/360)", angleDiffDegrees(350, 10) === 20);
assert("10° กับ 350° ได้เท่ากัน ไม่ขึ้นกับลำดับ", angleDiffDegrees(10, 350) === 20);
assert("ตรงข้ามกันได้ 180°", angleDiffDegrees(0, 180) === 180);
assert("มุมเดียวกันได้ 0°", angleDiffDegrees(90, 90) === 0);

console.log("createHeadingTracker:");
{
  const t = createHeadingTracker(15);
  assert("ตำแหน่งแรกยังไม่รู้ทิศ", t.update(13.7563, 100.5018) === null);
  // ขยับ ~5 ม. ยังไม่ถึงเกณฑ์ -> ต้องไม่เชื่อทิศ (กัน GPS แกว่งตอนรถจอด)
  assert("ขยับ 5 ม. ยังไม่พอให้เชื่อทิศ", t.update(13.75635, 100.5018) === null);
  // ขยับไปทางเหนือเกิน 15 ม. -> ได้ทิศ ~0°
  const h = t.update(13.7565, 100.5018);
  assert("ขยับเกิน 15 ม. ไปทางเหนือ -> ได้ทิศ ~0°", h !== null && (h < 5 || h > 355));
}

console.log("isAhead:");
{
  // รถมุ่งหน้าทิศเหนือ (0°) จากจุด O — จุดทดสอบวางห่างพอให้พ้นระยะยกเว้น 30 ม.
  const N = [13.7663, 100.5018];  // เหนือ ~1.1 กม.
  const S = [13.7463, 100.5018];  // ใต้  ~1.1 กม.
  const E = [13.7563, 100.5118];  // ตะวันออก ~1.1 กม.
  assert("จุดข้างหน้า -> เตือน", isAhead(0, ...O, ...N, 90));
  assert("จุดข้างหลัง -> ข้าม", !isAhead(0, ...O, ...S, 90));
  assert("จุดด้านข้าง 90° -> เตือน (อยู่ขอบพอดี)", isAhead(0, ...O, ...E, 90));
  assert("กรองแคบ 45° จุดด้านข้าง -> ข้าม", !isAhead(0, ...O, ...E, 45));
  assert("ยังไม่รู้ทิศ -> เตือนไว้ก่อน", isAhead(null, ...O, ...S, 90));
  assert("window 180 = ปิดการกรอง -> เตือนทุกทิศ", isAhead(0, ...O, ...S, 180));

  // เคสที่เคยพลาดจริง: รถทับจุดพอดี ทิศที่คำนวณได้ไม่มีความหมาย
  // เจอตอนจำลองขับวนสนามทดสอบ สวทช. — จุด nstda_w3 ไม่ถูกเตือนเลยทั้งรอบ
  assert("รถทับจุดพอดี -> ต้องเตือน ไม่ใช่ถูกกรองทิ้ง", isAhead(0, ...O, ...O, 90));
  assert("จุดข้างหลังแต่ห่างแค่ 10 ม. -> ยังเตือน (ใกล้เกินกว่าจะเชื่อทิศ)",
    isAhead(0, ...O, 13.75621, 100.5018, 90));
  assert("จุดข้างหลังห่าง 100 ม. -> ข้าม (พ้นระยะยกเว้นแล้ว)",
    !isAhead(0, ...O, 13.7554, 100.5018, 90));
}

console.log(`\nผล: ผ่าน ${passed} / ${passed + failed}`);
process.exit(failed > 0 ? 1 : 0);
