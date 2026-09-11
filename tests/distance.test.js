/** unit test ของ js/distance.js — รันด้วย: node tests/distance.test.js */

const {
  haversineMeters, inBoundingBox, findNearbyPoints,
  bearingDegrees, angleDiffDegrees, createHeadingTracker, isAhead,
  createCourseTracker, circularMeanDegrees, FRONT_CONE_DEG,
  COG_MIN_SPEED_KMH, COG_HOLD_MAX_MS, COURSE_WINDOW_MS,
  beepStartM, beepPatternFor, createSpeedTracker, DSD_E_M, BEEP_RECEDE_MIN_M,
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
  assert("รถทับจุดพอดี -> ต้องเตือน ไม่ใช่ถูกกรองทิ้ง", isAhead(0, ...O, ...O, 90));
  assert("จุดข้างหลังแต่ห่างแค่ 10 ม. -> ยังเตือน (ใกล้เกินกว่าจะเชื่อทิศ)",
    isAhead(0, ...O, 13.75621, 100.5018, 90));
  assert("จุดข้างหลังห่าง 100 ม. -> ข้าม (พ้นระยะยกเว้นแล้ว)",
    !isAhead(0, ...O, 13.7554, 100.5018, 90));
}

console.log("");
console.log("angleDiffDegrees — มุมวนรอบ 360 องศา (เคสที่ทิศจริงจาก COG เจอทุกวัน):");
{
  // COG ที่ตัวรับส่งมาอยู่ในช่วง 0-359.9 เสมอ รถที่วิ่งขึ้นเหนือจึงสลับไปมาระหว่าง
  assert("359.9° กับ 0.1° ต่างกัน 0.2° ไม่ใช่ 359.8°",
    Math.abs(angleDiffDegrees(359.9, 0.1) - 0.2) < 1e-9);
  assert("1° กับ 359° ต่างกัน 2°", Math.abs(angleDiffDegrees(1, 359) - 2) < 1e-9);
  assert("270° กับ 90° ต่างกัน 180° (ตรงข้ามกันพอดี)", angleDiffDegrees(270, 90) === 180);
  assert("315° กับ 45° ต่างกัน 90° (ขอบกรวยพอดี)", angleDiffDegrees(315, 45) === 90);
  assert("ผลลัพธ์ไม่เกิน 180 เสมอ ไม่ว่าป้อนอะไรเข้าไป",
    [[0, 359], [180, 0], [90, 271], [359, 181]].every(([a, b]) => angleDiffDegrees(a, b) <= 180));
  // มุมเกิน 360 เกิดได้จากค่าที่บวกสะสมมา (เช่นมุมสะสมของลูกศรบนแผนที่)
  assert("รับมุมเกิน 360 ได้ (720 = 0)", angleDiffDegrees(720, 0) === 0);
}

console.log("");
console.log("isAhead ตรงรอยต่อ 0/360 (รถวิ่งขึ้นเหนือ = เคสที่พังง่ายที่สุด):");
{
  const O = [13.7563, 100.5018];
  const N = [13.7663, 100.5018];  // เหนือ ~1.1 กม.
  const S = [13.7463, 100.5018];  // ใต้  ~1.1 กม.
  // รถชี้ 359.5° (เกือบเหนือพอดี) จุดที่อยู่ทางเหนือ bearing = 0° ต่างกันแค่ 0.5°
  assert("ทิศ 359.5° จุดทางเหนือ (bearing 0°) -> ข้างหน้า", isAhead(359.5, ...O, ...N, 90));
  assert("ทิศ 0.5° จุดทางเหนือ -> ข้างหน้า", isAhead(0.5, ...O, ...N, 90));
  assert("ทิศ 359.5° จุดทางใต้ (bearing 180°) -> ข้างหลัง", !isAhead(359.5, ...O, ...S, 90));
  assert("ทิศ 350° จุดทางเหนือ -> ยังข้างหน้า (ต่างกัน 10° ไม่ใช่ 350°)",
    isAhead(350, ...O, ...N, 90));
}

