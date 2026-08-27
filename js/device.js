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
 *
 * ลำดับการหาว่า API อยู่ที่ไหน:
 *   1. ?api=https://...        บน URL — ชนะทุกอย่าง ใช้ตอนสลับไปชี้ Pi เครื่องอื่นชั่วคราว
 *   2. window.API_BASE         ตั้งในหน้า HTML
 *   3. window.API_BASE_FALLBACK ใช้เฉพาะเมื่อหน้าเว็บมาจาก GitHub Pages หรือ file://
 *                              ซึ่งไม่มี API อยู่ข้าง ๆ (ตั้งไว้ใน index.html/test-nstda.html)
 *   4. path สัมพัทธ์            กรณีปกติ: เสิร์ฟจาก uvicorn ตัวเดียวกับ API
 * ทุกกรณีต้องเป็น https ถ้าหน้าเว็บเป็น https ไม่งั้นเบราว์เซอร์บล็อก (mixed content)
 */

const DeviceTracker = (() => {
  // ปกติเว็บถูกเสิร์ฟจาก uvicorn ตัวเดียวกับ API จึงใช้ path สัมพัทธ์ได้เลย (ค่าว่าง)
  //
  // แต่ถ้าเปิดหน้านี้จาก GitHub Pages ซึ่งเสิร์ฟไฟล์นิ่งอย่างเดียว ไม่มี API อยู่ด้วย
  // ต้องบอกว่า API อยู่ที่ไหนผ่าน ?api=... บน URL เช่น
  //   .../test-nstda.html?api=https://xxxx.trycloudflare.com
  // ใช้ query param แทนการ hardcode เพราะ URL ของ tunnel เปลี่ยนทุกครั้งที่รันใหม่
  // ถ้า hardcode ไว้ในไฟล์จะต้อง commit + รอ Pages deploy 1-2 นาทีทุกรอบ
  //
  // ⚠️ ต้องเป็น https:// เมื่อหน้าเว็บเป็น https (GitHub Pages) — เบราว์เซอร์บล็อก
  // การเรียก http จากหน้า https (mixed content) โดยไม่มีทางข้ามได้เลย
  const API_BASE = (() => {
    const fromUrl = new URLSearchParams(location.search).get("api");
    if (fromUrl) {
      // ตัด / ท้ายออกกัน //api/... ซึ่งบางเซิร์ฟเวอร์ตอบ 404
      const base = fromUrl.replace(/\/+$/, "");
      if (!/^https?:\/\//.test(base)) {
        console.warn(`[device] ?api= ต้องขึ้นต้นด้วย http:// หรือ https:// — ไม่รับค่า "${base}"`);
      } else {
        if (location.protocol === "https:" && base.startsWith("http://")) {
          console.warn(
            "[device] หน้านี้เป็น https แต่ ?api= เป็น http — เบราว์เซอร์จะบล็อก\n" +
              "ให้ Pi มี URL https ก่อน (ngrok/Cloudflare Tunnel)"
          );
        }
        console.log(`[device] ใช้ API ที่ ${base} (จาก ?api=)`);
        return base;
      }
    }
    if (window.API_BASE) return window.API_BASE;

    // หน้าที่ถูกเสิร์ฟจาก GitHub Pages (หรือเปิดจากไฟล์ตรง ๆ) ไม่มี API อยู่ข้าง ๆ
    // จึงต้องใช้ค่าสำรองที่หน้าเว็บตั้งไว้ ไม่งั้นยิง /api/... แล้วได้ 404 แล้วหมุดไม่ขึ้น
    // ผู้ใช้เลือกใช้ลิงก์ GitHub Pages เป็นหลัก (bookmark ในมือถือ) การบังคับให้พิมพ์
    // ?api=... ต่อท้ายทุกครั้งจึงไม่เวิร์ก — ลืมเมื่อไหร่ก็เงียบไปเฉย ๆ โดยไม่มีอะไรเตือน
    const noLocalApi = location.protocol === "file:" || /\.github\.io$/.test(location.hostname);
    if (noLocalApi && window.API_BASE_FALLBACK) {
      console.log(`[device] ใช้ API ที่ ${window.API_BASE_FALLBACK} (ค่าสำรองของหน้านี้)`);
      return window.API_BASE_FALLBACK;
    }
    return "";
  })();
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

  // ngrok แผนฟรีแทรกหน้าเตือน "You are about to visit..." ก่อนส่งคำขอถึงเซิร์ฟเวอร์จริง
  // เมื่อ User-Agent เป็นเบราว์เซอร์ ทำให้ fetch ได้ HTML กลับมาแทน JSON แล้ว resp.json()
  // โยน error -> ชั้นนี้หยุดโพลไปเงียบ ๆ โดยไม่มีอะไรบอกสาเหตุ
  //
  // การเปิดหน้าเว็บผ่าน ngrok ตรง ๆ กดผ่านหน้าเตือนครั้งเดียวแล้วได้คุกกี้ จึงไม่เจอปัญหา
  // แต่ถ้าเปิดจาก GitHub Pages แล้วชี้ ?api= มาที่ ngrok คำขอเป็นข้ามโดเมน ไม่มีคุกกี้ติดไป
  // จะโดนหน้าเตือนทุกครั้ง — header นี้คือทางที่ ngrok ให้ไว้ให้ข้าม (ค่าอะไรก็ได้)
  // ไม่มีผลข้างเคียงเมื่อไม่ได้ใช้ ngrok เพราะเซิร์ฟเวอร์อื่นแค่มองข้าม header ที่ไม่รู้จัก
  const FETCH_OPTS = {
    cache: "no-store",
    headers: { "ngrok-skip-browser-warning": "true" },
  };

  async function poll() {
    let data;
    try {
      const resp = await fetch(`${API_BASE}/api/device/location`, FETCH_OPTS);
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
