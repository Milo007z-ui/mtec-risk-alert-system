/**
 * device.js — แสดงตำแหน่งเรียลไทม์ของอุปกรณ์ Raspberry Pi บนแผนที่
 *
 * ต่างจาก gps.js ตรงที่ gps.js ติดตาม "ตำแหน่งของเครื่องที่เปิดเว็บอยู่" (มือถือในมือเรา)
 * ส่วนไฟล์นี้ติดตาม "ตำแหน่งของกล่อง Raspberry Pi ที่ติดอยู่บนรถ" ซึ่งเป็นคนละเครื่องกัน
 * ทำให้เปิดมือถือดูได้ว่ารถอยู่ไหนโดยไม่ต้องนั่งอยู่บนรถคันนั้น
 *
 * ทางเดินข้อมูล:
 *   Pi (GPS BE-609U) --POST--> /api/device/location --GET--> หน้านี้ --> หมุด 🚌 บนแผนที่
 *
 * ทำงานได้ทุกหน้าและทุกโหมด (แผนที่จริง / ?mock=1 / test-nstda.html) เพราะเป็นชั้นข้อมูล
 * อิสระ ไม่ยุ่งกับ GPS.start() หรือระบบเตือน — โหมดจำลองของเว็บกับตำแหน่ง Pi จริง
 * จึงแสดงพร้อมกันได้ (หมุดน้ำเงิน = เว็บ, หมุด 🚌 = Pi)
 *
 * ปิดชั้นนี้ด้วย ?device=0 บน URL ถ้าไม่ได้เสียบอุปกรณ์แล้วไม่อยากเห็นป้าย "ออฟไลน์"
 */

const DeviceTracker = (() => {
  // เว็บถูกเสิร์ฟจาก uvicorn ตัวเดียวกับ API อยู่แล้ว จึงใช้ path สัมพัทธ์ได้เลย
  // ตั้ง window.API_BASE ไว้ก่อนโหลดสคริปต์นี้ได้ ถ้าเปิดเว็บจากที่อื่น (เช่น Live Server)
  const API_BASE = window.API_BASE || "";
  const POLL_MS = 2000; // ถี่กว่า Pi ที่ส่งทุก 3 วิ เพื่อให้หน่วงรวมไม่เกิน ~1 รอบ

  let map = null;
  let marker = null;
  let timer = null;
  let lastPos = null;
  let centeredOnce = false;

  const SOURCE_LABEL = {
    serial: "GPS จริง",
    gpsd: "GPS จริง (gpsd)",
    route: "เส้นทางจำลอง",
    fixed: "พิกัดทดสอบคงที่",
  };

  function isEnabled() {
    return new URLSearchParams(location.search).get("device") !== "0";
  }

  /** ป้ายสถานะในแถบบน — สร้างเองแทนที่จะแก้ HTML ทุกหน้า จะได้ไม่ต้องซิงก์หลายไฟล์ */
  function statusEl() {
    let el = document.getElementById("device-status");
    if (!el) {
      el = document.createElement("span");
      el.id = "device-status";
      const bar = document.getElementById("status-bar");
      const link = bar && bar.querySelector("a");
      if (link) bar.insertBefore(el, link);
      else if (bar) bar.appendChild(el);
    }
    return el;
  }

  function start(leafletMap) {
    map = leafletMap;
    if (!isEnabled()) return;
    poll();
    timer = setInterval(poll, POLL_MS);
  }

  function stop() {
    if (timer !== null) clearInterval(timer);
    timer = null;
  }

  async function poll() {
    let data;
    try {
      const resp = await fetch(`${API_BASE}/api/device/location`, { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
    } catch (err) {
      // เปิดเว็บจาก file:// หรือ static server ที่ไม่มี API — ไม่ใช่ความผิดพลาดของผู้ใช้
      // แค่ไม่มีชั้นนี้ให้ดู เลยเงียบไว้แล้วหยุดโพล ไม่ต้องรัวคำเตือนใน console ทุก 2 วิ
      statusEl().textContent = "";
      stop();
      return;
    }

    if (data.lat === null || data.lng === null) {
      statusEl().textContent = "🚌 อุปกรณ์: ยังไม่เคยส่งตำแหน่ง";
      statusEl().className = "device-offline";
      return;
    }

    lastPos = data;
    render(data);
  }

  function render(d) {
    const latlng = [d.lat, d.lng];
    const online = d.online;

    if (!marker) {
      marker = L.marker(latlng, {
        icon: L.divIcon({
          className: "device-marker",
          html: '<div class="device-dot">🚌</div>',
          iconSize: [30, 30],
          iconAnchor: [15, 15],
        }),
        // สูงกว่าหมุดผู้ใช้ (1000) เพราะเป็นสิ่งที่เปิดหน้านี้มาดูโดยเฉพาะ
        zIndexOffset: 1200,
      }).addTo(map);
      marker.bindPopup("");
    } else {
      marker.setLatLng(latlng);
    }

    marker.getElement()?.classList.toggle("device-stale", !online);
    marker.setPopupContent(popupHtml(d));

    // จัดกลางแผนที่ให้ครั้งแรกครั้งเดียว เฉพาะตอนที่ยังไม่มีหมุดตำแหน่งของเครื่องที่เปิดเว็บ
    // (เปิดจากมือถือที่บ้าน/ไม่ได้กดอนุญาตตำแหน่ง) — ถ้าจัดกลางทุกรอบจะลากแผนที่ดูที่อื่นไม่ได้
    if (!centeredOnce && !document.querySelector(".user-marker")) {
      map.setView(latlng, 16);
      centeredOnce = true;
    }

    const parts = [`🚌 อุปกรณ์: ${online ? "ออนไลน์" : `ขาดหาย ${fmtAge(d.age_s)}`}`];
    if (online && d.speed_kmh !== null && d.speed_kmh !== undefined) {
      parts.push(`${d.speed_kmh.toFixed(0)} กม./ชม.`);
    }
    const el = statusEl();
    el.textContent = parts.join(" · ");
    el.className = online ? "device-online" : "device-offline";
  }

  function fmtAge(s) {
    if (s === null || s === undefined) return "";
    if (s < 60) return `${Math.round(s)} วิ`;
    if (s < 3600) return `${Math.round(s / 60)} นาที`;
    return `${(s / 3600).toFixed(1)} ชม.`;
  }

  function popupHtml(d) {
    const rows = [
      ["สถานะ", d.online ? "🟢 ออนไลน์" : `🔴 ไม่ตอบสนอง ${fmtAge(d.age_s)}`],
      ["พิกัด", `${d.lat.toFixed(6)}, ${d.lng.toFixed(6)}`],
    ];
    if (d.speed_kmh !== null && d.speed_kmh !== undefined) {
      rows.push(["ความเร็ว", `${d.speed_kmh.toFixed(1)} กม./ชม.`]);
    }
    if (d.satellites !== null && d.satellites !== undefined) {
      rows.push(["ดาวเทียม", `${d.satellites} ดวง`]);
    }
    if (d.source) rows.push(["แหล่งพิกัด", SOURCE_LABEL[d.source] || d.source]);
    rows.push(["อัปเดตล่าสุด", `${fmtAge(d.age_s)}ที่แล้ว`]);

    const body = rows
      .map(([k, v]) => `<tr><td>${k}</td><td><b>${v}</b></td></tr>`)
      .join("");
    return `<div class="device-popup"><h4>🚌 Raspberry Pi บนรถ</h4><table>${body}</table></div>`;
  }

  return { start, stop, isEnabled, lastPosition: () => lastPos };
})();