console.log("");
console.log("FRONT_CONE_DEG:");
{
  // กรวยแคบ ±30° เตือนเฉพาะจุดที่เกือบตรงหน้ารถ
  assert("ค่าเริ่มต้น = 30", FRONT_CONE_DEG === 30);
  const O = [13.7563, 100.5018];
  const N = [13.7663, 100.5018]; // เหนือ ~1.1 กม. = ตรงหน้าพอดี
  const E = [13.7563, 100.5118]; // ตะวันออก ~1.1 กม. = ตั้งฉากกับหัวรถ
  assert("จุดที่อยู่ตรงหน้าถือว่าอยู่ข้างหน้า",
    isAhead(0, ...O, ...N, FRONT_CONE_DEG));
  assert("ที่ 30° จุดตั้งฉาก 90° ถูกตัดออก",
    !isAhead(0, ...O, ...E, FRONT_CONE_DEG));
  assert("จุดที่เบน 45° ถูกตัดออกด้วย",
    !isAhead(0, ...O, 13.76336, 100.50949, FRONT_CONE_DEG));
}

console.log("");
console.log("createCourseTracker (COG จากตัวรับ + speed gate):");
{
  assert("เกณฑ์ความเร็วเริ่มต้น = 5 กม./ชม.", COG_MIN_SPEED_KMH === 5);
  assert("อายุค่าที่ค้างไว้ = 2 นาที", COG_HOLD_MAX_MS === 120000);

  const t = createCourseTracker();
  assert("เพิ่งเริ่ม ยังไม่ป้อนอะไร -> null", t.get(0) === null);
  // รถเพิ่งออกจากป้าย ยังคลานอยู่ 3 กม./ชม. — COG รอบนี้เชื่อไม่ได้ และไม่มีค่าเก่าให้ค้าง
  assert("ยังไม่เคยได้ค่าที่เชื่อได้ + รถยังคลานช้า -> null",
    t.update(90, 3, 0) === null && t.get(0) === null);
}
{
  const t = createCourseTracker();
  assert("วิ่ง 60 กม./ชม. ทิศ 90° -> รับค่า", t.update(90, 60, 1000) === 90);

  // นี่คือหัวใจของ speed gate: ตอนจอดนิ่ง COG ที่โมดูลส่งมาหมุนสุ่มทั้ง 360 องศา
  assert("จอดนิ่ง (0 กม./ชม.) COG สุ่มมาเป็น 270° -> ไม่รับ คงค่าเดิม 90°",
    t.update(270, 0, 2000) === 90);
  assert("คลานช้า 4 กม./ชม. (ต่ำกว่าเกณฑ์) -> ยังคงค่าเดิม",
    t.update(180, 4, 3000) === 90);
  assert("เร่งถึง 5 กม./ชม. พอดี -> รับค่าใหม่", t.update(180, 5, 4000) === 180);

  assert("โมดูลไม่ส่ง COG มารอบนี้ (null) -> คงค่าเดิม", t.update(null, 80, 5000) === 180);
  assert("ไม่รู้ความเร็ว (null) -> ไม่กล้ารับค่าใหม่ คงค่าเดิม", t.update(45, null, 6000) === 180);

  // จอดไฟแดง 1-2 นาทีแล้วออกรถทิศเดิม = ค่าเก่ายังใช้ได้
  assert("จอด 119 วิ -> ยังคงค่าเดิมไว้", t.get(4000 + 119000) === 180);
  // จอดนานกว่านั้น (จอดป้าย เข้าอู่ กลับรถ) ทิศเก่าอันตรายกว่าไม่รู้ทิศ
  assert("จอดเกิน 2 นาที -> ทิ้งค่า กลับไปเป็นไม่รู้ทิศ", t.get(4000 + 121000) === null);
  assert("ทิ้งแล้วต้องไม่ฟื้นกลับมาเอง", t.get(4000 + 121001) === null);
}
{
  // ค่าดิบจากตัวรับควรอยู่ 0-359.9 อยู่แล้ว แต่ต้องไม่พังถ้าเจอ 360 พอดีหรือค่าลบ
  const t = createCourseTracker();
  assert("360° ถูกทำให้เป็น 0°", t.update(360, 50, 0) === 0);
  assert("ค่าลบ -10° ถูกทำให้เป็น 350°", t.update(-10, 50, 1000) === 350);
  t.reset();
  assert("reset() -> กลับไปไม่รู้ทิศ", t.get(2000) === null);
}
{
  // ผ่าน gate ด้วยความเร็วจาก GPS ที่ต่างจากความเร็วที่ประมาณจากพิกัด — ต้องใช้ค่าที่ส่งเข้ามา
  const t = createCourseTracker(20); // ตั้งเกณฑ์เองได้ (เช่นถ้าติดตั้งบนรถที่วิ่งเร็วเสมอ)
  assert("เกณฑ์ 20 กม./ชม.: ที่ 15 -> ไม่รับ", t.update(90, 15, 0) === null);
  assert("เกณฑ์ 20 กม./ชม.: ที่ 25 -> รับ", t.update(90, 25, 1000) === 90);
}

