/**
 * riskpoints.js — โหลด GeoJSON จุดเสี่ยงและวาดลงแผนที่
 */

const RiskPoints = (() => {
  const DATA_URL = "data/risk_points_bkk_metro.geojson";

  const LEVEL_STYLE = {
    high: { color: "#c62828", label: "สูง" },
    medium: { color: "#ef6c00", label: "ปานกลาง" },
    low: { color: "#2e7d32", label: "ต่ำ" },
  };

  let points = []; // [{lat, lng, id, road, province, accident_count, deaths, ...}]

  async function load() {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`โหลดข้อมูลจุดเสี่ยงไม่สำเร็จ (HTTP ${resp.status})`);
    const geojson = await resp.json();
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
      const marker = L.circleMarker([p.lat, p.lng], {
        radius: 9,
        color: style.color,
        weight: 2,
        fillColor: style.color,
        fillOpacity: 0.5,
      }).addTo(map);

      marker.bindPopup(buildPopupHtml(p, style), { maxWidth: 300, minWidth: 260 });
    }
  }

  /** popup: Risk Score + ระดับ + สถิติ + ปัจจัยเสี่ยง + คำแนะนำ + คะแนนย่อย 4 ปัจจัย */
  function buildPopupHtml(p, style) {
    const rules = RiskRules.evaluate(p);
    const factors = rules
      .map((r) => `<span class="pp-chip">${r.icon} ${r.cause}</span>`)
      .join("");
    const advice = rules.length
      ? rules[0].advice
      : "ขับขี่ด้วยความระมัดระวังตามปกติ";

    // แถบคะแนนย่อย: (ชื่อ, คะแนนที่ได้, คะแนนเต็มของปัจจัย)
    const b = p.score_breakdown || {};
    const bars = [
      ["ความถี่", b.frequency, 30],
      ["ความรุนแรง", b.severity, 35],
      ["ลักษณะถนน", b.geometry, 20],
      ["ความเร็ว", b.speed, 15],
    ]
      .map(
        ([name, val, max]) => `
        <div class="pp-factor">
          <span class="pp-factor-name">${name}</span>
          <span class="pp-factor-track"><span class="pp-factor-fill"
            style="width:${((val || 0) / max) * 100}%;background:${style.color}"></span></span>
          <span class="pp-factor-val">${val ?? "-"}/${max}</span>
        </div>`
      )
      .join("");

    return `
      <div class="popup">
        <div class="pp-head">
          <div class="pp-title">${p.road}</div>
          <div class="pp-score" style="background:${style.color}">
            ${Math.round(p.risk_score)}<small>/100</small>
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
        ${factors ? `<div class="pp-section">ปัจจัยเสี่ยง</div><div class="pp-chips">${factors}</div>` : ""}
        <div class="pp-advice">💡 ${advice}</div>
        <div class="pp-section">องค์ประกอบคะแนน</div>
        ${bars}
      </div>`;
  }

  function all() {
    return points;
  }

  return { load, drawOnMap, all, LEVEL_STYLE };
})();
