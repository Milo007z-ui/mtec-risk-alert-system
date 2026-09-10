/** riskrules.js — กติกา Dynamic Alert: แปลงข้อมูลจุดเสี่ยงเป็น */

const RiskRules = (() => {
  const RULES = [
    {
      id: "fatal-history",
      when: (p) => p.deaths >= 1,
      cause: (p) => `จุดนี้เคยมีผู้เสียชีวิต ${p.deaths} ราย`,
      // คำว่า "เป็นพิเศษ" สงวนไว้ให้ระดับสูงเท่านั้น — ถ้าใช้กับระดับปานกลางด้วย
      advice: (p) =>
        p.level === "high"
          ? "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
          : "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง",
      icon: "☠️",
    },
    {
      id: "junction",
      when: (p) => /แยก|ทางร่วม/.test(p.road_feature || ""),
      cause: () => "เป็นบริเวณทางแยกทางร่วม",
      advice: "ลดความเร็ว และระวังรถตัดผ่านทางแยก",
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
      // ใช้ประโยคเดียวกับ fatal-history — cause (เหตุผลใน popup) ยังต่างกันอยู่
      advice: (p) =>
        p.level === "high"
          ? "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
          : "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง",
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
      // ใช้ประโยคเดียวกับ fatal-history/single-vehicle — ดูเหตุผลที่ single-vehicle
      advice: (p) =>
        p.level === "high"
          ? "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ"
          : "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง",
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

  /** ข้อความเตือน: สุภาพ กระชับ เป็นประโยคเดียวลื่นไหล (ไม่มีวงเล็บ/ตัวย่อ ให้ TTS ไม่สะดุด) */
  function buildAlertMessage(point, distanceMeters) {
    const dist = Math.round(distanceMeters / 50) * 50;
    const matched = evaluate(point);
    const top = matched[0]; // กติกาเรียงตามความสำคัญแล้ว

    if (point.level === "high") {
      const advice = top ? top.advice : "ใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ";
      return `ข้างหน้าอีก ${dist} เมตร ใกล้จุดเสี่ยงสูง โปรด${advice}`;
    }
    if (point.level === "medium") {
      const advice = top ? top.advice : "ลดความเร็ว และขับขี่ด้วยความระมัดระวัง";
      return `ข้างหน้าอีก ${dist} เมตร ใกล้จุดเสี่ยงปานกลาง โปรด${advice}`;
    }
    return `ข้างหน้าอีก ${dist} เมตร ใกล้จุดเสี่ยงต่ำ โปรดขับขี่ด้วยความระมัดระวัง`;
  }

  return { evaluate, buildAlertMessage };
})();