console.log("");
console.log("circularMeanDegrees (เฉลี่ยมุมแบบวงกลม):");
{
  // เหตุผลที่ต้องมีฟังก์ชันนี้: เฉลี่ยองศาตรง ๆ 350 กับ 10 จะได้ 180 ซึ่งชี้ตรงข้ามพอดี
  const m = circularMeanDegrees([350, 10]);
  assert(`350° กับ 10° เฉลี่ยได้ ~0° ไม่ใช่ 180° (ได้ ${m.toFixed(1)}°)`,
    m < 1 || m > 359);
  const m2 = circularMeanDegrees([355, 5, 0]);
  assert(`355°, 5°, 0° เฉลี่ยได้ ~0° (ได้ ${m2.toFixed(1)}°)`, m2 < 1 || m2 > 359);
  assertClose("10°, 20°, 30° เฉลี่ยได้ 20°", circularMeanDegrees([10, 20, 30]), 20, 0.1);
  assertClose("89°, 91° เฉลี่ยได้ 90°", circularMeanDegrees([89, 91]), 90, 0.1);
  assertClose("270°, 350° เฉลี่ยได้ 310°", circularMeanDegrees([270, 350]), 310, 0.1);

  // ตัวอย่างเดียวต้องได้ค่าเดิมเป๊ะ ไม่มีเศษจาก atan2 (โค้ดที่เรียกใช้เทียบด้วย === ได้)
  assert("ตัวอย่างเดียว -> คืนค่าเดิมเป๊ะ", circularMeanDegrees([90]) === 90);
  assert("ตัวอย่างเดียวที่เป็น 359.9 -> 359.9 เป๊ะ", circularMeanDegrees([359.9]) === 359.9);
  assert("360 ถูกทำให้เป็น 0", circularMeanDegrees([360]) === 0);
  assert("ค่าลบถูกทำให้เป็นบวก", circularMeanDegrees([-10]) === 350);

  assert("ไม่มีตัวอย่างเลย -> null", circularMeanDegrees([]) === null);
  // มุมที่หักล้างกันหมดไม่มีทิศกลาง — ต้องคืน null ให้ผู้เรียกใช้ค่าสำรอง ไม่ใช่เดามั่ว
  assert("0° กับ 180° หักล้างกัน -> null (ไม่มีทิศกลาง)",
    circularMeanDegrees([0, 180]) === null);
  assert("กระจายรอบวงเท่า ๆ กัน -> null",
    circularMeanDegrees([0, 90, 180, 270]) === null);
}

