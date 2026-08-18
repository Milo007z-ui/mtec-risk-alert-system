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
    document.getElementById("f-show-accidents").addEventListener("change", (e) => {
      Accidents.setVisible(e.target.checked);
    });
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
   * อ่านค่าจากฟอร์มแล้วสั่งกรองทั้งสองชั้น + อัปเดตบรรทัดสรุปจำนวน
   * บรรทัดสรุปรายงานแยกสองคำ: "จุดเสี่ยง" (รายอุบัติเหตุ) กับ "คลัสเตอร์" (วง)
   */
  function apply() {
    const province = document.getElementById("f-province").value;
    const levels = LEVELS.map(([key]) => key).filter(
      (key) => document.getElementById(`f-level-${key}`).checked
    );

    // ชั้นคลัสเตอร์ — ตัวเลขที่คืนมานับรวมหน่วย noise ที่ไม่ได้วาดวง
    // จึงนับวงที่แสดงจริงจาก unit_type === "cluster" แทน
    RiskPoints.setFilter({
      province,
      levels,
      pattern: document.getElementById("f-pattern").value,
    });
    const shownClusters = RiskPoints.visible().filter((p) => p.unit_type === "cluster").length;
    const totalClusters = RiskPoints.all().filter((p) => p.unit_type === "cluster").length;

    // ชั้นจุดเสี่ยงรายอุบัติเหตุ (ไม่มีตัวกรองประเภทปัญหา)
    const levelSet = new Set(levels);
    const shownAcc = Accidents.applyFilter({ province, levels: levelSet });
    const totalAcc = Accidents.all().length;

    const countEl = document.getElementById("filter-count");
    if (shownAcc === 0 && shownClusters === 0) {
      countEl.textContent = "ไม่มีจุดที่ตรงกับตัวกรอง";
      countEl.classList.add("filter-count--none");
      return;
    }
    countEl.classList.remove("filter-count--none");
    const accText =
      shownAcc === totalAcc
        ? `จุดเสี่ยงครบทั้ง ${totalAcc.toLocaleString("th-TH")} จุด`
        : `จุดเสี่ยง ${shownAcc.toLocaleString("th-TH")} จาก ${totalAcc.toLocaleString("th-TH")} จุด`;
    const clusterText =
      shownClusters === totalClusters
        ? `คลัสเตอร์ครบทั้ง ${totalClusters} วง`
        : `คลัสเตอร์ ${shownClusters} จาก ${totalClusters} วง`;
    countEl.textContent = `${accText} · ${clusterText}`;
  }

  function reset() {
    document.getElementById("f-province").value = "";
    document.getElementById("f-pattern").value = "";
    for (const [key] of LEVELS) document.getElementById(`f-level-${key}`).checked = true;
    document.getElementById("f-show-accidents").checked = true;
    Accidents.setVisible(true);
    apply();
  }

  return { init };
})();
