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
    // กล่องติ๊กชั้นจุดเสี่ยงรายอุบัติเหตุ มีเฉพาะตอนเปิดใช้ accidents.js
    const accToggle = document.getElementById("f-show-accidents");
    if (accToggle && typeof Accidents !== "undefined") {
      accToggle.addEventListener("change", (e) => Accidents.setVisible(e.target.checked));
    }
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

  /**
   * อ่านค่าจากฟอร์มแล้วสั่งกรอง + อัปเดตบรรทัดสรุปจำนวน
   * นับเฉพาะวงคลัสเตอร์ที่แสดงจริง (unit_type === "cluster") เพราะตัวเลขจาก
   * setFilter() นับรวมหน่วยเดี่ยว (noise) ที่ไม่ได้วาดบนแผนที่ด้วย
   * ชั้นจุดเสี่ยงรายอุบัติเหตุกรองตามไปด้วยเมื่อเปิดใช้ accidents.js
   */
  function apply() {
    const province = document.getElementById("f-province").value;
    const levels = LEVELS.map(([key]) => key).filter(
      (key) => document.getElementById(`f-level-${key}`).checked
    );

    RiskPoints.setFilter({
      province,
      levels,
      pattern: document.getElementById("f-pattern").value,
    });
    const shownClusters = RiskPoints.visible().filter((p) => p.unit_type === "cluster").length;
    const totalClusters = RiskPoints.all().filter((p) => p.unit_type === "cluster").length;

    if (typeof Accidents !== "undefined") {
      Accidents.applyFilter({ province, levels: new Set(levels) });
    }

    const countEl = document.getElementById("filter-count");
    countEl.textContent =
      shownClusters === totalClusters
        ? `แสดงครบทั้ง ${totalClusters} วง`
        : `แสดง ${shownClusters} จาก ${totalClusters} วง`;
    countEl.classList.toggle("filter-count--none", shownClusters === 0);
    if (shownClusters === 0) countEl.textContent = "ไม่มีคลัสเตอร์ที่ตรงกับตัวกรอง";
  }

  function reset() {
    document.getElementById("f-province").value = "";
    document.getElementById("f-pattern").value = "";
    for (const [key] of LEVELS) document.getElementById(`f-level-${key}`).checked = true;
    const accToggle = document.getElementById("f-show-accidents");
    if (accToggle && typeof Accidents !== "undefined") {
      accToggle.checked = true;
      Accidents.setVisible(true);
    }
    apply();
  }

  return { init };
})();
