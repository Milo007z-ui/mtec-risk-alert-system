/**
 * alert.js — ตรวจจับการเข้าใกล้จุดเสี่ยงและแจ้งเตือน (เสียง + ภาพ)
 *
 * กติกา cooldown ต่อจุด:
 *  - เตือนครั้งแรกเมื่อเข้ามาในรัศมี ALERT_RADIUS_M
 *  - จะเตือนจุดเดิมซ้ำได้ต่อเมื่อ (ก) ออกไปไกลกว่า EXIT_RADIUS_M แล้วกลับเข้ามาใหม่
 *    หรือ (ข) ยังวนอยู่ในรัศมีนานเกิน REALERT_MS
 *
 * กติกากันพูดทับ: ระหว่างที่ยังเตือนจุดหนึ่งค้างอยู่ จุดถัดไปจะรอให้พูดจบก่อน
 * ยกเว้นจุดที่ระดับสูงกว่าเดิม ให้ตัดเข้าแทนได้ทันที (ของเร่งด่วนกว่าต้องได้ยินก่อน)
 *
 * กติกาทิศทาง (ปัจจุบัน "ปิด" อยู่ — เตือนทุกทิศรอบตัว): เปิดด้วย ?heading=90 บน URL
 * จะเตือนเฉพาะจุดในมุม +-90 องศาจากทิศที่รถมุ่งหน้า ตัดจุดที่ขับผ่านไปแล้วออก
 * ปิดไว้ก่อนเพื่อให้เห็นทุกจุดที่เข้ารัศมี ใช้เป็นฐานเทียบว่าระบบเตือนครบไหม
 * ข้อจำกัดที่ต้องรู้ก่อนเปิด: แยกได้แค่ข้างหน้า/ข้างหลัง ไม่ได้แยกเลนขาขึ้น-ขาล่อง
 */

