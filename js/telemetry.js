/** telemetry.js — แผงตัวเลขสดมุมซ้ายของแผนที่ (โหมดจำลอง) */

const Telemetry = (() => {
  let box = null;
  let startedAt = null;
  let distM = 0;
  let lastLat = null;
  let lastLng = null;

  function enabled() {
    return new URLSearchParams(location.search).get("hud") !== "0";
  }

  function build() {
    if (box) return box;
    box = document.createElement("div");
    box.id = "telemetry";
    box.innerHTML =
      '<div class="tm-card">' +
        '<h3>ความเร็ว</h3>' +
        '<div class="tm-big" id="tm-spd">0<small>กม./ชม.</small></div>' +
        '<div class="tm-kv"><span>ระยะที่ขับแล้ว</span><b id="tm-dist">0.00 กม.</b></div>' +
        '<div class="tm-kv"><span>เวลาเดินทาง</span><b id="tm-clk">00:00</b></div>' +
      '</div>' +
      '<div class="tm-card">' +
        '<h3>ทิศทาง COG</h3>' +
        '<div class="tm-big" id="tm-cog">—<small>°</small></div>' +
        '<div class="tm-kv"><span>ดิบจากโมดูล</span><b id="tm-raw">—</b></div>' +
        '<div class="tm-kv"><span>หลังเฉลี่ยวน</span><b id="tm-err">—</b></div>' +
      '</div>' +
      '<div class="tm-card">' +
        '<h3 id="tm-head3">จุดในระยะ 500 ม.</h3>' +
        '<div class="tm-kv"><span>ไม่กรองทิศ</span><b id="tm-off">0</b></div>' +
        '<div class="tm-kv"><span>กรวย ±90°</span><b id="tm-c90">0</b></div>' +
        '<div class="tm-kv tm-pick"><span id="tm-lbl30">กรวย ±30°</span><b id="tm-c30">0</b></div>' +
      '</div>' +
      '<div class="tm-card">' +
        '<h3>เสียง beep</h3>' +
        '<div class="tm-kv"><span>จังหวะ</span><b id="tm-beep">เงียบ</b></div>' +
        '<div class="tm-kv"><span>เพราะจุด</span><b id="tm-beepfrom">—</b></div>' +
      '</div>' +
      // การ์ดสถานการณ์ทดสอบ beep — มีเฉพาะตอนเปิดด้วย ?scenario= (gps.js ตั้ง MOCK_SCENARIO ไว้)
      (window.MOCK_SCENARIO
        ? '<div class="tm-card">' +
            '<h3>สถานการณ์ทดสอบ</h3>' +
            '<div class="tm-kv tm-pick"><span>ตอนนี้</span><b id="tm-phase">—</b></div>' +
            // ซ้ำกับการ์ดความเร็วด้านบน เพราะแบนเนอร์เตือนมักบังการ์ดนั้นตอนเข้าใกล้จุดเสี่ยง
            '<div class="tm-kv"><span>ความเร็วรถ</span><b id="tm-vnow">—</b></div>' +
            `<div class="tm-kv"><span>ถึง ${window.MOCK_SCENARIO.target}</span><b id="tm-target">—</b></div>` +
            '<div class="tm-kv"><span>ความเร็วคิด beep</span><b id="tm-bspd">—</b></div>' +
            '<div class="tm-kv"><span>เริ่ม beep ที่</span><b id="tm-bstart">—</b></div>' +
          '</div>'
        : "");
    document.body.appendChild(box);
    return box;
  }

  function mmss(s) {
    const m = Math.floor(s / 60);
    const q = Math.floor(s % 60);
    return `${m < 10 ? "0" : ""}${m}:${q < 10 ? "0" : ""}${q}`;
  }

  /** เรียกทุกครั้งที่พิกัดอัปเดต — อ่านค่าจาก AlertSystem.telemetry() ไม่คิดเองซ้ำ */
  function update(lat, lng) {
    if (!enabled()) return;
    const el = build();
    const t = AlertSystem.telemetry();

    if (startedAt === null) startedAt = Date.now();
    // โหมดจำลองเร่งเวลาได้ จึงอ่านเวลาเดินทางของรถจาก gps.js แทนเวลาจริงที่นั่งดู
    const elapsedS = typeof window.MOCK_ELAPSED_S === "number"
      ? window.MOCK_ELAPSED_S
      : (Date.now() - startedAt) / 1000;
    if (lastLat !== null) distM += haversineMeters(lastLat, lastLng, lat, lng);
    lastLat = lat;
    lastLng = lng;

    const q = (id) => el.querySelector("#" + id);
    q("tm-spd").innerHTML =
      `${t.speedKmh === null || t.speedKmh === undefined ? "—" : Math.round(t.speedKmh)}` +
      '<small>กม./ชม.</small>';
    q("tm-dist").textContent = `${(distM / 1000).toFixed(2)} กม.`;
    q("tm-clk").textContent = mmss(elapsedS);

    q("tm-cog").innerHTML =
      `${t.heading === null ? "—" : Math.round(t.heading)}<small>°</small>`;
    q("tm-raw").textContent = t.rawCourse === null ? "—" : `${Math.round(t.rawCourse)}°`;
    // เทียบกับทิศจริงของถนนได้เฉพาะโหมดจำลอง ที่รู้คำตอบอยู่แล้ว
    if (t.trueCourse !== null && t.heading !== null) {
      q("tm-err").textContent = `คลาด ${angleDiffDegrees(t.heading, t.trueCourse).toFixed(1)}°`;
    } else {
      q("tm-err").textContent = t.heading === null ? "—" : "ใช้กรองทิศอยู่";
    }
    el.classList.toggle("tm-spike", window.MOCK_SPIKE === true);

    q("tm-head3").textContent = `จุดในระยะ ${AlertSystem.ALERT_RADIUS_M} ม.`;
    q("tm-lbl30").textContent = `กรวย ±${AlertSystem.HEADING_WINDOW_DEG}°`;
    q("tm-off").textContent = t.inRadius.off;
    q("tm-c90").textContent = t.inRadius.c90;
    q("tm-c30").textContent = t.inRadius.c30;

    const BEEP_TH = { far: "ช้า", mid: "ปานกลาง", near: "ถี่" };
    q("tm-beep").textContent = t.beep === null
      ? (t.parked ? "เงียบ · รถจอด" : "เงียบ")
      : BEEP_TH[t.beep] || t.beep;
    q("tm-beepfrom").textContent = t.beepFrom === null ? "—" : t.beepFrom;

    const sc = window.MOCK_SCENARIO;
    if (sc && q("tm-phase")) {
      q("tm-phase").textContent = (sc.phases && sc.phases[sc.phase]) || sc.phase;
      q("tm-vnow").textContent =
        t.speedKmh === null || t.speedKmh === undefined ? "—" : `${Math.round(t.speedKmh)} กม./ชม.`;
      const tp = RiskPoints.all().find((p) => p.id === sc.target);
      q("tm-target").textContent = tp ? `${Math.round(haversineMeters(lat, lng, tp.lat, tp.lng))} ม.` : "—";
      q("tm-bspd").textContent =
        t.beepSpeedKmh === null ? "ยังไม่รู้ ใช้ 90" : `${Math.round(t.beepSpeedKmh)} กม./ชม.`;
      q("tm-bstart").textContent = `${t.beepStartM} ม.`;
    }
  }

  return { update, enabled };
})();
