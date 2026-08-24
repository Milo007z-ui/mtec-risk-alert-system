/**
 * riskrules.js — กติกา Dynamic Alert: แปลงข้อมูลจุดเสี่ยงเป็น
 * "สาเหตุของความเสี่ยง" + "คำแนะนำการขับขี่" (ใช้ร่วมกันทั้งเสียงเตือนและ popup)
 *
 * แต่ละกติกา: when(point) เงื่อนไข, cause ข้อความสาเหตุ, advice คำแนะนำ
 * เรียงตาม priority — เสียงพูดหยิบข้อแรกที่เข้าเงื่อนไข (สั้นกระชับ)
 * ส่วน popup แสดงทุกข้อที่เข้าเงื่อนไข
 */

const RiskRules = (() => {
  const RULES = [
    {
      id: "fatal-history",
      when: (p) => p.deaths >= 1,
      cause: (p) => `จุดนี้เคยมีผู้เสียชีวิต ${p.deaths} ราย`,
      advice: "ลดความเร็ว และใช้ความระมัดระวังเป็นพิเศษ",
      icon: "☠️",
    },
    {
      id: "junction",
      when: (p) => /แยก|ทางร่วม/.test(p.road_feature || ""),
      cause: () => "เป็นบริเวณทางแยกทางร่วม",
      advice: "ชะลอความเร็ว และระวังรถตัดผ่านทางแยก",
      icon: "➕",
    },
    {
      id: "u-turn",
      when: (p) => /กลับรถ/.test(p.road_feature || ""),
      cause: () => "เป็นบริเวณจุดกลับรถ",
      advice: "เว้นระยะห่าง และระวังรถชะลอตัวเพื่อกลับรถ",
      icon: "↩️",
    },
    {
      id: "curve",
      when: (p) => /โค้ง/.test(p.road_feature || ""),
      cause: () => "เป็นช่วงทางโค้ง",
      advice: "ลดความเร็วก่อนเข้าโค้ง และงดแซงในช่วงนี้",
      icon: "〰️",
    },
    {
      id: "access-road",
      when: (p) => /เชื่อมเข้า/.test(p.road_feature || ""),
      cause: () => "มีทางเชื่อมเข้าออกพื้นที่ข้างทาง",
      advice: "ระวังรถเข้าออกพื้นที่ข้างทาง",
      icon: "🚪",
    },
    {
      id: "single-vehicle",
      when: (p) => p.pattern === "single",
      cause: () => "จุดนี้มักเกิดเหตุรถเสียหลักออกนอกเส้นทาง",
      advice: "ลดความเร็ว และประคองพวงมาลัยให้มั่นคง",
      icon: "🛞",
    },
    {
      id: "multi-vehicle",
      when: (p) => p.pattern === "multiple",
      cause: () => "จุดนี้มักเกิดเหตุรถหลายคันชนกัน",
      advice: "เว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง",
      icon: "🚦",
    },
    {
      id: "speeding-cause",
      when: (p) => /เร็ว/.test(p.top_cause || ""),
      cause: () => "สาเหตุหลักมาจากการใช้ความเร็วเกินกำหนด",
      advice: (p) => `ใช้ความเร็วไม่เกิน ${p.speed_limit} กิโลเมตรต่อชั่วโมง`,
      icon: "🏎️",
    },
    {
      id: "rear-end",
      when: (p) => /ชนท้าย/.test(p.crash_pattern || ""),
      cause: () => "จุดนี้เกิดเหตุชนท้ายบ่อยครั้ง",
      advice: "เว้นระยะห่างจากรถคันหน้าให้มากขึ้น",
      icon: "🚗",
    },
    {
      id: "rollover",
      when: (p) => /พลิกคว่ำ|ตกถนน/.test(p.crash_pattern || ""),
      cause: () => "จุดนี้เกิดเหตุรถพลิกคว่ำบ่อยครั้ง",
      advice: "ลดความเร็ว และประคองพวงมาลัยให้มั่นคง",
      icon: "🔄",
    },
    {
      id: "high-speed-road",
      when: (p) => (p.speed_limit || 0) >= 90,
      cause: () => "เป็นถนนที่ใช้ความเร็วสูง",
      advice: "เว้นระยะห่าง และหลีกเลี่ยงการเปลี่ยนช่องทางกะทันหัน",
      icon: "⚡",
    },
  ];

  /** คืนรายการ {cause, advice, icon} ทุกข้อที่เข้าเงื่อนไขของจุดนี้ */
  function evaluate(point) {
    const val = (v) => (typeof v === "function" ? v(point) : v);
    return RULES.filter((r) => r.when(point)).map((r) => ({
      id: r.id,
      cause: val(r.cause),
      advice: val(r.advice),
      icon: r.icon,
    }));
  }

  /**
   * ข้อความเตือน: สุภาพ กระชับ เป็นประโยคเดียวลื่นไหล (ไม่มีวงเล็บ/ตัวย่อ ให้ TTS ไม่สะดุด)
   *
   * ไม่พูดชื่อระดับตรงๆ ("ระดับสูง/ปานกลาง/ต่ำ") เพราะสื่อความเร่งด่วนด้วยน้ำหนักคำแทน
   * ซึ่งสั้นกว่าและฟังเป็นธรรมชาติกว่า — ระดับสูงเติม "มีจุดอันตราย" นำหน้าคำแนะนำ
   * ระดับปานกลางขึ้นคำแนะนำเลย ระดับต่ำใช้โทนขอความร่วมมือเบาที่สุด
   * (ผู้ขับแยกระดับได้อีกทางจากลายเสียงเตือนนำใน tts.js และสีแบนเนอร์ใน style.css)
   */
  function buildAlertMessage(point, distanceMeters) {
    const dist = Math.round(distanceMeters / 50) * 50;
    const matched = evaluate(point);
    const top = matched[0]; // กติกาเรียงตามความสำคัญแล้ว

    if (point.level === "high") {
      const advice = top ? top.advice : "ลดความเร็ว และใช้ความระมัดระวังเป็นพิเศษ";
      return `ข้างหน้าอีกประมาณ ${dist} เมตร มีจุดอันตราย กรุณา${advice}`;
    }
    if (point.level === "medium") {
      const advice = top ? top.advice : "ชะลอความเร็ว และขับขี่ด้วยความระมัดระวัง";
      return `ข้างหน้าอีกประมาณ ${dist} เมตร กรุณา${advice}`;
    }
    return `ข้างหน้าอีกประมาณ ${dist} เมตร ขอให้ขับขี่ด้วยความระมัดระวัง`;
  }

  return { evaluate, buildAlertMessage };
})();
