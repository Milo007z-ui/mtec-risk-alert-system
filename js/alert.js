/**
 * alert.js — ตรวจจับการเข้าใกล้จุดเสี่ยงและแจ้งเตือน (เสียง + ภาพ)
 *
 * กติกา cooldown ต่อจุด:
 *  - เตือนครั้งแรกเมื่อเข้ามาในรัศมี ALERT_RADIUS_M
 *  - จะเตือนจุดเดิมซ้ำได้ต่อเมื่อ (ก) ออกไปไกลกว่า EXIT_RADIUS_M แล้วกลับเข้ามาใหม่
 *    หรือ (ข) ยังวนอยู่ในรัศมีนานเกิน REALERT_MS
 */

const AlertSystem = (() => {
  const ALERT_RADIUS_M = 500;
  const EXIT_RADIUS_M = 600; // hysteresis กันเด้งเข้าออกตรงขอบรัศมี
  const REALERT_MS = 5 * 60 * 1000;

  // id จุดเสี่ยง -> { lastAlertAt } (มี entry = ยังอยู่ในสถานะ "เตือนแล้ว")
  const alerted = new Map();

  const LEVEL_TEXT = { high: "ความเสี่ยงสูง", medium: "ความเสี่ยงปานกลาง", low: "" };

  function buildMessage(point, distance) {
    const roundedDist = Math.round(distance / 50) * 50;
    const levelText = LEVEL_TEXT[point.level] ? ` ${LEVEL_TEXT[point.level]}` : "";
    return (
      `ข้างหน้าอีกประมาณ ${roundedDist} เมตร มีจุดเสี่ยงอุบัติเหตุ${levelText} ` +
      `บริเวณ${point.road_feature !== "ไม่ระบุ" ? point.road_feature : "ถนน" + point.road} ` +
      `สาเหตุหลักคือ ${point.top_cause} โปรดขับขี่ด้วยความระมัดระวัง`
    );
  }

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
    const nearby = findNearbyPoints(lat, lng, RiskPoints.all(), EXIT_RADIUS_M);
    const nearbyIds = new Set(nearby.map((n) => n.point.id));

    // จุดที่เคยเตือนแล้วแต่ตอนนี้ออกนอกรัศมี EXIT ไปแล้ว -> รีเซ็ตให้เตือนใหม่ได้
    for (const id of alerted.keys()) {
      if (!nearbyIds.has(id)) alerted.delete(id);
    }

    // เตือนเฉพาะจุดที่ใกล้ที่สุดที่เข้าเงื่อนไข (กันพูดรัวเมื่อหลายจุดติดกัน)
    for (const { point, distance } of nearby) {
      if (distance > ALERT_RADIUS_M) continue;
      const state = alerted.get(point.id);
      if (state && now - state.lastAlertAt < REALERT_MS) continue;

      alerted.set(point.id, { lastAlertAt: now });
      const msg = buildMessage(point, distance);
      const spoken = TTS.speak(msg);
      showBanner((spoken ? "🔊 " : "⚠️ ") + msg, point.level);
      break;
    }

    updateNearestInfo(lat, lng);
  }

  /** แสดงระยะจุดเสี่ยงที่ใกล้ที่สุดใน status bar ตลอดเวลา */
  function updateNearestInfo(lat, lng) {
    const el = document.getElementById("nearest-info");
    let best = null;
    for (const p of RiskPoints.all()) {
      const d = haversineMeters(lat, lng, p.lat, p.lng);
      if (!best || d < best.d) best = { p, d };
    }
    if (best) {
      el.textContent =
        best.d < 10000
          ? `จุดเสี่ยงใกล้สุด: ${best.p.road} ${(best.d / 1000).toFixed(2)} กม.`
          : "ไม่มีจุดเสี่ยงในระยะ 10 กม.";
    }
  }

  return { onPositionUpdate, ALERT_RADIUS_M };
})();
