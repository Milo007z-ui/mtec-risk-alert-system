/**
 * tts.js — อ่านข้อความแจ้งเตือนเป็นเสียงภาษาไทยด้วย Web Speech API
 * ถ้าเครื่องไม่มีเสียงไทย/ไม่รองรับ speechSynthesis จะคืน false
 * เพื่อให้ alert.js ใช้การแจ้งเตือนแบบภาพแทน
 */

const TTS = (() => {
  let thaiVoice = null;
  let unlocked = false;

  function isSupported() {
    return "speechSynthesis" in window;
  }

  function pickThaiVoice() {
    if (!isSupported()) return null;
    const voices = speechSynthesis.getVoices();
    return (
      voices.find((v) => v.lang === "th-TH") ||
      voices.find((v) => v.lang && v.lang.startsWith("th")) ||
      null
    );
  }

  function init() {
    if (!isSupported()) return;
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
    if (!isSupported() || unlocked) return;
    const u = new SpeechSynthesisUtterance("");
    u.volume = 0;
    speechSynthesis.speak(u);
    unlocked = true;
  }

  /**
   * พูดข้อความภาษาไทย คืน true ถ้าสั่งพูดได้ / false ถ้าต้อง fallback เป็นภาพ
   */
  function speak(text) {
    if (!isSupported()) return false;
    const u = new SpeechSynthesisUtterance(text);
    u.lang = "th-TH";
    u.rate = 1.0;
    if (thaiVoice) u.voice = thaiVoice;
    speechSynthesis.cancel(); // ตัดข้อความเก่าที่ยังพูดไม่จบ กันคิวยาว
    speechSynthesis.speak(u);
    return true;
  }

  function hasThaiVoice() {
    return thaiVoice !== null;
  }

  return { init, unlock, speak, isSupported, hasThaiVoice };
})();
