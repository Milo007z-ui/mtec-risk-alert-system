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
      cause: (p) => `เคยมีผู้เสียชีวิต ${p.deaths} ราย`,
      advice: "ลดความเร็วและใช้ความระมัดระวังสูงสุด",
      icon: "☠️",
    },
    {
      id: "junction",
      when: (p) => /แยก|ทางร่วม/.test(p.road_feature || ""),
      cause: () => "บริเวณทางแยก/ทางร่วม",
      advice: "ชะลอความเร็ว ระวังรถตัดกระแสจราจร",
      icon: "➕",
    },
    {
      id: "u-turn",
      when: (p) => /กลับรถ/.test(p.road_feature || ""),
      cause: () => "บริเวณจุดกลับรถ",
      advice: "ระวังรถชะลอเพื่อกลับรถ เว้นระยะห่าง",
      icon: "↩️",
    },
    {
      id: "curve",
      when: (p) => /โค้ง/.test(p.road_feature || ""),
      cause: () => "บริเวณทางโค้ง",
      advice: "ลดความเร็วก่อนเข้าโค้ง งดแซง",
      icon: "〰️",
    },
    {
      id: "access-road",
      when: (p) => /เชื่อมเข้า/.test(p.road_feature || ""),
      cause: () => "ทางเชื่อมเข้าพื้นที่ข้างทาง",
      advice: "ระวังรถเข้า-ออกกะทันหัน",
      icon: "🚪",
    },
    {
      id: "speeding-cause",
      when: (p) => /เร็ว/.test(p.top_cause || ""),
      cause: () => "สถิติชี้ว่าสาเหตุหลักคือการขับเร็วเกินกำหนด",
      advice: (p) => `ใช้ความเร็วไม่เกิน ${p.speed_limit} กิโลเมตรต่อชั่วโมง`,
      icon: "🏎️",
    },
    {
      id: "rear-end",
      when: (p) => /ชนท้าย/.test(p.crash_pattern || ""),
      cause: () => "จุดนี้เกิดเหตุชนท้ายบ่อย",
      advice: "เว้นระยะห่างจากรถคันหน้าให้มากขึ้น",
      icon: "🚗",
    },
    {
      id: "rollover",
      when: (p) => /พลิกคว่ำ|ตกถนน/.test(p.crash_pattern || ""),
      cause: () => "จุดนี้เกิดเหตุรถเสียหลัก/พลิกคว่ำบ่อย",
      advice: "ลดความเร็ว จับพวงมาลัยให้มั่นคง",
      icon: "🔄",
    },
    {
      id: "high-speed-road",
      when: (p) => (p.speed_limit || 0) >= 90,
      cause: (p) => `ถนนความเร็วสูง (จำกัด ${p.speed_limit} กม./ชม.)`,
      advice: "เว้นระยะห่างและไม่เปลี่ยนช่องทางกะทันหัน",
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

  /** ข้อความเตือน (Part 3): ทางการ กระชับ ระบุสาเหตุ + คำแนะนำ */
  function buildAlertMessage(point, distanceMeters) {
    const dist = Math.round(distanceMeters / 50) * 50;
    const matched = evaluate(point);
    const top = matched[0]; // กติกาเรียงตามความสำคัญแล้ว

    if (point.level === "high") {
      return (
        `โปรดทราบ ข้างหน้าประมาณ ${dist} เมตร เป็นจุดเสี่ยงอุบัติเหตุระดับสูง` +
        (top ? ` ${top.cause} โปรด${top.advice}` : " โปรดลดความเร็วและใช้ความระมัดระวังสูงสุด")
      );
    }
    if (point.level === "medium") {
      return (
        `ข้างหน้าประมาณ ${dist} เมตร เป็นจุดเสี่ยงอุบัติเหตุระดับปานกลาง` +
        (top ? ` ${top.cause} โปรด${top.advice}` : " โปรดขับขี่ด้วยความระมัดระวัง")
      );
    }
    return `ข้างหน้าประมาณ ${dist} เมตร มีจุดเฝ้าระวังอุบัติเหตุ โปรดขับขี่ด้วยความระมัดระวัง`;
  }

  return { evaluate, buildAlertMessage };
})();
