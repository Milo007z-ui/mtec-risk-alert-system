/** device.js — แสดงตำแหน่งเรียลไทม์ของอุปกรณ์ Raspberry Pi บนแผนที่ */

const DeviceTracker = (() => {
  // ปกติเว็บถูกเสิร์ฟจาก uvicorn ตัวเดียวกับ API จึงใช้ path สัมพัทธ์ได้เลย (ค่าว่าง)
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
    const noLocalApi = location.protocol === "file:" || /\.github\.io$/.test(location.hostname);
    if (noLocalApi && window.API_BASE_FALLBACK) {
      console.log(`[device] ใช้ API ที่ ${window.API_BASE_FALLBACK} (ค่าสำรองของหน้านี้)`);
      return window.API_BASE_FALLBACK;
    }
    return "";
  })();
  // Pi ส่งพิกัดขึ้นมาทุก 1 วินาที (POLL_INTERVAL_S) — ดึงที่อัตราเดียวกัน
  const POLL_MS = 1000;
  // จังหวะที่ผ่อนลงเมื่อต่อไม่ติดติดกันหลายครั้ง (เซิร์ฟเวอร์/tunnel ล่มยาว)
  const RETRY_MS = 10000;

  let map = null;
  let marker = null;
  let timer = null;
  let lastPos = null;
  let centeredOnce = false;

  // สถานะล่าสุดที่เคยแจ้งไปแล้ว ใช้เทียบกันรอบต่อรอบ จะได้ toast เฉพาะตอน "เปลี่ยน"
  let lastNotifiedState = null;

  // เคยดึงข้อมูลสำเร็จอย่างน้อย 1 ครั้งไหม — ใช้แยก "หน้านี้ไม่มี API ให้คุยด้วย"
  let everConnected = false;
  let consecutiveFails = 0;
  let pollMs = POLL_MS;

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

  /** เปลี่ยนจังหวะโพล — ต้องล้างตัวเก่าก่อนเสมอ ไม่งั้นจะมี interval ซ้อนกันหลายตัว */
  function retimer(ms) {
    if (ms === pollMs && timer !== null) return;
    pollMs = ms;
    stop();
    timer = setInterval(poll, ms);
  }

  /** ข้อความลอยแจ้งตอนอุปกรณ์เชื่อมต่อ/หลุด — สร้างเองแบบเดียวกับ statusEl() */
  function toast(text, kind) {
    let el = document.getElementById("device-toast");
    if (!el) {
      el = document.createElement("div");
      el.id = "device-toast";
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.className = `device-toast toast-${kind}`;
    el.classList.remove("hidden");
    clearTimeout(toast._timer);
    toast._timer = setTimeout(() => el.classList.add("hidden"), 5000);
  }

  /** เรียกทุกครั้งที่รู้สถานะออนไลน์/ออฟไลน์ล่าสุด — โผล่ข้อความเฉพาะตอน "เปลี่ยน" สถานะ */
  function notifyState(nextState) {
    if (nextState === lastNotifiedState) return;
    // ครั้งแรกที่เจอสถานะ searching ก็แจ้งได้ ต่างจาก offline ตรงที่มันคือข่าวดี
    const firstEver = lastNotifiedState === null;
    if (nextState === "searching") {
      toast("🔍 อุปกรณ์ทำงานอยู่ กำลังค้นหาสัญญาณดาวเทียม", "searching");
    } else if (!firstEver) {
      if (nextState === "online") toast("🚌 อุปกรณ์เชื่อมต่อแล้ว", "connect");
      else toast("⚠️ ขาดการเชื่อมต่อกับอุปกรณ์", "disconnect");
    }
    lastNotifiedState = nextState;
  }

  // ngrok แผนฟรีแทรกหน้าเตือน "You are about to visit..." ก่อนส่งคำขอถึงเซิร์ฟเวอร์จริง
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
      // ยังไม่เคยต่อติดเลยสักครั้ง = หน้านี้ไม่มี API ให้คุยด้วยจริง ๆ (เปิดจาก file://
      if (!everConnected) {
        statusEl().textContent = "";
        stop();
        return;
      }
      // เคยต่อติดแล้วเพิ่งมาพลาด = สัญญาณตกชั่วคราว ไม่ใช่ "ไม่มี API"
      consecutiveFails++;
      statusEl().textContent =
        `⚠️ อุปกรณ์: ขาดการเชื่อมต่อ (พยายามต่อใหม่... ${consecutiveFails})`;
      statusEl().className = "device-offline";
      notifyState("offline");
      updateGpsPanel("offline", null);
      if (marker) {
        marker.remove();
        marker = null;
      }
      // ถี่เท่าเดิมช่วงแรกเพื่อกลับมาให้ไวที่สุดตอนสัญญาณแค่กระพริบ แล้วค่อยผ่อนลง
      retimer(consecutiveFails <= 3 ? POLL_MS : RETRY_MS);
      return;
    }
    // กลับมาต่อติดแล้ว — คืนจังหวะโพลปกติถ้าเมื่อกี้ผ่อนไปแล้ว
    if (consecutiveFails > 0) {
      consecutiveFails = 0;
      retimer(POLL_MS);
    }
    everConnected = true;

    if (data.lat === null || data.lng === null) {
      // searching = อุปกรณ์ยังติดต่อเข้ามาอยู่ แค่ GPS ยังจับดาวไม่ได้ ต่างจากเครื่องดับ
      if (data.searching) {
        const sats = data.satellites;
        statusEl().textContent =
          `🔍 อุปกรณ์: กำลังค้นหาสัญญาณดาวเทียม${sats == null ? "" : ` · เห็นดาว ${sats} ดวง`}`;
        statusEl().className = "device-searching";
        notifyState("searching");
        updateGpsPanel("searching", data);
        if (marker) {
          marker.remove();
          marker = null;
        }
        return;
      }
      // forgotten_age_s = เคยส่งมาแล้วแต่นานจนเซิร์ฟเวอร์ลืมทิ้ง — ต่างจากไม่เคยส่งเลย
      statusEl().textContent = data.forgotten_age_s
        ? `🚌 อุปกรณ์: เงียบมา ${fmtAge(data.forgotten_age_s)}`
        : "🚌 อุปกรณ์: ยังไม่เคยส่งตำแหน่ง";
      statusEl().className = "device-offline";
      notifyState("offline");
      updateGpsPanel("offline", data);
      if (marker) {
        marker.remove();
        marker = null;
      }
      return;
    }

    lastPos = data;
    updateGpsPanel(data.online ? "online" : "stale", data);
    render(data);
  }

  /** องศา -> ทิศภาษาไทย + ตัวเลข เช่น 47 -> "ตะวันออกเฉียงเหนือ (47°)" (ช่วงองศาดู compassName ใน distance.js) */
  function compassLabel(deg) {
    return `${compassName(deg)} (${Math.round(deg)}°)`;
  }

  // มุมสะสมของลูกศร — ดูเหตุผลที่ไม่ตัดกลับเข้า 0-360 ใน MapView.setUserHeading
  let displayedHeading = 0;

  /** หมุนลูกศรบอกทิศของหมุดรถตามค่า heading ที่ Pi ส่งขึ้นมา (null = ซ่อนลูกศร) */
  function setDeviceHeading(headingDeg) {
    const dot = marker && marker.getElement()
      ? marker.getElement().querySelector(".device-dot")
      : null;
    if (!dot) return;
    const known = headingDeg !== null && headingDeg !== undefined && !Number.isNaN(headingDeg);
    dot.classList.toggle("has-heading", known);
    if (!known) return;
    let delta = (headingDeg - ((displayedHeading % 360) + 360) % 360) % 360;
    if (delta > 180) delta -= 360;
    if (delta < -180) delta += 360;
    displayedHeading += delta;
    const arrow = dot.querySelector(".device-arrow");
    if (arrow) arrow.style.transform = `rotate(${displayedHeading}deg)`;
  }

  // ---------- แผงสถานะ GPS สด ----------
  // เก็บจำนวนดาวย้อนหลัง 60 วินาที ไว้วาดกราฟเส้น จะได้เห็นว่ากำลังไต่ขึ้นหรือค้างอยู่
  const SAT_HISTORY_MAX = 60;
  const satHistory = [];
  const SAT_BARS = 12;     // ขีดเต็มแถบ = จับดาวได้ดีมากแล้ว
  let lastOkAt = null;

  const STATE_TH = {
    online: "รับสัญญาณแล้ว",
    stale: "สัญญาณขาดช่วง",
    searching: "กำลังค้นหาดาวเทียม",
    offline: "ขาดการเชื่อมต่อ",
  };

  function gpsPanel() {
    let el = document.getElementById("gps-panel");
    if (el) return el;
    const host = document.getElementById("map") || document.body;
    el = document.createElement("div");
    el.id = "gps-panel";
    el.innerHTML =
      '<div class="gp-head"><i class="gp-led"></i><span class="gp-state">กำลังเชื่อมต่อ</span></div>' +
      '<div class="gp-sats"><b class="gp-num">0</b><span>ดวงที่มองเห็น</span></div>' +
      `<div class="gp-bar">${'<i></i>'.repeat(SAT_BARS)}</div>` +
      '<svg class="gp-spark" viewBox="0 0 120 24" preserveAspectRatio="none" aria-hidden="true">' +
      '<polyline class="gp-line" fill="none" stroke="#ef6c00" stroke-width="1.5" points=""></polyline></svg>' +
      '<div class="gp-row"><span>พิกัด</span><b class="gp-fix">—</b></div>' +
      '<div class="gp-row"><span>อัปเดตเมื่อ</span><b class="gp-age">—</b></div>';
    host.appendChild(el);
    return el;
  }

  /** วาดกราฟจำนวนดาว 60 วินาทีล่าสุด — สูงสุดของแกนตั้งอย่างน้อย 8 เพื่อไม่ให้เส้นเด้งเกินจริง */
  function drawSpark(line, colour) {
    if (satHistory.length < 2) { line.setAttribute("points", ""); return; }
    const top = Math.max(8, ...satHistory);
    const step = 120 / (SAT_HISTORY_MAX - 1);
    const pts = satHistory
      .map((v, i) => `${(i + SAT_HISTORY_MAX - satHistory.length) * step},${23 - (v / top) * 22}`)
      .join(" ");
    line.setAttribute("points", pts);
    line.setAttribute("stroke", colour);
  }

  /** อัปเดตแผงทุกครั้งที่ poll เสร็จ ไม่ว่าผลจะเป็นอย่างไร */
  function updateGpsPanel(state, d) {
    const el = gpsPanel();
    el.className = `state-${state}`;
    el.querySelector(".gp-state").textContent = STATE_TH[state] || state;

    const sats = d && d.satellites != null ? d.satellites : null;
    if (state !== "offline") {
      satHistory.push(sats == null ? 0 : sats);
      if (satHistory.length > SAT_HISTORY_MAX) satHistory.shift();
      lastOkAt = Date.now();
    }
    el.querySelector(".gp-num").textContent = sats == null ? "—" : sats;

    const bars = el.querySelectorAll(".gp-bar i");
    bars.forEach((b, i) => b.classList.toggle("on", sats != null && i < sats));
    drawSpark(el.querySelector(".gp-line"),
      state === "online" ? "#2e7d32" : state === "offline" ? "#c62828" : "#ef6c00");

    el.querySelector(".gp-fix").textContent =
      state === "online" || state === "stale"
        ? `${d.lat.toFixed(5)}, ${d.lng.toFixed(5)}`
        : "ยังจับไม่ได้";
    el.querySelector(".gp-age").textContent =
      lastOkAt === null ? "—" : `${Math.round((Date.now() - lastOkAt) / 1000)} วิ`;
  }

  function render(d) {
    const latlng = [d.lat, d.lng];
    const online = d.online;

    if (!marker) {
      marker = L.marker(latlng, {
        icon: L.divIcon({
          className: "device-marker",
          // ลูกศรทิศแยกชิ้นกับตัวรถ เพื่อให้หมุนลูกศรได้โดยที่ 🚌 ยังตั้งตรงอ่านออก
          html: '<div class="device-dot"><span class="device-arrow"></span>🚌</div>',
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
    setDeviceHeading(online ? d.heading : null);
    marker.setPopupContent(popupHtml(d));

    // จัดกลางแผนที่ให้ครั้งแรกครั้งเดียว เฉพาะตอนที่ยังไม่มีหมุดตำแหน่งของเครื่องที่เปิดเว็บ
    if (!centeredOnce && !document.querySelector(".user-marker")) {
      map.setView(latlng, 16);
      centeredOnce = true;
    }

    const parts = [`🚌 อุปกรณ์: ${online ? "ออนไลน์" : `ขาดหาย ${fmtAge(d.age_s)}`}`];
    // เตือนบนแถบสถานะด้วย ไม่ใช่แค่ใน popup ที่ต้องกดหมุดก่อนถึงจะเห็น
    if (d.source === "route" || d.source === "fixed") parts.push("⚠️ ข้อมูลจำลอง");
    if (online && d.speed_kmh !== null && d.speed_kmh !== undefined) {
      parts.push(`${d.speed_kmh.toFixed(0)} กม./ชม.`);
    }
    if (online && d.heading !== null && d.heading !== undefined) {
      parts.push(`ทิศ ${compassLabel(d.heading)}`);
    }
    const el = statusEl();
    el.textContent = parts.join(" · ");
    el.className = online ? "device-online" : "device-offline";
    notifyState(online ? "online" : "offline");
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
    rows.push(["ทิศ", d.heading !== null && d.heading !== undefined
      ? compassLabel(d.heading) : "ยังไม่รู้ รอรถเคลื่อนที่"]);
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
