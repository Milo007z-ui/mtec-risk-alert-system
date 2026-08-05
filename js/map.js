/**
 * map.js — ตั้งค่าแผนที่ Leaflet + marker ตำแหน่งผู้ใช้
 */

const MapView = (() => {
  const BKK_CENTER = [13.7563, 100.5018];
  let map = null;
  let userMarker = null;
  let accuracyCircle = null;
  let routeLine = null;
  let firstFixZoom = 16;
  let autoPan = true;

  function init() {
    map = L.map("map").setView(BKK_CENTER, 11);

    // แผนที่ฐานโทนอ่อน (CARTO Positron) — สีถนนไม่แย่งสายตา ทำให้หมุดสีแดง/ส้ม/เขียวเด่นชัด
    L.tileLayer("https://{s}.basemaps.cartocdn.com/rastertiles/light_all/{z}/{x}/{y}{r}.png", {
      maxZoom: 19,
      subdomains: "abcd",
      attribution:
        '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> &copy; ' +
        '<a href="https://carto.com/attributions">CARTO</a>',
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
  function updateUserPosition(lat, lng, accuracyM) {
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
        color: "#1e88e5",
        weight: 1,
        fillColor: "#1e88e5",
        fillOpacity: 0.1,
      }).addTo(map);
      map.setView(latlng, firstFixZoom);
    } else {
      userMarker.setLatLng(latlng);
      accuracyCircle.setLatLng(latlng).setRadius(accuracyM);
      if (autoPan) map.panTo(latlng);
    }
  }

  /** วาดเส้นทางที่วางแผนไว้ (ใช้ในโหมดจำลอง) เป็นเส้นประ + ซูมออกให้เห็นทางข้างหน้า */
  function drawRoute(latlngs) {
    if (!latlngs || latlngs.length < 2) return;
    if (routeLine) routeLine.remove();
    routeLine = L.polyline(latlngs, {
      color: "#1e88e5",
      weight: 5,
      opacity: 0.5,
      dashArray: "9 11",
      lineCap: "round",
    }).addTo(map);
    firstFixZoom = 14; // ซูมออกให้เห็นถนนและจุดเสี่ยงถัดไปข้างหน้า
  }

  function getMap() {
    return map;
  }

  return { init, updateUserPosition, drawRoute, getMap };
})();
