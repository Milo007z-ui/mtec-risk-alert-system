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
      // โหมดจำลอง = หมุดนี้คือรถ · ใช้จริง = เครื่องที่เปิดเว็บ (คอม/มือถือ) แสดงเป็นจุดฟ้า
      // ไม่ให้สับสนกับ 🚌 ของ Raspberry Pi บนรถ (device.js)
      const isCar = typeof GPS !== "undefined" && GPS.isMockMode();
      userMarker = L.marker(latlng, {
        icon: L.divIcon({
          className: "user-marker",
          html: isCar
            ? '<div class="user-dot"><span class="user-arrow"></span>🚌</div>'
            : '<div class="user-dot viewer"><span class="user-arrow"></span></div>',
          iconSize: [30, 30],
          iconAnchor: [15, 15],
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
    const arrow = dot.querySelector(".user-arrow");
    if (arrow) arrow.style.transform = `rotate(${displayedHeading}deg)`;
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

  // สีพัดแต่ละโซน แบบภาพ ADAS: ไกล = น้ำเงินเข้ม · กลาง = ฟ้า · ใกล้ = เหลือง (วาดไกลก่อน ใกล้ทับบนสุด)
  const CONE_STYLES = [
    { color: "#1a3f8f", fillOpacity: 0.16 },  // ไกล
    { color: "#29a3e0", fillOpacity: 0.22 },  // กลาง
    { color: "#f5c518", fillOpacity: 0.30 },  // ใกล้
  ];

  /** พัดหนึ่งอันจากตัวรถ: มุม ±deg ยาว lenM */
  function fanPoints(lat, lng, headingDeg, deg, lenM) {
    const pts = [[lat, lng]];
    const STEPS = Math.max(8, Math.round(deg / 2));
    for (let i = 0; i <= STEPS; i++) {
      pts.push(destination(lat, lng, headingDeg - deg + (2 * deg * i) / STEPS, lenM));
    }
    return pts;
  }

  /**
   * วาดกรวยที่ระบบใช้กรองจุดเสี่ยง — เห็นด้วยตาว่าจุดไหนอยู่ในกรวยและจุดไหนถูกตัดออก
   * coneDegAt(d) = มุมกรวยที่ระยะ d · zoneEdgesM = ระยะรอยต่อโซน [ใกล้|กลาง, กลาง|ไกล]
   * กรวย 3 ระดับวาดเป็นพัด 3 อันซ้อนกันจากตัวรถ (แบบภาพ ADAS) — พื้นที่รวมเท่ากับที่ใช้ตัดสินจริง
   * เป็น factory: ชุดของรถจำลอง (หมุดผู้ใช้) กับของ Raspberry Pi แยกกัน ไม่ลบกันเอง
   */
  function makeCone() {
    let layers = []; // พัดกรวยกรองทิศ: [ไกล, กลาง, ใกล้]
    return function (lat, lng, headingDeg, coneDegAt, radiusM, zoneEdgesM = []) {
      const known = headingDeg !== null && headingDeg !== undefined && !Number.isNaN(headingDeg);
      if (!known || coneDegAt(radiusM) >= 180) {
        layers.forEach((l) => l.remove());
        layers = [];
        return;
      }
      // มุมเท่ากันทุกโซน (กรวยชั้นเดียว) -> วาดพัดอันเดียว ไม่ซ้อน 3 ชั้นสีเดียวกัน
      const single = coneDegAt(0) === coneDegAt(radiusM);
      const [nearEdge = radiusM, midEdge = radiusM] = single ? [] : zoneEdgesM;
      // [โซน, ความยาวพัด, ระยะกลางโซนไว้ถามมุม] — โซนที่เริ่มเลยรัศมีเตือนไปแล้วไม่ต้องวาด
      // (สนามทดสอบรัศมี 40 ม. อยู่ในโซนใกล้ทั้งหมด จึงเหลือพัดเดียว)
      const fans = [
        [0, radiusM, (midEdge + radiusM) / 2, midEdge < radiusM],
        [1, Math.min(midEdge, radiusM), (nearEdge + midEdge) / 2, nearEdge < radiusM],
        [2, Math.min(nearEdge, radiusM), nearEdge / 2, true],
      ].filter((f) => f[3]);
      if (layers.length !== fans.length) {
        layers.forEach((l) => l.remove());
        layers = [];
      }
      fans.forEach(([zone, lenM, probeM], i) => {
        const pts = fanPoints(lat, lng, headingDeg, coneDegAt(probeM), lenM);
        if (!layers[i]) {
          const st = CONE_STYLES[zone];
          layers[i] = L.polygon(pts, {
            color: st.color,
            weight: 1,
            opacity: 0.8,
            fillColor: st.color,
            fillOpacity: st.fillOpacity,
            interactive: false,
          }).addTo(map);
        } else {
          layers[i].setLatLngs(pts);
        }
      });
      // ให้กรวยอยู่ใต้หมุดทั้งหมด จะได้ไม่บังจุดเสี่ยง (ไล่จากใกล้ไปไกล พัดไกลจึงอยู่ล่างสุด)
      for (let i = layers.length - 1; i >= 0; i--) {
        if (layers[i].bringToBack) layers[i].bringToBack();
      }
    };
  }
  const setUserCone = makeCone();   // รถในโหมดจำลอง
  const setDeviceCone = makeCone(); // Raspberry Pi บนรถ — ใช้ทิศที่ Pi ส่งมา

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

  return { init, updateUserPosition, setUserHeading, setUserCone, setDeviceCone, drawRoute, getMap };
})();
