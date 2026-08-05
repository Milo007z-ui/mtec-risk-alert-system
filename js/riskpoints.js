/**
 * riskpoints.js — โหลด GeoJSON จุดเสี่ยงและวาดลงแผนที่
 *
 * คะแนนคำนวณล่วงหน้าฝั่ง Python ตามรอบ calibration (Fixed-Schedule) —
 * หน้าเว็บแค่แสดงผล ไม่คำนวณ percentile/Jenks สดเอง
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

  // ขนาดหมุดตามระดับ — ระดับสูงเด่นกว่าและมีวงรัศมีรอบนอกช่วยให้สังเกตเห็นก่อน
  const LEVEL_RADIUS = { high: 10, medium: 8, low: 7 };

  let points = []; // [{lat, lng, id, road, province, accident_count, ...}]
  let calibration = null; // เวอร์ชันรอบคำนวณจาก foreign member ใน GeoJSON

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
    for (const p of points) {
      const style = LEVEL_STYLE[p.level] || LEVEL_STYLE.low;

      // วงรัศมีจางรอบจุดเสี่ยงสูง — ช่วยให้กวาดสายตาเจอจุดอันตรายได้ก่อน
      if (p.level === "high") {
        L.circleMarker([p.lat, p.lng], {
          radius: 17,
          color: style.color,
          weight: 0,
          fillColor: style.color,
          fillOpacity: 0.14,
          interactive: false,
        }).addTo(map);
      }

      const marker = L.circleMarker([p.lat, p.lng], {
        radius: LEVEL_RADIUS[p.level] || LEVEL_RADIUS.low,
        color: "#fff",
        weight: 2,
        fillColor: style.color,
        fillOpacity: 0.95,
        className: "risk-marker",
      }).addTo(map);

      marker.bindPopup(buildPopupHtml(p, style), {
        maxWidth: 320,
        minWidth: 280,
        className: `risk-popup risk-popup--${p.level}`,
      });
    }
    updateLegend();
  }

  /** legend แสดงจำนวนจุดของแต่ละระดับ ให้เห็นภาพรวมโดยไม่ต้องเปิดหน้าสถิติ */
  function updateLegend() {
    const el = document.getElementById("legend");
    if (!el) return;
    const rows = ["high", "medium", "low"]
      .map((key) => {
        const count = points.filter((p) => p.level === key).length;
        return `<div class="legend-row">
            <span class="dot" style="background:${LEVEL_STYLE[key].color}"></span>
            <span class="legend-label">${LEVEL_STYLE[key].label}</span>
            <span class="legend-count">${count}</span>
          </div>`;
      })
      .join("");
    el.innerHTML = `<div class="legend-title">จุดเสี่ยง ${points.length} จุด</div>${rows}`;
  }

  /**
   * popup: Risk Score + ระดับ + สถิติ + มูลค่าความเสียหาย + Single/Multi
   * + ปัจจัยเสี่ยง + คำแนะนำขับขี่ + คำแนะนำวิศวกรรม + คะแนนย่อย 4 เกณฑ์ (Percentile)
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

    // แถบคะแนนย่อย 4 เกณฑ์ — ทุกเกณฑ์เป็น Percentile Rank 0-100 น้ำหนักเท่ากัน 25%
    // แต่ละแถบมีบรรทัดบอก "ค่าดิบ" ที่คะแนนนั้นมาจาก ให้ตรวจสอบย้อนได้ทันที
    const b = p.score_breakdown || {};
    const bars = [
      ["ความถี่", b.frequency, `${p.accident_count} ครั้งในรอบข้อมูล`],
      ["ความเสียหาย", b.economic_loss, formatBaht(p.economic_loss)],
      [
        "รถคันเดียว",
        b.single_vehicle,
        `รถคันเดียว ${single} ครั้ง · รถหลายคัน ${multi} ครั้ง (${p.single_pct}% / ${p.multi_pct}%)`,
      ],
      ["กายภาพถนน", b.geometry, p.road_feature],
    ]
      .map(
        ([name, val, note]) => `
        <div class="pp-factor">
          <span class="pp-factor-name">${name}</span>
          <span class="pp-factor-track"><span class="pp-factor-fill"
            style="width:${val || 0}%;background:${style.color}"></span></span>
          <span class="pp-factor-val">${val ?? "-"}</span>
        </div>
        <div class="pp-factor-note">${note}</div>`
      )
      .join("");

    const engAdvice = ENG_ADVICE[p.pattern] || ENG_ADVICE.mixed;
    const calibNote = calibration
      ? `คำนวณจากรอบข้อมูล ${calibration.version} · Percentile Rank + Jenks`
      : "";

    return `
      <div class="popup">
        <div class="pp-head" style="background:${style.color}">
          <div class="pp-head-main">
            <div class="pp-title">${p.road}</div>
            <div class="pp-sub-light">${p.province} · ${p.road_type} · จำกัด ~${p.speed_limit} กม./ชม.</div>
            <div class="pp-level">ความเสี่ยงระดับ${style.label}</div>
          </div>
          <div class="pp-score">${Math.round(p.risk_score)}<small>/100</small></div>
        </div>
        <div class="pp-body">
          <div class="pp-stats">
            <div><b>${p.accident_count}</b><span>อุบัติเหตุ</span></div>
            <div><b>${p.deaths}</b><span>เสียชีวิต</span></div>
            <div><b>${p.serious_injury}</b><span>สาหัส</span></div>
            <div><b>${p.minor_injury}</b><span>เล็กน้อย</span></div>
          </div>
          <div class="pp-tiles">
            <div class="pp-tile">
              <span class="pp-tile-label">💸 ความเสียหายรวม</span>
              <b>${formatBaht(p.economic_loss)}</b>
            </div>
            <div class="pp-tile">
              <span class="pp-tile-label">🚘 รูปแบบการชน</span>
              <b>คันเดียว ${single} · หลายคัน ${multi}</b>
            </div>
          </div>
          ${factors ? `<div class="pp-section">ปัจจัยเสี่ยง</div><div class="pp-chips">${factors}</div>` : ""}
          <div class="pp-advice">💡 ${advice}</div>
          <div class="pp-advice pp-advice--eng">🛠️ ${engAdvice}</div>
          <div class="pp-section">องค์ประกอบคะแนน · Percentile 0-100 × 25%</div>
          ${bars}
          ${calibNote ? `<div class="pp-calib">${calibNote}</div>` : ""}
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

  return { load, drawOnMap, all, remove, getCalibration, formatBaht, LEVEL_STYLE };
})();
