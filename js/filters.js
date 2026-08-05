/**
 * filters.js — แผงตัวกรองจุดเสี่ยงมุมบนขวาของแผนที่
 *
 * กรองได้ 3 แกน: จังหวัด · ระดับความเสี่ยง · ประเภทปัญหาหลัก
 * ตัวกรองมีผลทั้งหมุดบนแผนที่และการแจ้งเตือน (alert.js อ่าน RiskPoints.visible())
 */

const Filters = (() => {
  const PATTERN_OPTIONS = [
    ["", "ทั้งหมด"],
    ["single", "Single-vehicle เด่น (เสียหลัก/หลุดโค้ง)"],
    ["multiple", "Multiple-vehicle เด่น (ทางแยก/จุดเชื่อม)"],
    ["mixed", "ผสม"],
  ];

  const LEVELS = [
    ["high", "เสี่ยงสูง"],
    ["medium", "ปานกลาง"],
    ["low", "ต่ำ"],
  ];

  let panel = null;

  function init() {
    panel = document.getElementById("filter-panel");
    if (!panel) return;

    buildProvinceOptions();
    buildPatternOptions();

    panel.addEventListener("change", apply);
    document.getElementById("filter-toggle").addEventListener("click", () => {
      panel.classList.toggle("collapsed");
    });
    document.getElementById("filter-reset").addEventListener("click", reset);

    apply();
  }

  function buildProvinceOptions() {
    const select = document.getElementById("f-province");
    for (const name of RiskPoints.provinces()) {
      const opt = document.createElement("option");
      opt.value = name;
      opt.textContent = name;
      select.appendChild(opt);
    }
  }

  function buildPatternOptions() {
    const select = document.getElementById("f-pattern");
    for (const [value, label] of PATTERN_OPTIONS) {
      const opt = document.createElement("option");
      opt.value = value;
      opt.textContent = label;
      select.appendChild(opt);
    }
  }

  /** อ่านค่าจากฟอร์มแล้วสั่งกรอง + อัปเดตบรรทัดสรุปจำนวน */
  function apply() {
    const levels = LEVELS.map(([key]) => key).filter(
      (key) => document.getElementById(`f-level-${key}`).checked
    );
    const shown = RiskPoints.setFilter({
      province: document.getElementById("f-province").value,
      levels,
      pattern: document.getElementById("f-pattern").value,
    });

    const total = RiskPoints.all().length;
    const countEl = document.getElementById("filter-count");
    countEl.textContent =
      shown === total
        ? `แสดงครบทั้ง ${total} จุด`
        : `แสดง ${shown} จาก ${total} จุด`;
    countEl.classList.toggle("filter-count--none", shown === 0);
    if (shown === 0) countEl.textContent = "ไม่มีจุดที่ตรงกับตัวกรอง";
  }

  function reset() {
    document.getElementById("f-province").value = "";
    document.getElementById("f-pattern").value = "";
    for (const [key] of LEVELS) document.getElementById(`f-level-${key}`).checked = true;
    apply();
  }

  return { init };
})();
