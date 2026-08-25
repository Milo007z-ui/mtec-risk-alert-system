/**
 * tts.js — อ่านข้อความแจ้งเตือนเป็นเสียงภาษาไทย (แบบ 4 ชั้น fallback อัตโนมัติ)
 *
 * ชั้น 0 (ดีสุด): ไฟล์เสียง Botnoi ที่อัดไว้ล่วงหน้าใน audio/ — ดูตาราง VOICE_CLIPS
 *                เร็วที่สุดเพราะไม่ต้องเรียก API ไม่เสียพอยท์ และใช้ได้ตอนไม่มีเน็ต
 * ชั้น 1:        Botnoi Voice สดผ่าน proxy /api/tts (ต้องรันผ่าน FastAPI เท่านั้น)
 * ชั้น 2:        เสียง neural ของ Google ผ่าน translate_tts — ลื่น ฟรี ไม่ต้องสมัคร
 * ชั้น 3 (สำรอง): Web Speech API ในเครื่อง — ใช้เมื่อทุกชั้นบนล้มเหลว/ไม่มีเน็ต
 *                ถ้าเครื่องไม่รองรับเลยจะคืน false ให้ alert.js แจ้งเตือนด้วยภาพแทน
 *
 * ถ้าเปิดผ่าน python -m http.server (ไม่มี /api/tts) ชั้น 1 จะ error แล้วตกไปชั้น 2 เอง
 */