const AlertSystem = (() => {
  // หน้าเว็บตั้ง window.ALERT_RADIUS_M / window.EXIT_RADIUS_M ไว้ก่อนโหลดสคริปต์นี้ได้
  // เพื่อย่อรัศมีสำหรับสนามทดสอบเล็ก ๆ (test-nstda.html ใช้ 120/150 ม. เพราะถนนวงรอบ
  // อุทยานวิทย์ฯ ยาวแค่ 1.4 กม. ถ้าใช้ 500 ม. ทั้งสามจุดจะร้องพร้อมกันตั้งแต่ยังไม่ออกรถ)
  // ค่า default ต้องเป็น 500/600 เสมอ — เป็นระยะที่ใช้จริงบนถนนนอกพื้นที่
  const ALERT_RADIUS_M = window.ALERT_RADIUS_M || 500;
  const EXIT_RADIUS_M = window.EXIT_RADIUS_M || 600; // hysteresis กันเด้งเข้าออกตรงขอบรัศมี
  const REALERT_MS = 5 * 60 * 1000;

  // มุมที่ถือว่า "ข้างหน้า" นับจากทิศที่รถมุ่งหน้า (องศา ไปทางละเท่านี้)
  //
  // 180 = ปิดการกรองทิศ เตือนทุกทิศรอบตัว (ผู้ใช้เลือกกลับมาใช้แบบนี้ 2026-08-28
  // ก่อนออกทดสอบภาคสนามบนถนนจริงชุด 456 คลัสเตอร์ รัศมี 500 ม.)
  //
  // เหตุผลที่ปิดก่อน: ยังไม่เคยมีการทดสอบบนถนนจริงสำเร็จสักครั้ง จึงยังไม่มีข้อมูลว่า
  // การกรองทิศทำงานถูกต้องแค่ไหนกับ GPS จริงที่มีความคลาดเคลื่อน — ถ้าเปิดไว้แล้ว
  // ระบบเงียบตอนควรเตือน จะแยกไม่ออกว่าเป็นเพราะตัวกรอง หรือเพราะจุดเสี่ยง/พิกัดผิด
  // ปิดไว้ก่อนทำให้เห็นทุกจุดที่เข้ารัศมี ใช้เป็นฐานเทียบได้ว่าระบบเตือนครบไหม
  //
  // โค้ดกับเทสยังอยู่ครบ (bearingDegrees / isAhead / HeadingTracker) เปิดกลับได้ทันที
  // โดยไม่ต้องเขียนใหม่ ตั้งเป็น 90 เพื่อตัดจุดที่ขับผ่านไปแล้วออก — วัดกับเส้นทางจำลอง
  // แล้วลดการเตือนซ้ำซ้อน 41% (สมุทรสาคร 500 ม.) และ 9% (สนามทดสอบ สวทช. 60 ม.)
  // โดยไม่พลาดจุดเสี่ยงใดเลยทั้งสองเส้นทาง
  //
  // ข้อจำกัดที่ต้องรู้ก่อนเปิดกลับ: แยกได้แค่ข้างหน้า/ข้างหลัง ไม่ได้แยกเลนขาขึ้น-ขาล่อง
  // เลนสวนที่อยู่ข้างหน้า 100 ม. เบนจากทิศรถแค่ 8.5 องศา ซึ่งน้อยกว่าความคลาดเคลื่อน
  // ของ GPS เอง (5-15 ม.) จะแยกเลนได้ต้องทำ map matching กับ OSM
  //
  // ลองเปิดสดหน้างานได้ด้วย ?heading=90 บน URL ไม่ต้องแก้โค้ด
  // ** ถ้าเปิดถาวร ต้องตั้งให้ตรงกับ DEFAULT_HEADING_WINDOW_DEG ใน device/pi_alert_client.py **
  const HEADING_WINDOW_DEG = (() => {
    const q = Number(new URLSearchParams(location.search).get("heading"));
    return Number.isFinite(q) && q > 0 ? q : window.HEADING_WINDOW_DEG || 180;
  })();

  // ต้องขยับอย่างน้อย 15 ม. ถึงจะเชื่อทิศ — กัน GPS แกว่งตอนรถจอดทำให้ทิศสุ่มไปมา
  const heading = createHeadingTracker(15);

  const LEVEL_RANK = { low: 1, medium: 2, high: 3 };

  // id จุดเสี่ยง -> { lastAlertAt } (มี entry = ยังอยู่ในสถานะ "เตือนแล้ว")
  const alerted = new Map();

  // ระดับของเสียงเตือนที่กำลังเล่นอยู่ (null = ว่าง พร้อมเตือนจุดใหม่)
  // speakSeq กันชุดเสียงเก่าที่ถูกตัดกลางคัน มาปลดล็อกทับชุดใหม่ที่กำลังพูดอยู่
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
  function onPositionUpdate(lat, lng) {
    const now = Date.now();
    const headingDeg = heading.update(lat, lng);
    // visible() = จุดที่ผ่านตัวกรองบนแผนที่ — เตือนเฉพาะสิ่งที่ผู้ใช้เลือกดูอยู่
    const nearby = findNearbyPoints(lat, lng, RiskPoints.visible(), EXIT_RADIUS_M);
    const nearbyIds = new Set(nearby.map((n) => n.point.id));

    // จุดที่เคยเตือนแล้วแต่ตอนนี้ออกนอกรัศมี EXIT ไปแล้ว -> รีเซ็ตให้เตือนใหม่ได้
    for (const id of alerted.keys()) {
      if (!nearbyIds.has(id)) alerted.delete(id);
    }

    // เตือนเฉพาะจุดที่ใกล้ที่สุดที่เข้าเงื่อนไข (กันพูดรัวเมื่อหลายจุดติดกัน)
    for (const { point, distance } of nearby) {
      if (distance > ALERT_RADIUS_M) continue;
      // จุดที่ขับผ่านไปแล้ว/อยู่ด้านหลัง ไม่ต้องเตือน (ยังไม่รู้ทิศ = เตือนไว้ก่อน)
      if (!isAhead(headingDeg, lat, lng, point.lat, point.lng, HEADING_WINDOW_DEG)) continue;
      const state = alerted.get(point.id);
      if (state && now - state.lastAlertAt < REALERT_MS) continue;

      // ยังพูดจุดก่อนหน้าไม่จบ — รอก่อน เว้นแต่จุดนี้ระดับสูงกว่า จึงตัดเข้าแทนได้
      // (ไม่บันทึกลง alerted จึงกลับมาเตือนได้เองในรอบถัดไปเมื่อเสียงว่าง)
      if (speakingLevel && LEVEL_RANK[point.level] <= LEVEL_RANK[speakingLevel]) break;

      alerted.set(point.id, { lastAlertAt: now });
      // log ไว้ตรวจลำดับการเตือน: บอกจุดที่เตือน + จุดอื่นที่อยู่ในระยะขณะนั้น
      // (ถ้าเห็นว่าเตือนจุดไกลก่อนจุดใกล้ ให้ดูบรรทัดนี้ว่าจุดใกล้ถูกเตือนไปแล้วหรือยัง)
      console.log(
        `[ALERT] ${point.level} ${point.id} ที่ ${distance.toFixed(0)} ม. | ` +
          `ทิศรถ ${headingDeg === null ? "ยังไม่รู้" : headingDeg.toFixed(0) + "°"} ` +
          `(กรอง ±${HEADING_WINDOW_DEG}°) | ในระยะ ${EXIT_RADIUS_M} ม. ตอนนี้: ` +
          nearby
            .map((n) => `${n.point.id} ${n.distance.toFixed(0)}ม.${alerted.has(n.point.id) ? "*" : ""}`)
            .join(", ") +
          " (* = เตือนไปแล้ว)"
      );
      const msg = RiskRules.buildAlertMessage(point, distance);
      showBanner("🔊 " + msg, point.level);
      // เสียงเตือนนำตามระดับความเสี่ยงก่อน แล้วค่อยพูดข้อความ (Botnoi -> Google -> Web Speech)
      // ถ้าทุกชั้นล้มเหลวค่อยเปลี่ยนไอคอนเป็นเตือนภาพ
      speakingLevel = point.level;
      const seq = ++speakSeq;
      TTS.playChime(point.level)
        // ถ้าระหว่างเล่นเสียงนำมีจุดที่เร่งด่วนกว่าตัดเข้ามา ให้ทิ้งประโยคนี้ไปเลย
        // ไม่งั้นชุดเก่าจะพูดออกมาทับตอนเสียงนำของชุดใหม่ยังไม่จบ แล้วค่อยโดนตัดกลางคำ
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

  return { onPositionUpdate, ALERT_RADIUS_M, heading: () => heading.get() };
})();
