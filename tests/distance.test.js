/**
 * unit test ของ js/distance.js — รันด้วย: node tests/distance.test.js
 */

const { haversineMeters, inBoundingBox, findNearbyPoints } = require("../js/distance.js");

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

console.log(`\nผล: ผ่าน ${passed} / ${passed + failed}`);
process.exit(failed > 0 ? 1 : 0);
