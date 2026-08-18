/**
 * riskpoints.js — โหลด GeoJSON จุดเสี่ยงและวาดลงแผนที่
 *
 * คะแนนคำนวณล่วงหน้าฝั่ง Python ตามรอบ calibration (Fixed-Schedule) —
 * หน้าเว็บแค่แสดงผล ไม่ให้คะแนน/จัดระดับสดเอง
 */

const RiskPoints = (() => {
  const DATA_URL = "data/risk_points_bkk_metro.geojson";

  const LEVEL_STYLE = {
    high: { color: "#c62828", label: "สูง" },
    medium: { color: "#ef6c00", label: "ปานกลาง" },
    low: { color: "#2e7d32", label: "ต่ำ" },
  };

  // คำแนะนำเชิงวิศวกรรมตามรูปแบบปัญหาเด่นของจุด (Single vs Multiple Vehicle)
  const ENG_ADVICE = {
    single:
      "ป้องกันรถหลุดออกนอกทาง: เส้นสั่นเตือนขอบทาง (rumble strips) · ราวกันอันตราย · ป้าย/ไฟเตือนแนวโค้ง · ปรับปรุงไหล่ทาง",
    multiple:
      "ลดความขัดแย้งกระแสจราจร: ปรับจังหวะสัญญาณไฟ · เพิ่มช่องรอเลี้ยว · จัดการจุดตัด/จุดกลับรถ · เพิ่มทัศนวิสัยบริเวณทางแยก",
    mixed:
      "รูปแบบผสม: บังคับใช้กฎหมายความเร็ว · ทบทวนป้าย/เครื่องหมายจราจรและกายภาพถนนโดยรวม",
  };

  let points = []; // [{lat, lng, id, road, province, accident_count, ...}]
  let calibration = null; // เวอร์ชันรอบคำนวณจาก foreign member ใน GeoJSON
  let markers = []; // [{point, layer}] เก็บไว้เพื่อซ่อน/แสดงตามตัวกรอง
  let mapRef = null;

  // ตัวกรองที่ใช้อยู่ — ค่าเริ่มต้นคือแสดงทุกจุด
  let filter = {
    province: "", // "" = ทุกจังหวัด
    levels: new Set(["high", "medium", "low"]),
    pattern: "", // "" = ทุกประเภทปัญหา
  };

  /**
   * จำนวนเงินเป็นหน่วยไทยที่อ่านออกทันที — 58,000 -> "5.8 หมื่นบาท",
   * 500,000 -> "5 แสนบาท", 6,700,000 -> "6.7 ล้านบาท"
   */
  function formatBaht(value) {
    const v = Math.round(value || 0);
    if (v === 0) return "ไม่มีผู้บาดเจ็บหรือเสียชีวิต";
    const units = [
      [1e9, "พันล้าน"],
      [1e6, "ล้าน"],
      [1e5, "แสน"],
      [1e4, "หมื่น"],
      [1e3, "พัน"],
    ];
    for (const [size, name] of units) {
      if (v >= size) {
        const n = (v / size).toLocaleString("th-TH", { maximumFractionDigits: 1 });
        return `${n} ${name}บาท`;
      }
    }
    return `${v.toLocaleString("th-TH")} บาท`;
  }

  async function load() {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`โหลดข้อมูลจุดเสี่ยงไม่สำเร็จ (HTTP ${resp.status})`);
    const geojson = await resp.json();
    calibration = geojson.calibration || null;
    points = geojson.features.map((f) => ({
      lng: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
      ...f.properties,
    }));
    return points;
  }

  function drawOnMap(map) {
    mapRef = map;
    markers = [];
    for (const p of points) {
      const style = LEVEL_STYLE[p.level] || LEVEL_STYLE.low;
      const marker = L.circleMarker([p.lat, p.lng], {
        radius: 9,
        color: style.color,
        weight: 2,
        fillColor: style.color,
        fillOpacity: 0.5,
      }).addTo(map);

      // สร้าง HTML ตอนคลิกเท่านั้น — ตั้งแต่รอบ v2568-r7 มีจุดเสี่ยง 1,234 จุด
      // ถ้าสร้างล่วงหน้าทั้งหมดจะหน่วงตอนเปิดแผนที่โดยที่ผู้ใช้ดูแค่ไม่กี่จุด
      marker.bindPopup(() => buildPopupHtml(p, style), { maxWidth: 310, minWidth: 270 });
      markers.push({ point: p, layer: marker });
    }
  }

  /** จุดนี้ผ่านเงื่อนไขตัวกรองปัจจุบันหรือไม่ */
  function matchesFilter(p) {
    if (filter.province && p.province !== filter.province) return false;
    if (!filter.levels.has(p.level)) return false;
    if (filter.pattern && p.pattern !== filter.pattern) return false;
    return true;
  }

  /**
   * ตั้งค่าตัวกรองแล้วซ่อน/แสดงหมุดให้ตรงกัน
   * ตัวกรองมีผลกับการแจ้งเตือนด้วย (alert.js อ่านจาก visible()) เพื่อให้
   * "เห็นอะไรบนแผนที่ = ได้ยินเตือนเรื่องนั้น" ไม่สับสน
   */
  function setFilter(next) {
    filter = {
      province: next.province || "",
      levels: new Set(next.levels && next.levels.length ? next.levels : []),
      pattern: next.pattern || "",
    };

    for (const { point, layer } of markers) {
      const show = matchesFilter(point);
      const on = mapRef.hasLayer(layer);
      if (show && !on) layer.addTo(mapRef);
      else if (!show && on) layer.remove();
    }
    return visible().length;
  }

  /** จุดที่ผ่านตัวกรอง (ใช้ทั้งวาดแผนที่และตรวจแจ้งเตือน) */
  function visible() {
    return points.filter(matchesFilter);
  }

  /** รายชื่อจังหวัดในข้อมูล เรียงตามพจนานุกรมไทย (ใช้เติม dropdown) */
  function provinces() {
    return [...new Set(points.map((p) => p.province))].sort((a, b) =>
      a.localeCompare(b, "th")
    );
  }

  /**
   * popup: Severity Index + ระดับ + สถิติ + มูลค่าความเสียหาย + Single/Multi
   * + ปัจจัยเสี่ยง + คำแนะนำขับขี่ + คำแนะนำวิศวกรรม + ที่มาของค่า SI
   */
  function buildPopupHtml(p, style) {
    const rules = RiskRules.evaluate(p);
    const factors = rules
      .map((r) => `<span class="pp-chip">${r.icon} ${r.cause}</span>`)
      .join("");
    const advice = rules.length
      ? rules[0].advice
      : "ขับขี่ด้วยความระมัดระวังตามปกติ";

    const single = p.single_count ?? 0;
    const multi = p.multi_count ?? 0;
    const si = p.severity_index ?? 0;

    // ที่มาของค่า SI แบบกางสูตรให้เห็นตัวตั้งจริง เพราะ SI เป็นค่าเฉลี่ยต่อครั้ง
    // ตัวเลขเดียวจึงไม่บอกว่ามาจากจุดที่เกิดถี่แต่เบา หรือเกิดน้อยครั้งแต่หนัก
    const fatal = p.fatal_crashes ?? 0;
    const injured = p.injured_total ?? 0;
    const n = p.accident_count ?? 1;

    return `
      <div class="popup">
        <div class="pp-head">
          <div class="pp-title">${p.road}</div>
          <div class="pp-score" style="background:${style.color}">
            ${si.toFixed(2)}<small>SI</small>
          </div>
        </div>
        <div class="pp-sub">${p.province} · ${p.road_type} · จำกัด ~${p.speed_limit} กม./ชม.</div>
        <div class="pp-levelrow">ระดับความเสี่ยง:
          <span class="pp-level" style="background:${style.color}">${style.label}</span>
        </div>
        <div class="pp-stats">
          <div><b>${p.accident_count}</b><span>อุบัติเหตุ</span></div>
          <div><b>${p.deaths}</b><span>เสียชีวิต</span></div>
          <div><b>${p.serious_injury}</b><span>สาหัส</span></div>
          <div><b>${p.minor_injury}</b><span>เล็กน้อย</span></div>
        </div>
        <div class="pp-sub">💸 ความเสียหายรวม ${formatBaht(p.economic_loss)} ·
          🚘 คันเดียว ${single} ครั้ง / หลายคัน ${multi} ครั้ง</div>
        ${factors ? `<div class="pp-section">ปัจจัยเสี่ยง</div><div class="pp-chips">${factors}</div>` : ""}
        <div class="pp-advice">💡 ${advice}</div>
        <div class="pp-advice">🛠️ ${ENG_ADVICE[p.pattern] || ENG_ADVICE.mixed}</div>
        <div class="pp-section">ที่มาของดัชนีความรุนแรง</div>
        <div class="pp-formula">
          SI = (ครั้งที่มีผู้เสียชีวิต ${fatal} + ผู้บาดเจ็บ ${injured} คน) ÷ อุบัติเหตุ ${n} ครั้ง
          = <b>${si.toFixed(2)}</b>
        </div>
        <div class="pp-sub">เกณฑ์: ต่ำ SI &lt; 1 · ปานกลาง 1–2 · สูง SI ≥ 2</div>
        ${buildSplitHtml(p, single, multi)}
      </div>`;
  }

  /**
   * แถบเทียบสัดส่วนรถคันเดียว vs รถหลายคันของคลัสเตอร์ พร้อมจำนวนครั้งจริง
   * ตัวเลข % ในแถบจะซ่อนเมื่อช่วงแคบเกินไป (ตัวเลขเต็มอยู่ในบรรทัดใต้แถบแล้ว)
   */
  function buildSplitHtml(p, single, multi) {
    const singlePct = p.single_pct ?? 0;
    const multiPct = p.multi_pct ?? 0;
    const label = (pct) => (pct >= 18 ? `${Math.round(pct)}%` : "");

    return `
      <div class="pp-split">
        <div class="pp-split-bar">
          <span class="pp-split-seg pp-split-single" style="width:${singlePct}%">${label(singlePct)}</span>
          <span class="pp-split-seg pp-split-multi" style="width:${multiPct}%">${label(multiPct)}</span>
        </div>
        <div class="pp-split-legend">
          <span><i class="pp-sw pp-sw-single"></i>รถคันเดียว <b>${single}</b> ครั้ง (${Math.round(singlePct)}%)</span>
          <span><i class="pp-sw pp-sw-multi"></i>รถหลายคัน <b>${multi}</b> ครั้ง (${Math.round(multiPct)}%)</span>
        </div>
      </div>`;
  }

  function all() {
    return points;
  }

  function getCalibration() {
    return calibration;
  }

  /** เอาจุดเสี่ยงตาม id ออกจากชุดข้อมูลในหน่วยความจำ (ไม่แตะไฟล์ต้นฉบับ) */
  function remove(ids) {
    if (!ids || !ids.length) return;
    const drop = new Set(ids);
    points = points.filter((p) => !drop.has(p.id));
  }

  return {
    load, drawOnMap, all, remove, getCalibration, formatBaht,
    setFilter, visible, provinces, LEVEL_STYLE,
  };
})();