console.log("");
console.log("createCourseTracker + หน้าต่างเฉลี่ย (จำลองข้อมูล 10Hz):");
{
  assert("หน้าต่างเฉลี่ย = 0.5 วิ (ตรงกับ COURSE_WINDOW_S ฝั่งอุปกรณ์)",
    COURSE_WINDOW_MS === 500);

  // ที่ 10Hz หน้าต่าง 500 ms = ~5 ตัวอย่าง ป้อนค่าคร่อมรอย 0/360 เข้าไป
  const t = createCourseTracker();
  let last = null;
  [358, 359, 0, 1, 2].forEach((deg, i) => {
    last = t.update(deg, 60, 100 * i); // ทุก 100 ms = 10Hz
  });
  assert(`ค่าคร่อมรอย 0/360 เฉลี่ยได้ ~0° ไม่ใช่ ~180° (ได้ ${last.toFixed(1)}°)`,
    last < 2 || last > 358);
}
{
  // ค่าหลุดเดี่ยว ๆ จาก multipath ตอนตึกสูงบัง — การเฉลี่ยต้องดึงกลับมาใกล้ของจริง
  const t = createCourseTracker();
  [90, 90, 90, 90].forEach((deg, i) => t.update(deg, 60, 100 * i));
  const spiked = t.update(200, 60, 400); // ค่าหลุด 110 องศาในเฟรมเดียว
  assert(`ค่าหลุด 1 เฟรมถูกกลืนไว้ (ได้ ${spiked.toFixed(1)}° ไม่ใช่ 200°)`,
    spiked > 90 && spiked < 130);
}
{
  // ตัวอย่างเก่ากว่าหน้าต่างต้องถูกทิ้ง ไม่งั้นทิศจะตามไม่ทันตอนเลี้ยว
  const t = createCourseTracker();
  t.update(0, 60, 0);
  const after = t.update(90, 60, 2000); // ห่าง 2 วิ = เกินหน้าต่าง 0.5 วิ ไปมาก
  assert("ตัวอย่างเก่าเกินหน้าต่างถูกทิ้ง -> ได้ 90° เป๊ะ ไม่ใช่ค่าเฉลี่ยกับ 0°",
    after === 90);
}
{
  // รถจอด: ไม่เก็บตัวอย่างใหม่เลย ค่าเดิมต้องค้างไว้ ไม่ใช่หายไปเมื่อหน้าต่างหมดอายุ
  const t = createCourseTracker();
  t.update(120, 60, 0);
  assert("จอดนิ่ง 3 วิ (ไม่มีตัวอย่างใหม่) -> ยังคงค่าเดิม 120°",
    t.update(45, 0, 3000) === 120);
  assert("get() ก็ยังได้ค่าเดิม", t.get(3000) === 120);
}

console.log("");
console.log("beepStartM (AASHTO Table 3-3 Maneuver E ตามความเร็วรถ):");
{
  // ขั้นบันไดตามที่ผู้ใช้กำหนด: 0-50 · 51-60 · 61-70 · ... · 111-120
  assert("0 กม./ชม. (รถจอด) -> 200 ม.", beepStartM(0) === 200);
  assert("50 -> 200 ม. (ขอบบนของช่วงแรก)", beepStartM(50) === 200);
  assert("51 -> 235 ม. (ข้ามขั้น)", beepStartM(51) === 235);
  assert("70 -> 275 ม.", beepStartM(70) === 275);
  assert("80 -> 315 ม.", beepStartM(80) === 315);
  assert("90 -> 360 ม.", beepStartM(90) === 360);
  assert("100 -> 405 ม.", beepStartM(100) === 405);
  assert("110 -> 435 ม.", beepStartM(110) === 435);
  assert("120 -> 470 ม.", beepStartM(120) === 470);

  // เกินเพดานทางพิเศษไทย — ต้องไม่คืน undefined/NaN
  assert("150 (เกินเพดาน) -> ตัดที่ 470 ม.", beepStartM(150) === 470);
  assert("ยังไม่รู้ความเร็ว -> ใช้ค่ากลาง 90 (= 360 ม.)", beepStartM(null) === 360);
  assert("undefined -> ใช้ค่ากลางเช่นกัน", beepStartM(undefined) === 360);

  // ระยะเริ่ม beep ต้องต่ำกว่าระยะที่เสียงพูดยิง (500 ม.) เสมอ ไม่งั้นลำดับเสียงสลับกัน
  const speeds = Object.keys(DSD_E_M).map(Number);
  assert("ทุกความเร็ว beep เริ่มใกล้กว่า 500 ม. (พูดก่อน beep เสมอ)",
    speeds.every((v) => beepStartM(v) < 500));

  // ต้องเพิ่มตามความเร็วเสมอ — เคยเจอค่าพิมพ์ผิดในเอกสารที่ยกตารางนี้ไปเผยแพร่ต่อ
  const sorted = speeds.sort((a, b) => a - b);
  let monotonic = true;
  for (let i = 1; i < sorted.length; i++) {
    if (DSD_E_M[sorted[i]] <= DSD_E_M[sorted[i - 1]]) monotonic = false;
  }
  assert("ตาราง DSD เพิ่มตามความเร็วทุกแถว (จับค่าลอกผิด)", monotonic);
}

