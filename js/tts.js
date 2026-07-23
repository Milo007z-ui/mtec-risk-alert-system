/**
 * tts.js — อ่านข้อความแจ้งเตือนเป็นเสียงภาษาไทย (แบบ 3 ชั้น fallback อัตโนมัติ)
 *
 * ชั้น 1 (ดีสุด): Botnoi Voice ผ่าน proxy /api/tts — เสียงไทยธรรมชาติที่สุด (ต้องรันผ่าน FastAPI)
 * ชั้น 2:        เสียง neural ของ Google ผ่าน translate_tts — ลื่น ฟรี ไม่ต้องสมัคร
 * ชั้น 3 (สำรอง): Web Speech API ในเครื่อง — ใช้เมื่อสองชั้นบนล้มเหลว/ไม่มีเน็ต
 *                ถ้าเครื่องไม่รองรับเลยจะคืน false ให้ alert.js แจ้งเตือนด้วยภาพแทน
 *
 * ถ้าเปิดผ่าน python -m http.server (ไม่มี /api/tts) ชั้น 1 จะ error แล้วตกไปชั้น 2 เอง
 */

const TTS = (() => {
  const USE_BOTNOI = true; // ชั้น 1: เรียก proxy /api/tts (Botnoi)
  const USE_NEURAL = true; // ชั้น 2: Google translate_tts
  const NEURAL_MAX_CHARS = 190; // translate_tts รับได้จำกัดต่อครั้ง

  let thaiVoice = null;
  let unlocked = false;
  let audioEl = null;
  let resumeTimer = null;

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
    unlocked = true;
  }

  /** ชั้นสำรอง: สังเคราะห์เสียงในเครื่องด้วย Web Speech API */
  function speakWebSpeech(text) {
    if (!speechSupported()) return false;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "th-TH";
    u.rate = 0.95; // ช้าลงเล็กน้อย ฟังชัดและนุ่มขึ้น
    u.pitch = 1.0; // โทนเสียงเป็นธรรมชาติ (0=ต่ำสุด, 2=สูงสุด)
    u.volume = 1.0;
    if (thaiVoice) u.voice = thaiVoice;
    if (speechSynthesis.speaking || speechSynthesis.pending) speechSynthesis.cancel();

    // แก้บั๊ก Chrome ที่เสียงกระตุก/หยุดกลางประโยค: คอย resume ระหว่างพูด
    clearInterval(resumeTimer);
    resumeTimer = setInterval(() => {
      if (!speechSynthesis.speaking) return clearInterval(resumeTimer);
      speechSynthesis.pause();
      speechSynthesis.resume();
    }, 6000);

    speechSynthesis.speak(u);
    return true;
  }

  /** เล่นไฟล์เสียงจาก url — คืน Promise<boolean> ว่าเล่นสำเร็จไหม */
  function playUrl(url) {
    return new Promise((resolve) => {
      audioEl.onerror = () => resolve(false); // โหลด/ถอดรหัสไฟล์ไม่ได้ (เช่น 502/404)
      audioEl.src = url;
      const p = audioEl.play();
      if (p && p.then) p.then(() => resolve(true)).catch(() => resolve(false));
      else resolve(true);
    });
  }

  /**
   * พูดข้อความภาษาไทย — ไล่ลองทีละชั้น: Botnoi -> Google -> Web Speech
   * คืน true ถ้ามีชั้นใดพูดได้ / false ถ้าต้อง fallback เป็นภาพ
   */
  async function speak(text) {
    if (!unlocked || !audioEl) return speakWebSpeech(text);
    if (speechSupported()) speechSynthesis.cancel(); // กันพูดซ้อนกับชั้นสำรอง

    const urls = [];
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

  return { init, unlock, speak, isSupported, hasThaiVoice };
})();
