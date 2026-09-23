/** tts.js — อ่านข้อความแจ้งเตือนเป็นเสียงภาษาไทย (แบบ 4 ชั้น fallback อัตโนมัติ) */

const TTS = (() => {
  const USE_BOTNOI = true; // ชั้น 1: เรียก proxy /api/tts (Botnoi)
  const USE_NEURAL = true; // ชั้น 2: Google translate_tts
  const NEURAL_MAX_CHARS = 190; // translate_tts รับได้จำกัดต่อครั้ง

  const BEEP_FALLBACK_MS = 700; // ใช้เมื่อไม่มี Web Audio (เล่นเสียงนำไม่ได้ ได้แค่หน่วงเวลา)
  const MAX_SPEAK_MS = 20000; // เพดานเวลารอเสียงหนึ่งชุด กันค้างถ้า onended ไม่ยิง
  const FADE_IN_MS = 180; // ไล่ความดังขึ้นตอนเริ่มพูด ไม่ให้ประโยคผุดขึ้นมาดังเต็ม
  const FADE_OUT_MS = 140; // หรี่ลงตอนถูกตัดกลางประโยค แทนการดับทันทีซึ่งได้ยินเป็นเสียงสะดุด

  let thaiVoice = null;
  let unlocked = false;
  let audioEl = null;
  let resumeTimer = null;
  let toneCtx = null; // AudioContext สำหรับสังเคราะห์เสียง beep
  let speaking = false; // กัน beep ไปร้องทับประโยคเตือนที่กำลังพูดอยู่

  function speechSupported() {
    return "speechSynthesis" in window;
  }
  function isSupported() {
    return speechSupported() || "Audio" in window;
  }

  /** URL เสียง Botnoi ผ่าน proxy ฝั่งเซิร์ฟเวอร์เรา (ซ่อน token ไว้ที่ server) */
  function botnoiUrl(text) {
    return `/api/tts?text=${encodeURIComponent(text)}`;
  }

  /** URL เสียง neural ภาษาไทยจาก Google (ไม่ต้องใช้ API key) */
  function neuralUrl(text) {
    const q = encodeURIComponent(text);
    return `https://translate.google.com/translate_tts?ie=UTF-8&tl=th&client=tw-ob&q=${q}`;
  }

  function pickThaiVoice() {
    if (!speechSupported()) return null;
    const thai = speechSynthesis
      .getVoices()
      .filter((v) => v.lang && v.lang.toLowerCase().startsWith("th"));
    if (thai.length === 0) return null;

    // เสียง neural/online (Google, Natural, Neural) นุ่มกว่าเสียง local มาก
    const isNatural = (v) => /google|natural|neural|online/i.test(v.name);
    return (
      thai.find((v) => v.lang === "th-TH" && isNatural(v)) ||
      thai.find((v) => isNatural(v)) ||
      thai.find((v) => v.lang === "th-TH") ||
      thai[0]
    );
  }

  function init() {
    if (!speechSupported()) return;
    thaiVoice = pickThaiVoice();
    // บางเบราว์เซอร์ (Chrome) โหลดรายชื่อเสียงแบบ async
    speechSynthesis.onvoiceschanged = () => {
      thaiVoice = pickThaiVoice();
    };
  }

  /** ปลดล็อกเสียง — ต้องเรียกจาก user gesture (กดปุ่ม) ครั้งแรกหนึ่งครั้ง */
  function unlock() {
    if (unlocked) return;
    // ปลดล็อก Web Speech (ชั้นสำรอง)
    if (speechSupported()) {
      const u = new SpeechSynthesisUtterance("");
      u.volume = 0;
      speechSynthesis.speak(u);
    }
    // ปลดล็อก <audio> (ชั้น neural) — สร้างและ "อุ่นเครื่อง" ระหว่างมี user gesture
    audioEl = new Audio();
    audioEl.play().catch(() => {}); // ยังไม่มี src เล่นไม่ได้ แต่นับเป็นการปลดล็อก
    // iOS 17+: ไม่ให้สวิตช์ปิดเสียง (silent) ปิด beep ไปด้วย
    try {
      if (navigator.audioSession) navigator.audioSession.type = "playback";
    } catch (e) { /* เบราว์เซอร์ไม่รองรับ */ }
    // ปลดล็อก <audio> ของ beep — เล่นเงียบ ๆ ครั้งหนึ่งใน user gesture แล้วค่อยเปิดเสียง
    // (ทางเดียวกับเสียงพูด ซึ่งดังบนมือถือจริง ต่างจาก Web Audio ที่มักเงียบ)
    beepEl = makeToneEl([0.0]);
    leadEl = makeToneEl(BEEP_LEAD_TIMES);
    // ปลดล็อก AudioContext (สำรอง ใช้เมื่อ <audio> เล่นไม่ขึ้น)
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) {
      toneCtx = toneCtx || new AudioCtx();
      if (toneCtx.state === "suspended") toneCtx.resume();
    }
    unlocked = true;
  }

  /** เสียงพูดที่อัดไว้ล่วงหน้าด้วย Botnoi Voice — ข้อความ -> ชื่อไฟล์ใน CLIP_DIR */
  const CLIP_DIR = "audio/";
  const VOICE_CLIPS = {
    // ⚠️ รอบสี่ (2026-08-25): ผู้ใช้ลองตัด "ลดความเร็ว" ออกแล้วไม่ชอบ ขอกลับไปใช้
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงต่ำ โปรดขับขี่ด้วยความระมัดระวัง":
      "alert_01.mp3",
    //  2. medium — fatal-history + single-vehicle + rollover รวมกัน (51+27 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวัง":
      "alert_02.mp3",
    //  4. medium (24 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
      "alert_04.mp3",
    //  5. high — fatal-history + single-vehicle + rollover รวมกัน (9+5 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดใช้ความเร็วให้เหมาะสม และขับขี่ระมัดระวังเป็นพิเศษ":
      "alert_05.mp3",
    //  6. high   (8 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
      "alert_06.mp3",
    //  7. medium (5 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดลดความเร็ว และระวังรถตัดผ่านทางแยก":
      "alert_07.mp3",
    //  9. medium (4 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดใช้ความเร็วไม่เกิน 90 กิโลเมตรต่อชั่วโมง":
      "alert_09.mp3",
    // 10. high   (2 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดลดความเร็วก่อนเข้าโค้ง และงดแซงในช่วงนี้":
      "alert_10.mp3",
    // 11. medium (1 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดลดความเร็วก่อนเข้าโค้ง และงดแซงในช่วงนี้":
      "alert_11.mp3",
    // 12. medium (1 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดเว้นระยะห่าง และระวังรถชะลอตัวเพื่อกลับรถ":
      "alert_12.mp3"
  };

  /** ลายเสียงเตือนแยกตามระดับ — โทน "ติ๊ง-ต่อง" สองโทนสลับ แบบเสียงประกาศบนรถโดยสาร */
  /** เสียง beep — ใช้แทน chime เดิมทั้งหมด */
  const BEEP_HZ = 2400; // แยกจากย่านเสียงพูดชัดเจน และเป็นย่านที่ลำโพงเล็กดังที่สุด
  const BEEP_S = 0.12;
  const BEEP_PEAK = 0.7;

  // จังหวะ beep ตามระยะ (ครั้งต่อวินาที) — ตั้งใจไม่ให้ไต่ไปถึงเสียงยาวต่อเนื่องแบบ
  const BEEP_RATE_HZ = { far: 1, mid: 2, near: 4 };

  const BEEP_LEAD_TIMES = [0.0, 0.22]; // beep นำหน้าประโยค 2 ครั้ง
  const BEEP_LEAD_GAP_MS = 280; // เงียบก่อนเริ่มพูด ให้แยกเสียงนำกับประโยคออกจากกัน

  // สัดส่วนความดังของฮาร์มอนิกที่ 2 และ 3 เทียบกับคลื่นหลัก
  const HARMONICS = [[1, 1.0], [2, 0.3], [3, 0.12]];

  // เวลาไล่ความดังขึ้น — เสียงที่ดังขึ้นทันทีทำให้คนขับสะดุ้ง (startle reflex) ซึ่งอันตราย
  const ATTACK_S = 0.02;
  const RELEASE_S = 0.04;

  /** ตั้งเวลาเล่น beep หนึ่งครั้งที่เวลา at ของ AudioContext */
  function scheduleBeep(at) {
    for (const [mult, share] of HARMONICS) {
      const osc = toneCtx.createOscillator();
      const gain = toneCtx.createGain();
      osc.type = "sine";
      osc.frequency.value = BEEP_HZ * mult;

      const peak = BEEP_PEAK * share;
      gain.gain.setValueAtTime(0.0001, at);
      gain.gain.exponentialRampToValueAtTime(peak, at + ATTACK_S);
      gain.gain.setValueAtTime(peak, at + BEEP_S - RELEASE_S);
      gain.gain.exponentialRampToValueAtTime(0.0001, at + BEEP_S);

      osc.connect(gain).connect(toneCtx.destination);
      osc.start(at);
      osc.stop(at + BEEP_S + 0.02);
    }
  }

  let beepEl = null; // <audio> beep ครั้งเดียว (จังหวะบอกระยะ)
  let leadEl = null; // <audio> beep สองครั้งนำหน้าประโยค

  /** สร้างไฟล์ WAV ของ beep เสียงเดียวกับ scheduleBeep() เริ่มที่เวลา times (วินาที) */
  function toneWavUrl(times) {
    const RATE = 22050;
    const total = Math.ceil((times[times.length - 1] + BEEP_S + 0.02) * RATE);
    const buf = new ArrayBuffer(44 + total * 2);
    const v = new DataView(buf);
    const str = (o, s) => { for (let i = 0; i < s.length; i++) v.setUint8(o + i, s.charCodeAt(i)); };
    str(0, "RIFF"); v.setUint32(4, 36 + total * 2, true); str(8, "WAVE");
    str(12, "fmt "); v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true);
    v.setUint32(24, RATE, true); v.setUint32(28, RATE * 2, true);
    v.setUint16(32, 2, true); v.setUint16(34, 16, true);
    str(36, "data"); v.setUint32(40, total * 2, true);
    // envelope แบบเดียวกับ Web Audio: ไต่ขึ้นแบบ exponential -> คงที่ -> หรี่ลง
    const env = (t) => {
      if (t < 0 || t > BEEP_S) return 0;
      if (t < ATTACK_S) return 0.0001 * Math.pow(1e4, t / ATTACK_S);
      if (t < BEEP_S - RELEASE_S) return 1;
      return Math.pow(1e-4, (t - (BEEP_S - RELEASE_S)) / RELEASE_S);
    };
    for (let i = 0; i < total; i++) {
      const t = i / RATE;
      let s = 0;
      for (const at of times) {
        const g = env(t - at);
        if (!g) continue;
        for (const [mult, share] of HARMONICS) {
          s += BEEP_PEAK * share * g * Math.sin(2 * Math.PI * BEEP_HZ * mult * (t - at));
        }
      }
      v.setInt16(44 + i * 2, Math.max(-1, Math.min(1, s)) * 32767, true);
    }
    return URL.createObjectURL(new Blob([buf], { type: "audio/wav" }));
  }

  /** <audio> ของ beep ที่ปลดล็อกแล้ว — ต้องเรียกใน user gesture */
  function makeToneEl(times) {
    const el = new Audio(toneWavUrl(times));
    el.muted = true; // iOS ไม่สน volume จึงใช้ muted ตอนปลดล็อก
    const p = el.play();
    const reset = () => { el.pause(); el.currentTime = 0; el.muted = false; };
    if (p && p.then) p.then(reset).catch(reset);
    else reset();
    return el;
  }

  /** เล่น beep ผ่าน <audio> — ไม่ขึ้นค่อยใช้ Web Audio แทน */
  function playTone(el, times) {
    const viaCtx = () => {
      if (!toneCtx) return;
      if (toneCtx.state !== "running") toneCtx.resume();
      const t0 = toneCtx.currentTime + 0.02; // เผื่อเวลาให้ scheduler เล็กน้อย
      for (const at of times) scheduleBeep(t0 + at);
    };
    if (!el) return viaCtx();
    try {
      el.currentTime = 0;
      const p = el.play();
      if (p && p.catch) p.catch(viaCtx);
    } catch (e) {
      viaCtx();
    }
  }

  /** beep สองครั้งนำหน้าประโยคเตือน — แทน playChime() เดิม */
  function playLeadBeep() {
    return new Promise((resolve) => {
      if (!leadEl && !toneCtx) return setTimeout(resolve, BEEP_FALLBACK_MS);
      playTone(leadEl, BEEP_LEAD_TIMES);
      const lenMs = (BEEP_LEAD_TIMES[BEEP_LEAD_TIMES.length - 1] + BEEP_S) * 1000;
      setTimeout(resolve, lenMs + BEEP_LEAD_GAP_MS);
    });
  }

  let beepPattern = null;
  let beepTimer = null;

  /** ตั้งจังหวะ beep บอกระยะ — name = "far" | "mid" | "near" | null (null = เงียบ) */
  function setBeepPattern(name) {
    if (name === beepPattern) return;
    beepPattern = name;
    if (beepTimer !== null) {
      clearInterval(beepTimer);
      beepTimer = null;
    }
    if (!name || (!beepEl && !toneCtx)) return;
    const tick = () => {
      // ประโยคเตือนสำคัญกว่า beep — ข้ามจังหวะนี้ไปเฉย ๆ ไม่ต้องหยุดทั้งชุด
      if (speaking) return;
      playTone(beepEl, [0.0]);
    };
    tick();
    beepTimer = setInterval(tick, 1000 / BEEP_RATE_HZ[name]);
  }

  /** ชั้นสำรอง: สังเคราะห์เสียงในเครื่องด้วย Web Speech API */
  function speakWebSpeech(text) {
    if (!speechSupported()) return Promise.resolve(false);
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "th-TH";
      // 0.92 ช้ากว่าปกติเล็กน้อย — ภาษาไทยไม่มีช่องว่างระหว่างคำ เสียงสังเคราะห์
      u.rate = 0.92;
      u.pitch = 1.0; // โทนเสียงเป็นธรรมชาติ (0=ต่ำสุด, 2=สูงสุด)
      u.volume = 1.0;
      if (thaiVoice) u.voice = thaiVoice;
      if (speechSynthesis.speaking || speechSynthesis.pending) speechSynthesis.cancel();

      const done = once(resolve, MAX_SPEAK_MS);
      u.onend = () => done(true);
      u.onerror = () => done(false);

      // แก้บั๊ก Chrome ที่เสียงกระตุก/หยุดกลางประโยค: คอย resume ระหว่างพูด
      clearInterval(resumeTimer);
      resumeTimer = setInterval(() => {
        if (!speechSynthesis.speaking) return clearInterval(resumeTimer);
        speechSynthesis.pause();
        speechSynthesis.resume();
      }, 6000);

      speechSynthesis.speak(u);
    });
  }

  /** ห่อ resolve ให้เรียกได้ครั้งเดียว + มีเวลาสูงสุดกันค้าง */
  function once(resolve, timeoutMs) {
    let settled = false;
    const finish = (v) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(v);
    };
    const timer = setTimeout(() => finish(true), timeoutMs);
    return finish;
  }

  /** ไล่ระดับความดังของ <audio> จากค่าปัจจุบันไปยัง target */
  function rampVolume(el, target, ms) {
    return new Promise((resolve) => {
      const STEP_MS = 20;
      const from = el.volume;
      const steps = Math.max(1, Math.round(ms / STEP_MS));
      let i = 0;

      // ยกเลิกการไล่ระดับครั้งก่อน — ต้อง resolve ตัวเก่าทิ้งด้วย ไม่งั้น promise
      clearInterval(el._volTimer);
      if (el._volResolve) el._volResolve();
      el._volResolve = resolve;

      el._volTimer = setInterval(() => {
        i++;
        const v = from + (target - from) * (i / steps);
        el.volume = Math.min(1, Math.max(0, v));
        if (i >= steps) {
          clearInterval(el._volTimer);
          el._volResolve = null;
          resolve();
        }
      }, STEP_MS);
    });
  }

  /** หยุดเสียงที่กำลังพูดอยู่แบบหรี่ลง ไม่ตัดกลางคำให้สะดุดหู */
  async function fadeOutCurrent() {
    if (!audioEl || audioEl.paused || !audioEl.src) return;
    await rampVolume(audioEl, 0, FADE_OUT_MS);
    audioEl.pause();
  }

  /** เล่นไฟล์เสียงจาก url — คืน Promise<boolean> ที่ resolve เมื่อ "เล่นจบ" */
  function playUrl(url) {
    return new Promise((resolve) => {
      const done = once(resolve, MAX_SPEAK_MS);

      // ยกเลิกการไล่ระดับที่ค้างอยู่ พร้อมปลด promise ของมันด้วย
      clearInterval(audioEl._volTimer);
      if (audioEl._volResolve) {
        audioEl._volResolve();
        audioEl._volResolve = null;
      }

      audioEl.onerror = () => done(false); // โหลด/ถอดรหัสไฟล์ไม่ได้ (เช่น 502/404)
      audioEl.onended = () => done(true);
      audioEl.volume = 0;
      audioEl.src = url;

      // ไล่ความดังขึ้นเมื่อเสียงเริ่มเล่นจริง — ดักไว้สองทาง (event playing และ promise
      const fadeIn = () => rampVolume(audioEl, 1, FADE_IN_MS);
      audioEl.onplaying = fadeIn;
      const p = audioEl.play();
      if (p && p.then) p.then(fadeIn).catch(() => done(false)); // เบราว์เซอร์บล็อก/เล่นไม่ขึ้น
    });
  }

  /** พูดข้อความภาษาไทย — ไล่ลองทีละชั้น: Botnoi -> Google -> Web Speech */
  async function speak(text) {
    speaking = true;
    try {
      return await speakInner(text);
    } finally {
      speaking = false;
    }
  }

  async function speakInner(text) {
    if (!unlocked || !audioEl) return speakWebSpeech(text);
    if (speechSupported()) speechSynthesis.cancel(); // กันพูดซ้อนกับชั้นสำรอง
    await fadeOutCurrent(); // ถ้ายังพูดประโยคก่อนค้างอยู่ ให้หรี่ลงก่อน ไม่ตัดกลางคำ

    const urls = [];
    // ชั้น 0: ไฟล์เสียง Botnoi ที่อัดไว้ล่วงหน้า — เร็วที่สุด ไม่ใช้เน็ต ไม่เสียพอยท์
    if (VOICE_CLIPS[text]) urls.push(CLIP_DIR + VOICE_CLIPS[text]);
    if (USE_BOTNOI) urls.push(botnoiUrl(text));
    if (USE_NEURAL && text.length <= NEURAL_MAX_CHARS) urls.push(neuralUrl(text));

    for (const url of urls) {
      if (await playUrl(url)) return true; // ชั้นนี้เล่นได้ จบ
    }
    return speakWebSpeech(text); // ทุกชั้นเสียงไฟล์ล้มเหลว -> เสียงในเครื่อง
  }

  function hasThaiVoice() {
    return thaiVoice !== null;
  }

  return { init, unlock, speak, playLeadBeep, setBeepPattern, isSupported, hasThaiVoice };
})();