console.log("");
console.log("createSpeedTracker:");
{
  const t = createSpeedTracker(15);
  assert("ตำแหน่งแรกยังไม่รู้ความเร็ว", t.update(13.75, 100.5, 0) === null);
  // ขยับ 5 ม. ใน 1 วิ = 18 กม./ชม. แต่ยังไม่ถึงเกณฑ์ 15 ม. -> ไม่เชื่อ
  assert("ขยับ 5 ม. ยังไม่พอให้เชื่อ (GPS แกว่งได้เท่านี้)",
    t.update(13.750045, 100.5, 1000) === null);
  // ขยับ ~111 ม. ใน 4 วิ = 100 กม./ชม.
  const v = t.update(13.751, 100.5, 4000);
  assert("ขยับ 111 ม. ใน 4 วิ -> ได้ ~100 กม./ชม.", v > 95 && v < 105);
  assert("get() คืนค่าล่าสุด", t.get() === v);
}

console.log("");
console.log("beepPatternFor:");
{
  const at = (d) => [{ point: { id: "a" }, distance: d }];

  let seen = new Map();
  assert("ไกลกว่าระยะเริ่ม beep -> ยังไม่ร้อง", beepPatternFor(at(400), seen, 90) === null);
  assert("ถึงระยะพอดี (360 ที่ 90 กม./ชม.) -> จังหวะช้า",
    beepPatternFor(at(360), seen, 90) === "far");
  assert("240 ม. (67%) -> ยังช้าอยู่", beepPatternFor(at(240), seen, 90) === "far");
  assert("120 ม. (33%) -> ปานกลาง", beepPatternFor(at(120), seen, 90) === "mid");
  assert("60 ม. (17%) -> ถี่สุด", beepPatternFor(at(60), seen, 90) === "near");

  // ขับผ่านจุดไปแล้วต้องหยุดเอง ไม่งั้นเสียงค้างจนกว่าจะพ้นรัศมี EXIT ทั้งวง
  assert("ขับผ่านไปแล้ว (ระยะเพิ่มเกิน 25 ม.) -> หยุดร้อง",
    beepPatternFor(at(60 + BEEP_RECEDE_MIN_M + 5), seen, 90) === null);

  // GPS แกว่ง 5-15 ม. ตอนรถติดไฟแดง ต้องไม่ทำให้เสียงติด ๆ ดับ ๆ
  seen = new Map();
  beepPatternFor(at(60), seen, 90);
  assert("GPS แกว่ง +15 ม. -> ยังร้องต่อ ไม่ตัดสินว่าขับผ่านแล้ว",
    beepPatternFor(at(75), seen, 90) === "near");

  // ระยะเดียวกันแต่คนละความเร็ว ต้องได้ผลต่างกัน — นี่คือหัวใจของการปรับตามความเร็ว
  seen = new Map();
  assert("330 ม. ที่ 120 กม./ชม. (เริ่ม 470) -> ร้องแล้ว",
    beepPatternFor(at(330), seen, 120) === "far");
  seen = new Map();
  assert("330 ม. ที่ 60 กม./ชม. (เริ่ม 235) -> ยังไม่ร้อง",
    beepPatternFor(at(330), seen, 60) === null);

  // หลายจุดพร้อมกัน -> ใช้จุดที่ใกล้ที่สุด
  seen = new Map();
  const many = [
    { point: { id: "x" }, distance: 300 },
    { point: { id: "y" }, distance: 80 },
  ];
  assert("หลายจุดพร้อมกัน -> ใช้จุดที่ใกล้ที่สุด", beepPatternFor(many, seen, 90) === "near");

  assert("ไม่มีจุดเลย -> เงียบ", beepPatternFor([], new Map(), 90) === null);
}

console.log(`\nผล: ผ่าน ${passed} / ${passed + failed}`);
process.exit(failed > 0 ? 1 : 0);
