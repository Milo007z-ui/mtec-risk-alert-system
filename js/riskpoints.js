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

      marker.bindPopup(`
        <div class="popup">
          <strong>${p.road}</strong> (${p.province})<br>
          ระดับความเสี่ยง: <span style="color:${style.color};font-weight:bold">${style.label}</span><br>
          อุบัติเหตุ ${p.accident_count} ครั้ง |
          เสียชีวิต ${p.deaths} | บาดเจ็บสาหัส ${p.serious_injury} | บาดเจ็บเล็กน้อย ${p.minor_injury}<br>
          สาเหตุหลัก: ${p.top_cause}<br>
          ลักษณะบริเวณ: ${p.road_feature}
        </div>
      `);
    }
  }

  function all() {
    return points;
  }

  return { load, drawOnMap, all, LEVEL_STYLE };
})();