const TTS = (() => {
  const USE_BOTNOI = true; // ชั้น 1: เรียก proxy /api/tts (Botnoi)
  const USE_NEURAL = true; // ชั้น 2: Google translate_tts
  const NEURAL_MAX_CHARS = 190; // translate_tts รับได้จำกัดต่อครั้ง

  const CHIME_MS = 2000; // ใช้เมื่อไม่มี Web Audio (เล่นเสียงนำไม่ได้ ได้แค่หน่วงเวลา)
  const MAX_SPEAK_MS = 20000; // เพดานเวลารอเสียงหนึ่งชุด กันค้างถ้า onended ไม่ยิง
  const FADE_IN_MS = 180; // ไล่ความดังขึ้นตอนเริ่มพูด ไม่ให้ประโยคผุดขึ้นมาดังเต็ม
  const FADE_OUT_MS = 140; // หรี่ลงตอนถูกตัดกลางประโยค แทนการดับทันทีซึ่งได้ยินเป็นเสียงสะดุด

  let thaiVoice = null;
  let unlocked = false;
  let audioEl = null;
  let resumeTimer = null;
  let chimeCtx = null;

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

  /**
   * ปลดล็อกเสียง — ต้องเรียกจาก user gesture (กดปุ่ม) ครั้งแรกหนึ่งครั้ง
   * ไม่งั้นเบราว์เซอร์บนมือถือจะบล็อกเสียงที่สั่งเล่นเองทีหลัง
   */
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
    // ปลดล็อก AudioContext (เสียงติ๊งก่อนพูด) — มือถือบล็อกถ้าไม่ได้สร้าง/resume ใน user gesture
    const AudioCtx = window.AudioContext || window.webkitAudioContext;
    if (AudioCtx) {
      chimeCtx = chimeCtx || new AudioCtx();
      if (chimeCtx.state === "suspended") chimeCtx.resume();
    }
    unlocked = true;
  }

  /**
   * เสียงพูดที่อัดไว้ล่วงหน้าด้วย Botnoi Voice — ข้อความ -> ชื่อไฟล์ใน CLIP_DIR
   *
   * ทำไมต้องมี: เว็บที่ deploy บน GitHub Pages ไม่มีเซิร์ฟเวอร์ จึงไม่มี /api/tts
   * เสียง Botnoi สดจึงใช้ไม่ได้เลยบนเว็บจริง ต้องตกไปใช้ Google ซึ่งเสียงแข็งกว่ามาก
   * ไฟล์ที่อัดไว้จึงเป็นทางเดียวที่จะได้เสียง Botnoi บนเว็บจริง
   * ผลพลอยได้: ไม่เสียพอยท์ต่อการเตือนหนึ่งครั้ง เล่นทันทีไม่ต้องรอเรียก API และใช้ได้ตอนไม่มีเน็ต
   *
   * คีย์คือข้อความเต็มที่ระยะ 500 เมตร เพราะการเตือนยิงตอนข้ามเส้น 500 พอดีเสมอ
   * (วัดจริงได้ 496-500 ม. ปัดเป็น 500 ทุกครั้ง) ระยะอื่นจะหาไม่เจอแล้วตกไปใช้ TTS สดเอง
   *
   * ไฟล์หายหรือยังไม่ได้ใส่ก็ไม่พัง — playUrl ได้ 404 แล้วไล่ไปชั้นถัดไปตามลำดับเดิม
   * สร้างรายการนี้จาก audio-script.txt (ดู docs ใน README หัวข้อเสียงพูด)
   */
  const CLIP_DIR = "audio/";
  const VOICE_CLIPS = {
    // ⚠️ รอบสี่ (2026-08-25): ผู้ใช้ลองตัด "ลดความเร็ว" ออกแล้วไม่ชอบ ขอกลับไปใช้
    // คำเดิม "ลดความเร็ว" ตามปกติ — แต่ยังคงให้ fatal-history/single-vehicle/
    // rollover ใช้ประโยคเดียวกันไว้เหมือนเดิม (ผู้ใช้ยืนยันอยากรวมส่วนนี้ต่อ)
    // เลข alert_03/alert_08 เดิมเลยยังว่างไป ไม่ต้องอัดไฟล์เพิ่ม ใช้
    // alert_02.mp3/alert_05.mp3 ร่วมกันแทน ไม่ได้ไล่เลขใหม่เพราะ alert_01
    // อัดไปแล้วก่อนหน้านี้
    //  1. low    (319 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงต่ำ โปรดขับขี่ด้วยความระมัดระวัง":
      "alert_01.mp3",
    //  2. medium — fatal-history + single-vehicle + rollover รวมกัน (51+27 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดลดความเร็ว และใช้ความระมัดระวัง":
      "alert_02.mp3",
    //  4. medium (24 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงปานกลาง โปรดเว้นระยะห่างจากคันหน้า และระวังรถเปลี่ยนช่องทาง":
      "alert_04.mp3",
    //  5. high — fatal-history + single-vehicle + rollover รวมกัน (9+5 วง)
    "ข้างหน้าอีก 500 เมตร ใกล้จุดเสี่ยงสูง โปรดลดความเร็ว และใช้ความระมัดระวังเป็นพิเศษ":
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

  /**
   * ลายเสียงเตือนแยกตามระดับ — โทน "ติ๊ง-ต่อง" สองโทนสลับ แบบเสียงประกาศบนรถโดยสาร
   * (ผู้ใช้ฟังเทียบ 3 แบบแล้วเลือกแบบนี้ เพราะคนขับคุ้นบริบทเสียงนี้อยู่แล้ว)
   *
   * ใช้คู่โน้ต D6 (1175 Hz) กับ A5 (880 Hz) ทุกระดับ ด้วยเหตุผลสองข้อ
   *   1. เสียงเครื่องยนต์รถโดยสารกระจุกอยู่ย่านต่ำ (ราว 50-200 Hz) เสียงเตือนย่านนี้
   *      จึงลอยพ้นเสียงรบกวน ไม่ถูกกลบ
   *   2. ไม่สูงเกิน 2000 Hz เพราะการได้ยินความถี่สูงถดถอยตามอายุ (presbycusis)
   *      คนขับอาชีพส่วนใหญ่อายุมาก ถ้าใช้เสียงแหลมกว่านี้บางคนจะไม่ได้ยิน
   *
   * ความเร่งด่วนสื่อด้วย "จำนวนรอบ" ของคู่โน้ต ไม่ใช่การเปลี่ยนความถี่
   * (สองรอบ = สูง · หนึ่งรอบ = ปานกลาง · โน้ตเดียว = ต่ำ) เสียงจึงเป็นชุดเดียวกัน
   * ฟังแล้วรู้ว่ามาจากระบบเดียวกัน แต่ยังแยกระดับออก
   *
   * ค่า peak คำนวณมาให้ RMS ของเสียงนำสูงกว่า RMS ของไฟล์เสียงพูด Botnoi
   * (วัดได้ 0.111) ตามระดับ: ต่ำ +3.4 dB · ปานกลาง +4.8 dB · สูง +5.0 dB
   * ถ้าเสียงนำไม่ดังกว่าประโยคที่ตามมา มันจะกลืนไปกับเสียงพูดและไม่ดึงความสนใจเลย
   * เพดาน peak 0.88 กันเสียงแตกเมื่อฮาร์มอนิกซ้อนกันพอดี
   * ** ถ้าเปลี่ยนไฟล์เสียงพูดชุดใหม่ ต้องวัด RMS แล้วคำนวณ peak ใหม่ **
   *
   * [เวลาเริ่ม(วินาที), ความถี่(เฮิรตซ์), ความยาว(วินาที)]
   */
  const CHIME_PATTERNS = {
    // สองรอบเต็ม ติ๊ง-ต่อง-ติ๊ง-ต่อง — ย้ำสองครั้งจึงเร่งด่วนที่สุด
    high: {
      tones: [[0.0, 1175, 0.2], [0.24, 880, 0.2], [0.48, 1175, 0.2], [0.72, 880, 0.42]],
      peak: 0.785,
    },
    // หนึ่งรอบ ติ๊ง-ต่อง — โทนประกาศมาตรฐาน
    medium: { tones: [[0.0, 1175, 0.22], [0.26, 880, 0.45]], peak: 0.765 },
    // จังหวะเดียว โน้ตต่ำของคู่ — แจ้งให้ทราบโดยไม่รบกวนสมาธิ
    low: { tones: [[0.0, 880, 0.45]], peak: 0.643 },
  };

  // เวลาเงียบหลังเสียงนำจบก่อนเริ่มพูด — เว้นสั้นๆ พอให้แยกเสียงนำกับประโยคออกจากกัน
  // แต่ไม่นานจนขาดตอน (ค่าเดิมตายตัว 2 วิ ทำให้มีช่องเงียบ 1.5 วิ ฟังแล้วสะดุด)
  const CHIME_GAP_MS = 550;

  // สัดส่วนความดังของฮาร์มอนิกที่ 2 และ 3 เทียบกับคลื่นหลัก
  // เสียงที่มีฮาร์มอนิกลอยพ้นเสียงรบกวนได้ดีกว่าคลื่นไซน์บริสุทธิ์ที่ความดังเท่ากัน
  // และหูคนระบุทิศทาง/แยกแยะได้ง่ายกว่า
  const HARMONICS = [[1, 1.0], [2, 0.3], [3, 0.12]];

  // เวลาไล่ความดังขึ้น 40 มิลลิวินาที — ยาวพอไม่ให้เกิด startle reflex
  // (เสียงที่ดังขึ้นทันทีทำให้คนขับสะดุ้ง ซึ่งอันตรายมากถ้ามีผู้โดยสารยืนอยู่)
  // ยืดจาก 30 เป็น 40 ตอนเพิ่มความดัง เพราะเสียงยิ่งดังยิ่งต้องขึ้นนุ่มขึ้น
  // ค่านี้ใช้คำนวณ peak ใน CHIME_PATTERNS ด้วย เปลี่ยนแล้วต้องคำนวณ peak ใหม่
  const ATTACK_S = 0.04;

  /** ความยาวรวมของลายเสียงหนึ่งชุด (วินาที) */
  function chimeLengthS(pattern) {
    return Math.max(...pattern.tones.map(([at, , dur]) => at + dur));
  }

  /**
   * เสียงเตือนนำก่อนพูดข้อความ — ใช้ลายเสียงตามระดับความเสี่ยง
   * แต่ละจังหวะสังเคราะห์จากคลื่นหลัก + ฮาร์มอนิกที่ 2 และ 3 ให้เสียงอิ่มคล้ายระฆัง
   * ไล่ความดังขึ้นช้าๆ แล้วปล่อยจางแบบเอกซ์โพเนนเชียล ไม่มีเสียง "แป๊ะ" หัวท้าย
   * คืน Promise ที่ resolve เมื่อเสียงจบ + เว้นช่วง CHIME_GAP_MS พร้อมให้เริ่มพูด
   */
  function playChime(level = "medium") {
    const pattern = CHIME_PATTERNS[level] || CHIME_PATTERNS.medium;
    return new Promise((resolve) => {
      if (!chimeCtx) return setTimeout(resolve, CHIME_MS);
      if (chimeCtx.state === "suspended") chimeCtx.resume();

      const t0 = chimeCtx.currentTime + 0.02; // เผื่อเวลาให้ scheduler เล็กน้อย

      for (const [at, freq, dur] of pattern.tones) {
        for (const [mult, share] of HARMONICS) {
          const osc = chimeCtx.createOscillator();
          const gain = chimeCtx.createGain();
          osc.type = "sine";
          osc.frequency.value = freq * mult;

          const start = t0 + at;
          const peak = pattern.peak * share;
          gain.gain.setValueAtTime(0.0001, start);
          gain.gain.exponentialRampToValueAtTime(peak, start + ATTACK_S);
          gain.gain.exponentialRampToValueAtTime(0.0001, start + dur);

          osc.connect(gain).connect(chimeCtx.destination);
          osc.start(start);
          osc.stop(start + dur + 0.02);
        }
      }

      setTimeout(resolve, chimeLengthS(pattern) * 1000 + CHIME_GAP_MS);
    });
  }

  /**
   * ชั้นสำรอง: สังเคราะห์เสียงในเครื่องด้วย Web Speech API
   * คืน Promise<boolean> ที่ resolve เมื่อ "พูดจบ" (ไม่ใช่ตอนเริ่มพูด)
   */
  function speakWebSpeech(text) {
    if (!speechSupported()) return Promise.resolve(false);
    return new Promise((resolve) => {
      const u = new SpeechSynthesisUtterance(text);
      u.lang = "th-TH";
      // 0.92 ช้ากว่าปกติเล็กน้อย — ภาษาไทยไม่มีช่องว่างระหว่างคำ เสียงสังเคราะห์
      // ที่ความเร็วเต็มมักอ่านติดกันจนแยกคำไม่ออก โดยเฉพาะในห้องโดยสารที่มีเสียงรบกวน
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

  /**
   * ห่อ resolve ให้เรียกได้ครั้งเดียว + มีเวลาสูงสุดกันค้าง
   * (ถ้าเสียงค้างไม่ยอมจบ ระบบเตือนจะถูกล็อกไว้ตลอด — ต้องมีทางออกเสมอ)
   */
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

  /**
   * ไล่ระดับความดังของ <audio> จากค่าปัจจุบันไปยัง target
   *
   * ทำไมไม่ใช้ Web Audio (GainNode) ซึ่งไล่ระดับได้เนียนกว่า: เสียงชั้น Google
   * มาจากโดเมนอื่นและไม่ส่งหัว CORS การต่อผ่าน createMediaElementSource
   * จะทำให้กราฟถูก taint แล้วเงียบสนิท — ต้องคุมที่ .volume ของ element เท่านั้น
   */
  function rampVolume(el, target, ms) {
    return new Promise((resolve) => {
      const STEP_MS = 20;
      const from = el.volume;
      const steps = Math.max(1, Math.round(ms / STEP_MS));
      let i = 0;

      // ยกเลิกการไล่ระดับครั้งก่อน — ต้อง resolve ตัวเก่าทิ้งด้วย ไม่งั้น promise
      // ของมันจะค้างตลอดกาล ทำให้ speak() ที่ await อยู่ไม่เดินต่อ และล็อกเสียงไม่ถูกปลด
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

  /**
   * เล่นไฟล์เสียงจาก url — คืน Promise<boolean> ที่ resolve เมื่อ "เล่นจบ"
   * (false = โหลด/เล่นไม่ได้ ให้ไปลองชั้นถัดไป)
   * เปิดเสียงจากศูนย์แล้วไล่ขึ้น ไม่ให้ประโยคเริ่มดังเต็มทันทีจนสะดุด
   */
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
      // ของ play()) เพราะถ้าพลาดทั้งคู่ volume จะค้างที่ 0 กลายเป็นเตือนแล้วไม่มีเสียง
      // เรียกซ้ำได้ไม่มีปัญหา ครั้งหลังจะแทนที่ครั้งแรกเอง
      const fadeIn = () => rampVolume(audioEl, 1, FADE_IN_MS);
      audioEl.onplaying = fadeIn;
      const p = audioEl.play();
      if (p && p.then) p.then(fadeIn).catch(() => done(false)); // เบราว์เซอร์บล็อก/เล่นไม่ขึ้น
    });
  }

  /**
   * พูดข้อความภาษาไทย — ไล่ลองทีละชั้น: Botnoi -> Google -> Web Speech
   * คืน true ถ้ามีชั้นใดพูดได้ / false ถ้าต้อง fallback เป็นภาพ
   */
  async function speak(text) {
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

  return { init, unlock, speak, playChime, isSupported, hasThaiVoice };
})();
