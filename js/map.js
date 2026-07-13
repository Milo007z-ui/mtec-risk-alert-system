/**
 * map.js — ตั้งค่าแผนที่ Leaflet + marker ตำแหน่งผู้ใช้
 */

const MapView = (() => {
  const BKK_CENTER = [13.7563, 100.5018];
  let map = null;
  let userMarker = null;
  let accuracyCircle = null;
  let autoPan = true;

  function init() {
    map = L.map("map").setView(BKK_CENTER, 11);
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
        color: "#1976d2",
        weight: 1,
        fillColor: "#1976d2",
        fillOpacity: 0.12,
      }).addTo(map);
      map.setView(latlng, 16);
    } else {
      userMarker.setLatLng(latlng);
      accuracyCircle.setLatLng(latlng).setRadius(accuracyM);
      if (autoPan) map.panTo(latlng);
    }
  }

  function getMap() {
    return map;
  }

  return { init, updateUserPosition, getMap };
})();
