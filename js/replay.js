/** replay.js — เล่นย้อนการขับทดสอบจาก log ของ Raspberry Pi บนแผนที่
 *
 * เปิดด้วย ?replay=data/replay_xxx.json (สร้างจาก scripts/build_replay_from_log.py)
 * ตำแหน่ง ทิศ และเวลาที่เตือน เป็นค่าที่ Pi บันทึกไว้จริงทุกวินาที ไม่ได้คำนวณใหม่
 * แล้วส่งเข้า DeviceTracker.feed() ชุดเดียวกับตอนใช้งานจริง หมุด 🚌 กรวย ป้ายเตือน จึงหน้าตาเดียวกัน
 */

const Replay = (() => {
  const SPEEDS = [1, 2, 4, 8, 16];
  const TICK_MS = 100;
  // ไม่มีตำแหน่งนานกว่านี้ = Pi ไม่ได้บันทึก ข้ามไปเลย ไม่เดินนาฬิการอ
  // ช่วงสั้น ๆ ราว 10-15 วิ ตอน Pi กำลังพูดเตือน (ลูปรอเสียงจบ) ไม่นับ ให้รถค้างที่เดิมเหมือนตอนจริง
  const GAP_S = 60;

  let map = null;
  let data = null;
  let clock = 0;      // วินาทีนับจากจุดเริ่มของ log
  let speed = 4;
  let playing = false;
  let timer = null;
  let frameIdx = -1;
  let seekRound = 0;  // เปลี่ยนทุกครั้งที่ลากแถบ ให้การเตือนเดิมขึ้นป้ายซ้ำได้เมื่อเล่นผ่านอีกรอบ
  let soundOn = true;
  let ui = {};

  function url() {
    return new URLSearchParams(location.search).get("replay");
  }

  function isEnabled() {
    return !!url();
  }

  async function start(leafletMap) {
    map = leafletMap;
    try {
      const resp = await fetch(url(), { cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      data = await resp.json();
    } catch (err) {
      document.getElementById("gps-status").textContent = `❌ โหลดไฟล์เล่นย้อนไม่ได้: ${err.message}`;
      return;
    }
    data.t0 = hmsToSec(data.start);
    data.duration = data.frames[data.frames.length - 1][0];
    addSpeeds(data.frames);
    drawTrail();
    buildUi();
    // ?t=วินาที เริ่มกลางทาง · ?autoplay=1 เล่นทันที (ไม่มีเสียงจนกว่าจะกดปุ่มสักครั้ง ตามกฎเบราว์เซอร์)
    const qp = new URLSearchParams(location.search);
    seek(Math.min(Number(qp.get("t")) || 0, data.duration));
    if (qp.get("autoplay") === "1") play();
  }

  /** ความเร็วจากระยะระหว่างตำแหน่งย้อนหลัง 3 วินาที — log ไม่ได้เก็บความเร็วไว้ */
  function addSpeeds(frames) {
    frames.forEach((f, i) => {
      let j = i;
      while (j > 0 && f[0] - frames[j - 1][0] <= 3) j--;
      const p = frames[j];
      const dt = f[0] - p[0];
      f[4] = dt > 0 ? (haversineMeters(p[1], p[2], f[1], f[2]) / dt) * 3.6 : 0;
    });
  }

  /** เส้นทางที่ขับจริง — ตัดเป็นท่อนตรงช่วงที่ไม่มีข้อมูล ไม่ลากเส้นตรงข้ามช่วงนั้น */
  function drawTrail() {
    const parts = [[]];
    data.frames.forEach((f, i) => {
      if (i && f[0] - data.frames[i - 1][0] > GAP_S) parts.push([]);
      parts[parts.length - 1].push([f[1], f[2]]);
    });
    const line = L.polyline(parts, { color: "#1976d2", weight: 4, opacity: 0.45 }).addTo(map);
    map.fitBounds(line.getBounds(), { padding: [30, 30] });
  }

  function buildUi() {
    const bar = document.createElement("div");
    bar.id = "replay-bar";
    bar.innerHTML =
      '<button class="rp-play" type="button" title="เล่น/หยุด">▶️</button>' +
      '<span class="rp-time">--:--:--</span>' +
      `<input class="rp-seek" type="range" min="0" max="${data.duration}" step="1" value="0">` +
      `<select class="rp-speed" title="ความเร็วการเล่น">${SPEEDS.map((s) =>
        `<option value="${s}"${s === speed ? " selected" : ""}>${s}×</option>`).join("")}</select>` +
      '<label class="rp-sound" title="เล่นเสียงเตือนที่เครื่องนี้ (แทนลำโพง Pi)">' +
      '<input type="checkbox" checked> 🔊</label>' +
      '<div class="rp-note"></div>';
    document.body.appendChild(bar);
    document.body.classList.add("replay");
    ui = {
      play: bar.querySelector(".rp-play"),
      time: bar.querySelector(".rp-time"),
      seek: bar.querySelector(".rp-seek"),
      speed: bar.querySelector(".rp-speed"),
      sound: bar.querySelector(".rp-sound input"),
      note: bar.querySelector(".rp-note"),
    };
    ui.note.textContent =
      `ข้อมูลจริงจาก log ของ Pi วันที่ ${thaiDate(data.date)} ` +
      `${data.start.slice(0, 5)}–${data.end.slice(0, 5)} น. · เตือน ${data.alerts.length} ครั้ง`;
    ui.play.addEventListener("click", () => {
      if (typeof TTS !== "undefined") TTS.unlock(); // เสียงต้องปลดล็อกจากการกดปุ่ม
      playing ? pause() : play();
    });
    ui.seek.addEventListener("input", () => seek(Number(ui.seek.value)));
    ui.speed.addEventListener("change", () => { speed = Number(ui.speed.value); });
    ui.sound.addEventListener("change", () => { soundOn = ui.sound.checked; });
  }

  function play() {
    if (clock >= data.duration) seek(0);
    playing = true;
    ui.play.textContent = "⏸️";
    timer = setInterval(tick, TICK_MS);
  }

  function pause() {
    playing = false;
    ui.play.textContent = "▶️";
    clearInterval(timer);
  }

  function seek(t) {
    clock = t;
    seekRound++;
    frameIdx = -1;
    show(false);
  }

  function tick() {
    const prev = clock;
    clock += (TICK_MS / 1000) * speed;
    // ช่วงที่ Pi ไม่ได้บันทึก — กระโดดข้าม และบอกบนแถบว่าข้ามไปช่วงไหน
    const next = data.frames.find((f) => f[0] > prev);
    if (next && next[0] - prev > GAP_S && clock < next[0]) {
      const from = secToHms(data.t0 + prev).slice(0, 5);
      const to = secToHms(data.t0 + next[0]).slice(0, 5);
      ui.note.textContent = `⏭️ ข้ามช่วง ${from}–${to} น. ที่ Pi ไม่ได้บันทึกตำแหน่ง`;
      clock = next[0];
    }
    if (clock >= data.duration) {
      clock = data.duration;
      show(true, prev);
      pause();
      return;
    }
    show(true, prev);
  }

  /** แสดงตำแหน่งที่เวลา clock — fire=true ให้เตือนทุกครั้งที่นาฬิกาเดินผ่านในรอบนี้ */
  function show(fire, prev) {
    let i = frameIdx < 0 ? 0 : frameIdx;
    if (data.frames[i][0] > clock) i = 0;
    while (i + 1 < data.frames.length && data.frames[i + 1][0] <= clock) i++;

    let alert = null;
    if (fire) {
      for (const a of data.alerts) {
        if (a.t > prev && a.t <= clock) alert = a;
      }
    }
    ui.seek.value = Math.floor(clock);
    ui.time.textContent = secToHms(data.t0 + clock);
    if (i === frameIdx && !alert) return;
    frameIdx = i;

    const [t, lat, lng, heading, kmh] = data.frames[i];
    DeviceTracker.feed({
      lat, lng, heading,
      speed_kmh: kmh,
      online: true,
      age_s: 0,
      source: "serial",
      satellites: data.satellites ?? null, // log ไม่มีค่านี้ — ใช้ค่าที่ผู้ขับจดจากจอ ถ้าใส่ไว้
      at_ms: logTimeMs(t),
      last_alert: alert
        ? { at: `${alert.t}-${seekRound}`, message: alert.message, level: alert.level, age_s: 0 }
        : null,
    });
    if (alert && soundOn && typeof TTS !== "undefined") {
      TTS.playLeadBeep();
      TTS.speak(alert.message);
    }
    follow(lat, lng);
  }

  /** เลื่อนแผนที่ตามรถเมื่อรถใกล้หลุดขอบจอ — ไม่จับกลางทุกวินาทีจนจอสั่น */
  function follow(lat, lng) {
    const inner = map.getBounds().pad(-0.2);
    if (!inner.contains([lat, lng])) map.panTo([lat, lng]);
  }

  function hmsToSec(hms) {
    const [h, m, s] = hms.split(":").map(Number);
    return h * 3600 + m * 60 + s;
  }

  function secToHms(sec) {
    const s = Math.floor(sec);
    const pad = (n) => String(n).padStart(2, "0");
    return `${pad(Math.floor(s / 3600))}:${pad(Math.floor(s / 60) % 60)}:${pad(s % 60)}`;
  }

  function logTimeMs(t) {
    const [y, mo, d] = data.date.split("-").map(Number);
    return new Date(y, mo - 1, d).getTime() + (data.t0 + t) * 1000;
  }

  function thaiDate(iso) {
    const [y, m, d] = iso.split("-").map(Number);
    return `${d}/${m}/${y + 543}`;
  }

  /** กระโดดไปเวลา t (วินาทีของ log) แบบเดินหน้า — ให้สคริปต์อัดวิดีโอเรียกทีละเฟรม */
  function stepTo(t) {
    const prev = clock;
    clock = Math.min(t, data.duration);
    show(true, prev);
  }

  return { isEnabled, start, stepTo, ready: () => !!data && !!ui.seek };
})();
