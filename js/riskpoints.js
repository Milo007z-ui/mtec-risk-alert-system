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

  let inspectLayer = null; // ชั้นชั่วคราวโชว์ขอบเขต+สมาชิกของคลัสเตอร์ที่กำลังเปิดดู
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

  /**
   * วาดเฉพาะ "คลัสเตอร์" (192 วง) เป็นหมุดขนาดคงที่ตามดีไซน์เดิม
   *
   * เคยลองเปลี่ยนเป็น L.circle รัศมีจริงตาม `radius_m` แล้วผู้ใช้ขอย้อนกลับ —
   * ที่ระดับซูมภาพรวมทั้งกรุงเทพฯ รัศมีจริง (มัธยฐาน 158 ม.) เล็กกว่า 2 พิกเซล
   * มองไม่เห็น ส่วนกลุ่ม chaining 4.5 กม. กลับใหญ่จนกลบพื้นที่ข้างเคียง
   * ขนาดคงที่อ่านง่ายกว่าในทุกระดับซูม (`radius_m` ยังอยู่ใน GeoJSON และแสดงในป๊อปอัป)
   *
   * หน่วยวิเคราะห์ชนิด noise (จุดเสี่ยงเดี่ยว 796 จุด) ไม่วาดที่ชั้นนี้
   * เพราะชั้นจุดเสี่ยง (accidents.js) ปิดอยู่ — แต่ยังอยู่ใน `points`
   * เพื่อให้ระบบแจ้งเตือนตรวจครบทุกคลัสเตอร์
   */
  function drawOnMap(map) {
    mapRef = map;
    markers = [];
    for (const p of points) {
      if (p.unit_type !== "cluster") continue;
      const style = LEVEL_STYLE[p.level] || LEVEL_STYLE.low;
      const layer = L.circleMarker([p.lat, p.lng], {
        radius: 9,
        color: style.color,
        weight: 2,
        fillColor: style.color,
        fillOpacity: 0.5,
      }).addTo(map);

      // สร้าง HTML ตอนคลิกเท่านั้น ไม่ต้องสร้างล่วงหน้าทั้ง 192 วง
      layer.bindPopup(() => buildPopupHtml(p, style), { maxWidth: 310, minWidth: 270 });
      // เปิดป๊อปอัป = เข้าโหมดตรวจสอบ: วาดขอบเขตจริงของคลัสเตอร์ + จุดสมาชิกทั้งหมด
      layer.on("popupopen", () => showInspect(p, style));
      layer.on("popupclose", clearInspect);
      markers.push({ point: p, layer });
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
   * Convex hull ด้วย monotone chain (Andrew 1979) — คืนลำดับจุดขอบนอกสุด
   * ใช้วาดขอบเขตจริงของคลัสเตอร์ ไม่ใช่วงกลมประมาณ เพื่อให้เห็นรูปร่างที่ DBSCAN
   * จับได้จริง รวมถึงกรณีที่กลุ่มยืดยาวตามถนน (chaining) ซึ่งวงกลมจะซ่อนไว้
   */
  function convexHull(pts) {
    if (pts.length < 3) return pts.slice();
    const s = pts.slice().sort((a, b) => a.lng - b.lng || a.lat - b.lat);
    const cross = (o, a, b) =>
      (a.lng - o.lng) * (b.lat - o.lat) - (a.lat - o.lat) * (b.lng - o.lng);
    const half = (arr) => {
      const h = [];
      for (const pt of arr) {
        while (h.length >= 2 && cross(h[h.length - 2], h[h.length - 1], pt) <= 0) h.pop();
        h.push(pt);
      }
      h.pop();
      return h;
    };
    return half(s).concat(half(s.slice().reverse()));
  }

  /**
   * โหมดตรวจสอบคลัสเตอร์ — วาดสิ่งที่พิสูจน์ได้ด้วยตาว่า DBSCAN จัดกลุ่มถูกต้อง:
   *   1. ขอบเขตจริง (convex hull) ของจุดเสี่ยงที่เป็นสมาชิกวงนี้
   *   2. จุดเสี่ยงสมาชิกทุกจุด วาดทับให้เห็นชัดว่ามีจุดไหนอยู่ในวงบ้าง
   * ต้องมี accidents.js โหลดอยู่ ถ้าไม่มีก็ข้ามไปเงียบ ๆ (แผนที่ยังใช้ได้ปกติ)
   */
  function showInspect(cluster, style) {
    clearInspect();
    if (typeof Accidents === "undefined" || !mapRef) return;
    const members = Accidents.membersOf(cluster.id);
    if (!members.length) return;

    inspectLayer = L.layerGroup().addTo(mapRef);

    const hull = convexHull(members);
    if (hull.length >= 3) {
      L.polygon(hull.map((m) => [m.lat, m.lng]), {
        color: style.color,
        weight: 2,
        dashArray: "5,4",
        fillColor: style.color,
        fillOpacity: 0.08,
        interactive: false,
      }).addTo(inspectLayer);
    }

    const dots = L.canvas({ padding: 0.3 });
    for (const m of members) {
      L.circleMarker([m.lat, m.lng], {
        renderer: dots,
        radius: 4,
        color: "#fff",
        weight: 1,
        fillColor: style.color,
        fillOpacity: 0.95,
        interactive: false,
      }).addTo(inspectLayer);
    }
  }

  function clearInspect() {
    if (inspectLayer && mapRef) mapRef.removeLayer(inspectLayer);
    inspectLayer = null;
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
        <div class="pp-inspect">🔎 กำลังแสดงขอบเขตและจุดเสี่ยง
          <b>${p.accident_count}</b> จุดที่ DBSCAN จัดเข้าวงนี้ (รัศมี ${Math.round(p.radius_m || 0)} ม.)</div>
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
    load, drawOnMap, all, remove, getCalibration, formatBaht, clearInspect,
    setFilter, visible, provinces, LEVEL_STYLE,
  };
})();
