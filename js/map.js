/** map.js — ตั้งค่าแผนที่ Leaflet + marker ตำแหน่งผู้ใช้ */

const MapView = (() => {
  // หน้าเว็บตั้ง window.MAP_CENTER / window.MAP_ZOOM ไว้ก่อนโหลดสคริปต์นี้ได้
  const BKK_CENTER = [13.7563, 100.5018];
  const START_CENTER = window.MAP_CENTER || BKK_CENTER;
  const START_ZOOM = window.MAP_ZOOM || 11;
  let map = null;
  let userMarker = null;
  let accuracyCircle = null;
  let routeLine = null;
  let coneLayer = null;
  let firstFixZoom = 16;
  let displayedHeading = 0; // มุมสะสมของลูกศร (ไม่ถูกตัดกลับเข้า 0-360 โดยตั้งใจ)
  let autoPan = true;

  function init() {
    map = L.map("map").setView(START_CENTER, START_ZOOM);
    L.tileLayer("https://tile.openstreetmap.org/{z}/{x}/{y}.png", {
      maxZoom: 19,
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
    }).addTo(map);

    // ถ้าผู้ใช้ลากแผนที่เอง ให้หยุด auto-pan ชั่วคราว จนกว่าจะกดปุ่มกลับมาตามตำแหน่ง
    map.on("dragstart", () => {
      autoPan = false;
      document.getElementById("btn-recenter").classList.remove("hidden");
    });

    document.getElementById("btn-recenter").addEventListener("click", () => {
      autoPan = true;
      document.getElementById("btn-recenter").classList.add("hidden");
      if (userMarker) map.panTo(userMarker.getLatLng());
    });

    return map;
  }

  /** อัปเดตตำแหน่งผู้ใช้บนแผนที่ (สร้าง marker ครั้งแรก, ขยับครั้งถัดไป) */
  function updateUserPosition(lat, lng, accuracyM, headingDeg = null) {
    const latlng = [lat, lng];
    if (!userMarker) {
      userMarker = L.marker(latlng, {
        icon: L.divIcon({
          className: "user-marker",
          html: '<div class="user-dot"></div>',
          iconSize: [22, 22],
          iconAnchor: [11, 11],
        }),
        zIndexOffset: 1000,
      }).addTo(map);
      accuracyCircle = L.circle(latlng, {
        radius: accuracyM,
        color: "#1976d2",
        weight: 1,
        fillColor: "#1976d2",
        fillOpacity: 0.12,
      }).addTo(map);
      map.setView(latlng, firstFixZoom);
    } else {
      userMarker.setLatLng(latlng);
      accuracyCircle.setLatLng(latlng).setRadius(accuracyM);
      if (autoPan) map.panTo(latlng);
    }
    setUserHeading(headingDeg);
  }

  /** หมุนหัวลูกศรของหมุดผู้ใช้ให้ชี้ตามทิศที่รถวิ่งจริง */
  function setUserHeading(headingDeg) {
    const dot = userMarker && userMarker.getElement()
      ? userMarker.getElement().querySelector(".user-dot")
      : null;
    if (!dot) return;
    const known = headingDeg !== null && headingDeg !== undefined && !Number.isNaN(headingDeg);
    dot.classList.toggle("has-heading", known);
    if (!known) return;
    let delta = (headingDeg - ((displayedHeading % 360) + 360) % 360) % 360;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    displayedHeading += delta;
    dot.style.transform = `rotate(${displayedHeading}deg)`;
  }

  /** หาพิกัดที่อยู่ห่างจากจุดตั้งต้นตามทิศและระยะที่กำหนด (สูตร great-circle) */
  function destination(lat, lng, bearingDeg, distM) {
    const R = 6371000;
    const br = (bearingDeg * Math.PI) / 180;
    const p1 = (lat * Math.PI) / 180;
    const l1 = (lng * Math.PI) / 180;
    const dr = distM / R;
    const p2 = Math.asin(Math.sin(p1) * Math.cos(dr) + Math.cos(p1) * Math.sin(dr) * Math.cos(br));
    const l2 = l1 + Math.atan2(Math.sin(br) * Math.sin(dr) * Math.cos(p1),
                               Math.cos(dr) - Math.sin(p1) * Math.sin(p2));
    return [(p2 * 180) / Math.PI, (l2 * 180) / Math.PI];
  }

  /** วาดกรวยที่ระบบใช้กรองจุดเสี่ยง — เห็นด้วยตาว่าจุดไหนอยู่ในกรวยและจุดไหนถูกตัดออก */
  function setUserCone(lat, lng, headingDeg, coneDeg, radiusM) {
    const known = headingDeg !== null && headingDeg !== undefined && !Number.isNaN(headingDeg);
    if (!known || coneDeg >= 180) {
      if (coneLayer) { coneLayer.remove(); coneLayer = null; }
      return;
    }
    const pts = [[lat, lng]];
    const STEPS = 20;
    for (let i = 0; i <= STEPS; i++) {
      pts.push(destination(lat, lng, headingDeg - coneDeg + (2 * coneDeg * i) / STEPS, radiusM));
    }
    if (!coneLayer) {
      coneLayer = L.polygon(pts, {
        color: "#1976d2",
        weight: 1.5,
        opacity: 0.7,
        fillColor: "#1976d2",
        fillOpacity: 0.13,
        interactive: false,
      }).addTo(map);
      // ให้กรวยอยู่ใต้หมุดทั้งหมด จะได้ไม่บังจุดเสี่ยง
      if (coneLayer.bringToBack) coneLayer.bringToBack();
    } else {
      coneLayer.setLatLngs(pts);
    }
  }

  /** วาดเส้นทางที่วางแผนไว้ (ใช้ในโหมดจำลอง) เป็นเส้นประ + ซูมออกให้เห็นทางข้างหน้า */
  function drawRoute(latlngs) {
    if (!latlngs || latlngs.length < 2) return;
    if (routeLine) routeLine.remove();
    routeLine = L.polyline(latlngs, {
      color: "#1976d2",
      weight: 4,
      opacity: 0.55,
      dashArray: "8 10",
    }).addTo(map);
    firstFixZoom = 14; // ซูมออกให้เห็นถนนและจุดเสี่ยงถัดไปข้างหน้า
  }

  function getMap() {
    return map;
  }

  return { init, updateUserPosition, setUserHeading, setUserCone, drawRoute, getMap };
})();
