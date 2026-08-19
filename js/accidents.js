/**
 * accidents.js — ชั้นจุดเสี่ยงรายอุบัติเหตุ (1 จุด : 1 อุบัติเหตุ, ทั้งชุด 4,460 จุด)
 *
 * แยกจาก riskpoints.js ชัดเจนตามคำศัพท์ที่ตกลงกันไว้:
 *   - จุดเสี่ยง   = อุบัติเหตุ 1 ครั้ง          -> ไฟล์นี้
 *   - คลัสเตอร์   = วงที่ DBSCAN รวมจุดเสี่ยงเข้าด้วยกัน -> riskpoints.js
 *
 * ชั้นนี้เป็น "ชั้นดูอย่างเดียว" — เริ่มต้นปิดไว้ ต้องติ๊กเปิดเองในแผงตัวกรอง
 * และ **ไม่มีผลกับการแจ้งเตือน** ระบบเตือนอ่านจาก RiskPoints.visible()
 * ซึ่งเป็นคลัสเตอร์ล้วน เปิด/ปิดชั้นนี้จึงไม่ทำให้เสียงเตือนเปลี่ยนไปเลย
 *
 * วาดด้วย Canvas renderer ไม่ใช่ SVG เพราะ 4,460 จุดเป็น element เกินกว่าที่
 * DOM จะรับไหวบนมือถือ — Canvas วาดทุกจุดลง bitmap เดียว เลื่อน/ซูมลื่นกว่ามาก
 * ข้อแลกเปลี่ยน: ไม่มี hover cursor รายจุด แต่คลิกเปิด popup ได้ตามปกติ
 */

const Accidents = (() => {
  const DATA_URL = "data/accident_points.geojson";

  // ใช้ชุดสีเดียวกับระดับความเสี่ยงของคลัสเตอร์ที่จุดนั้นสังกัด
  // จุดเสี่ยงเดี่ยว (ไม่เข้าคลัสเตอร์) ไม่ถูกจัดระดับตั้งแต่ v2568-r9 -> เทา
  const LEVEL_COLOR = { high: "#c62828", medium: "#ef6c00", low: "#2e7d32" };
  const UNCLASSIFIED_COLOR = "#9e9e9e";

  const colorOf = (p) => LEVEL_COLOR[p.level] || UNCLASSIFIED_COLOR;

  let points = [];
  let layerGroup = null;
  let renderer = null;
  let mapRef = null;
  let visibleOnMap = false; // เริ่มต้นปิด — ผู้ใช้ติ๊กเปิดเองเมื่ออยากดู

  async function load() {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`โหลดจุดเสี่ยงรายอุบัติเหตุไม่สำเร็จ (HTTP ${resp.status})`);
    const geojson = await resp.json();
    points = geojson.features.map((f) => ({
      lng: f.geometry.coordinates[0],
      lat: f.geometry.coordinates[1],
      ...f.properties,
    }));
    return points;
  }

  function drawOnMap(map) {
    mapRef = map;
    renderer = L.canvas({ padding: 0.3 });
    layerGroup = L.layerGroup();

    for (const p of points) {
      const marker = L.circleMarker([p.lat, p.lng], {
        renderer,
        radius: 3,
        color: colorOf(p),
        weight: 1,
        fillColor: colorOf(p),
        fillOpacity: 0.75,
      });
      marker.bindPopup(() => buildPopupHtml(p), { maxWidth: 280 });
      marker.__point = p;
      layerGroup.addLayer(marker);
    }

    if (visibleOnMap) layerGroup.addTo(map);
    return points.length;
  }

  /** ซ่อน/แสดงทั้งชั้น (ปุ่มติ๊กในแผงตัวกรอง) */
  function setVisible(show) {
    visibleOnMap = show;
    if (!layerGroup || !mapRef) return;
    if (show) layerGroup.addTo(mapRef);
    else layerGroup.remove();
  }

  function isVisible() {
    return visibleOnMap;
  }

  /**
   * ใช้ตัวกรองเดียวกับชั้นคลัสเตอร์ (จังหวัด + ระดับ) — ตัวกรอง "ประเภทปัญหา"
   * ไม่มีผลกับชั้นนี้ เพราะ pattern เป็นคุณสมบัติของกลุ่ม ไม่ใช่ของอุบัติเหตุเดี่ยว
   */
  function applyFilter({ province, levels }) {
    if (!layerGroup) return 0;
    let shown = 0;
    layerGroup.eachLayer((layer) => {
      const p = layer.__point;
      // จุดที่ไม่ถูกจัดระดับผ่านตัวกรองระดับเสมอ (ไม่มีระดับให้เทียบ)
      const ok =
        (!province || p.province === province) &&
        (!levels || !p.level || levels.has(p.level));
      layer.setStyle({ opacity: ok ? 1 : 0, fillOpacity: ok ? 0.75 : 0 });
      layer.options.interactive = ok;
      if (ok) shown++;
    });
    return shown;
  }

  function buildPopupHtml(p) {
    const injured = (p.serious_injury || 0) + (p.minor_injury || 0);
    const unitLabel =
      p.unit_type === "cluster"
        ? `อยู่ในคลัสเตอร์ <b>${p.unit_id}</b>`
        : "จุดเสี่ยงเดี่ยว ไม่เข้าเกณฑ์ Black Spot จึงไม่ถูกจัดระดับ";

    return `
      <div class="popup popup-acc">
        <div class="pp-title">${p.road}</div>
        <div class="pp-sub">${p.province} · ${p.road_feature}</div>
        <div class="pp-stats">
          <div><b>${p.deaths}</b><span>เสียชีวิต</span></div>
          <div><b>${p.serious_injury}</b><span>สาหัส</span></div>
          <div><b>${p.minor_injury}</b><span>เล็กน้อย</span></div>
          <div><b>${p.vehicles}</b><span>คันที่เกิดเหตุ</span></div>
        </div>
        <div class="pp-sub">ลักษณะการชน: ${p.crash_pattern}</div>
        <div class="pp-sub">มูลเหตุสันนิษฐาน: ${p.cause}</div>
        <div class="pp-sub">ผู้บาดเจ็บรวม ${injured} คน · EPDO ${p.epdo_million.toFixed(2)} ล้านบาท</div>
        <div class="pp-sub">${unitLabel}</div>
      </div>`;
  }

  function all() {
    return points;
  }

  /**
   * จุดเสี่ยงทุกจุดที่ DBSCAN จัดเข้าคลัสเตอร์นี้
   * ใช้โดยโหมดตรวจสอบคลัสเตอร์ (riskpoints.js) เพื่อยืนยันว่าวงที่วาดบนแผนที่
   * ประกอบด้วยจุดเสี่ยงจุดไหนบ้างจริง ๆ — ตรวจได้ด้วยตาว่า DBSCAN ทำงานถูกต้อง
   */
  function membersOf(unitId) {
    return points.filter((p) => p.unit_id === unitId);
  }

  return {
    load, drawOnMap, all, membersOf,
    setVisible, isVisible, applyFilter, LEVEL_COLOR,
  };
})();
