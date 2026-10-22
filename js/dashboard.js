/** dashboard.js — โหลด GeoJSON แล้วสรุปสถิติเป็น KPI + กราฟ + ตาราง */

(async function main() {
  const LEVELS = [
    { key: "high", label: "สูง", color: "var(--risk-high)", ink: "#fff" },
    { key: "medium", label: "ปานกลาง", color: "var(--risk-medium)", ink: "#fff" },
    { key: "low", label: "ต่ำ", color: "var(--risk-low)", ink: "#fff" },
  ];

  // dashboard.html ตั้ง window.RISK_DATA_URL ไว้ก่อนโหลดสคริปต์นี้เพื่อเลือกชุดข้อมูล
  const DATA_URL = window.RISK_DATA_URL || "data/risk_points_bkk_metro_3y.geojson";

  let zones;
  let calibration = null;
  try {
    const resp = await fetch(DATA_URL);
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const geojson = await resp.json();
    calibration = geojson.calibration || null;
    zones = geojson.features.map((f) => f.properties);
  } catch (err) {
    document.getElementById("loading").classList.add("hidden");
    const el = document.getElementById("load-error");
    el.textContent = `โหลดข้อมูลไม่สำเร็จ (${err.message}) — ตรวจว่าเปิดผ่าน server ไม่ใช่ file://`;
    el.classList.remove("hidden");
    return;
  }

  // ระดับรวม 2 ปัจจัย (SI + Accident Rate จำแนกด้วย Rate Quality Control)
  // จาก data/combined_levels_3y.json (scripts/build_combined_levels.py)
  // ถ้าโหลดไม่ได้ ใช้ระดับจาก SI อย่างเดียว และซ่อนการ์ดที่ต้องใช้ข้อมูล Accident Rate
  let combined = null;
  try {
    const resp = await fetch(window.LEVELS_DATA_URL || "data/combined_levels_3y.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    combined = await resp.json();
  } catch (err) {
    document.getElementById("method-card").classList.add("hidden");
    document.getElementById("rate-card").classList.add("hidden");
    document.getElementById("level-note").textContent = "ระดับจาก Accident Severity (SI) อย่างเดียว";
  }
  const info = (z) => (combined && combined.clusters[z.id]) || null;
  const levelOf = (z) => (info(z) ? info(z).level : z.level);

  const sum = (key) => zones.reduce((acc, z) => acc + (z[key] || 0), 0);
  const score = (z) => z.severity_index ?? 0; // Severity Index (คำนวณฝั่ง Python)
  const fmt = (n) => n.toLocaleString("th-TH");
  const chip = (key) => {
    if (!key) return `<span style="color:var(--muted)">–</span>`;
    const lv = LEVELS.find((l) => l.key === key);
    return `<span class="level-chip ${key}" style="background:${lv.color}">${lv.label}</span>`;
  };

  // ---------- KPI ----------
  const byLevel = {};
  for (const lv of LEVELS) byLevel[lv.key] = zones.filter((z) => levelOf(z) === lv.key).length;

  // KPI ผู้เสียชีวิต/บาดเจ็บ/จุดเสี่ยง ใช้ยอด "ทุกจุดเสี่ยง" จาก calibration.overall
  const overall = (calibration && calibration.overall) || null;
  const excluded = (calibration && calibration.excluded_noise) || null;
  const totalAcc = overall ? overall.risk_points : sum("accident_count");
  const totalDeaths = overall ? overall.deaths : sum("deaths");
  const totalSerious = overall ? overall.serious_injury : sum("serious_injury");
  const totalMinor = overall ? overall.minor_injury : sum("minor_injury");

  document.getElementById("kpi-zones").textContent = fmt(zones.length);
  document.getElementById("kpi-zones-sub").textContent =
    `สูง ${byLevel.high} · ปานกลาง ${byLevel.medium} · ต่ำ ${byLevel.low}` +
    (combined ? " (ระดับรวม 2 ปัจจัย)" : "");
  document.getElementById("kpi-accidents").textContent = fmt(totalAcc);
  document.getElementById("kpi-deaths").textContent = fmt(totalDeaths);
  document.getElementById("kpi-deaths-sub").textContent = excluded
    ? `ในคลัสเตอร์ ${fmt(totalDeaths - excluded.deaths)} · จุดเสี่ยงเดี่ยว ${fmt(excluded.deaths)}`
    : `ใน ${zones.filter((z) => z.deaths > 0).length} คลัสเตอร์ที่มีผู้เสียชีวิต`;
  document.getElementById("kpi-injured").textContent = fmt(totalSerious + totalMinor);
  document.getElementById("kpi-injured-sub").textContent =
    `สาหัส ${fmt(totalSerious)} · เล็กน้อย ${fmt(totalMinor)}`;

  // ---------- แถบสัดส่วนระดับ ----------
  const levelBar = document.getElementById("level-bar");
  const levelLegend = document.getElementById("level-legend");
  for (const lv of LEVELS) {
    const count = byLevel[lv.key];
    const pct = (count / zones.length) * 100;

    const seg = document.createElement("div");
    seg.className = "level-seg";
    seg.style.background = lv.color;
    seg.style.color = lv.ink;
    seg.style.flex = `${count} 0 0`;
    seg.textContent = count;
    seg.title = `${lv.label} ${count} วง (${pct.toFixed(1)}%)`;
    levelBar.appendChild(seg);

    const item = document.createElement("span");
    item.innerHTML = `<span class="swatch" style="background:${lv.color}"></span>` +
      `${lv.label} <strong>${count}</strong> วง (${pct.toFixed(1)}%)`;
    levelLegend.appendChild(item);
  }
  // ป้ายตัวเลขในท่อนต้องไม่ล้น — ถ้าท่อนแคบกว่าตัวเลข ให้ซ่อน (legend มีค่าครบอยู่แล้ว)
  requestAnimationFrame(() => {
    for (const seg of levelBar.children) {
      if (seg.scrollWidth > seg.offsetWidth) seg.textContent = "";
    }
  });

  // ---------- เกณฑ์แบ่งระดับ 2 ปัจจัย ----------
  if (combined) {
    const c = combined.counts;
    const total = (o) => LEVELS.reduce((acc, lv) => acc + (o[lv.key] || 0), 0);
    document.getElementById("method-note").textContent =
      `${fmt(combined.with_aadt)} วงที่มีข้อมูลปริมาณจราจร (AADT) ใช้ทั้งสองปัจจัย · ` +
      `${fmt(combined.without_aadt)} วงที่ไม่มี AADT ใช้ระดับจาก SI`;
    const mtb = document.querySelector("#method-table tbody");
    for (const lv of LEVELS) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${chip(lv.key)}</td>` +
        `<td class="num">${fmt(c.si[lv.key] || 0)}</td>` +
        `<td class="num">${fmt(c.rate[lv.key] || 0)}</td>` +
        `<td class="num"><strong>${fmt(c.combined[lv.key] || 0)}</strong></td>`;
      mtb.appendChild(tr);
    }
    const tr = document.createElement("tr");
    tr.innerHTML = `<td>รวม</td><td class="num">${fmt(total(c.si))} วง</td>` +
      `<td class="num">${fmt(total(c.rate))} วง</td><td class="num">${fmt(total(c.combined))} วง</td>`;
    mtb.appendChild(tr);
    const ra = Object.entries(combined.ra_by_agency)
      .map(([name, v]) => `${name} ${v.toFixed(4)}`).join(" · ");
    const items = [
      `ปัจจัยที่ 1 Accident Severity: ${combined.method.severity}`,
      `ปัจจัยที่ 2 ${combined.method.rate} (Rc ที่ระดับความเชื่อมั่นร้อยละ 95)`,
      `Ra แยกตามหน่วยงาน: ${ra}`,
      combined.method.combine,
    ];
    const ul = document.getElementById("method-list");
    for (const t of items) {
      const li = document.createElement("li");
      li.textContent = t;
      ul.appendChild(li);
    }
  }

  // ---------- กราฟจังหวัด ----------
  const byProvince = new Map();
  for (const z of zones) {
    if (!byProvince.has(z.province)) byProvince.set(z.province, { total: 0, high: 0, medium: 0, low: 0 });
    const p = byProvince.get(z.province);
    p.total++;
    p[levelOf(z)]++;
  }
  const provinces = [...byProvince.entries()].sort((a, b) => b[1].total - a[1].total);

  drawBars({
    container: document.getElementById("province-chart"),
    rows: provinces.map(([name, p]) => ({
      label: name,
      value: p.total,
      tooltip: `<strong>${name}</strong><br>จุดคลัสเตอร์ ${p.total} วง<br>` +
        `🔴 สูง ${p.high} · 🟠 ปานกลาง ${p.medium} · 🟡 ต่ำ ${p.low}`,
    })),
    color: "var(--series-1)",
  });

  // ---------- กราฟสาเหตุ (top 8 + อื่นๆ + ไม่ระบุ) ----------
  // นับรายจุดเสี่ยงในคลัสเตอร์จาก data/cause_counts_3y.json (scripts/build_cause_counts.py)
  // ชุดเดียวกับตารางที่ 4-7 ในรายงาน · ถ้าโหลดไม่ได้ ใช้สาเหตุหลักรายคลัสเตอร์แทน
  const CAUSE_TOP_N = 8;
  let causes;
  let unspecified = 0;
  try {
    const resp = await fetch(window.CAUSE_DATA_URL || "data/cause_counts_3y.json");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    const data = await resp.json();
    causes = data.causes.map((c) => [c.cause, c.count]);
    unspecified = data.unspecified || 0;
  } catch (err) {
    const byCause = new Map();
    for (const z of zones) {
      byCause.set(z.top_cause, (byCause.get(z.top_cause) || 0) + z.accident_count);
    }
    causes = [...byCause.entries()].sort((a, b) => b[1] - a[1]);
    document.getElementById("cause-note").textContent =
      "จำนวนจุดเสี่ยงสะสมในจุดคลัสเตอร์ที่มีสาเหตุหลักนั้น";
  }
  const topCauses = causes.slice(0, CAUSE_TOP_N);
  const otherTotal = causes.slice(CAUSE_TOP_N).reduce((acc, [, n]) => acc + n, 0);
  if (otherTotal > 0) topCauses.push([`อื่นๆ (${causes.length - CAUSE_TOP_N} สาเหตุ)`, otherTotal]);
  if (unspecified > 0) topCauses.push(["ไม่ระบุ", unspecified]);

  drawBars({
    container: document.getElementById("cause-chart"),
    rows: topCauses.map(([name, n]) => ({
      label: name,
      value: n,
      tooltip: `<strong>${name}</strong><br>อุบัติเหตุสะสม ${fmt(n)} ครั้ง`,
    })),
    color: "var(--series-2)",
  });

  // ---------- ตาราง 10 อันดับ ระดับรวม (เรียงระดับ แล้ว EPDO ภายในระดับ) ----------
  const RANK = { high: 2, medium: 1, low: 0 };
  const ctb = document.querySelector("#combined-table tbody");
  [...zones]
    .sort((a, b) => RANK[levelOf(b)] - RANK[levelOf(a)] || b.epdo_million - a.epdo_million)
    .slice(0, 10)
    .forEach((z, i) => {
      const c = info(z) || {};
      const has = c.R != null;
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${z.road_label || z.road}</td>
        <td>${z.province}</td>
        <td class="num">${fmt(z.accident_count)}</td>
        <td class="num">${score(z).toFixed(2)}</td>
        <td>${chip(z.si_level || c.si_level || z.level)}</td>
        <td class="num">${has ? c.R.toFixed(3) : "–"}</td>
        <td class="num">${has ? c.DF.toFixed(2) : "–"}</td>
        <td>${chip(c.rate_level)}</td>
        <td class="num">${z.epdo_million.toFixed(2)}</td>
        <td>${chip(levelOf(z))}</td>`;
      ctb.appendChild(tr);
    });

  // ---------- ตาราง 10 อันดับ ----------
  const tbody = document.querySelector("#top-table tbody");
  const top10 = [...zones].sort((a, b) => score(b) - score(a)).slice(0, 10);
  top10.forEach((z, i) => {
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${z.road_label || z.road}</td>
      <td>${z.province}</td>
      <td class="num">${z.accident_count}</td>
      <td class="num">${z.deaths}</td>
      <td class="num">${z.serious_injury}</td>
      <td class="num">${z.minor_injury}</td>
      <td class="num">${score(z).toFixed(2)}</td>
      <td>${chip(z.si_level || z.level)}</td>
      <td>${chip(levelOf(z))}</td>`;
    tbody.appendChild(tr);
  });

  // ---------- ตาราง 10 อันดับ Accident Rate ----------
  if (combined) {
    const rtb = document.querySelector("#rate-table tbody");
    const withRate = zones.filter((z) => info(z) && info(z).R != null);
    withRate.sort((a, b) => info(b).R - info(a).R).slice(0, 10).forEach((z, i) => {
      const c = info(z);
      const tr = document.createElement("tr");
      tr.innerHTML = `
        <td>${i + 1}</td>
        <td>${z.road_label || z.road}</td>
        <td>${c.agency}</td>
        <td class="num">${fmt(z.accident_count)}</td>
        <td class="num">${fmt(c.V)}</td>
        <td class="num">${c.R.toFixed(3)}</td>
        <td class="num">${c.DF.toFixed(2)}</td>
        <td class="num">${score(z).toFixed(2)}</td>
        <td>${chip(c.rate_level)}</td>
        <td>${chip(c.level)}</td>`;
      rtb.appendChild(tr);
    });
  }

  // ระบุรอบ calibration ที่ผลชุดนี้ถูก "ล็อก" ไว้ (Fixed-Schedule Recalibration)
  if (calibration) {
    const [b1, b2] = calibration.level_breaks || [];
    document.getElementById("calib-note").textContent =
      ` · รอบคำนวณ ${calibration.version}` +
      (excluded ? ` · จุดเสี่ยงเดี่ยว ${fmt(excluded.risk_points)} จุดไม่นำมาจัดระดับ` : "") +
      (b1 != null ? ` (ระดับรวม 2 ปัจจัย = ระดับที่สูงกว่าระหว่างปัจจัยที่ 1 SI: ต่ำ < ${b1} · ปานกลาง ${b1}–${b2} · สูง ≥ ${b2}` +
        ` กับปัจจัยที่ 2 Accident Rate: ต่ำ R ≤ Ra · ปานกลาง Ra < R ≤ Rc · สูง R > Rc)` : "");
  }

  document.getElementById("loading").classList.add("hidden");
  document.getElementById("dashboard").classList.remove("hidden");

  // ---------- ตัววาดกราฟแท่งแนวนอน ----------
  function drawBars({ container, rows, color }) {
    const max = Math.max(...rows.map((r) => r.value));
    for (const r of rows) {
      const row = document.createElement("div");
      row.className = "bar-row";

      const label = document.createElement("div");
      label.className = "bar-label";
      label.textContent = r.label;
      label.title = r.label;

      const track = document.createElement("div");
      track.className = "bar-track";
      const fill = document.createElement("div");
      fill.className = "bar-fill";
      fill.style.background = color;
      fill.style.width = `${(r.value / max) * 100}%`;
      const value = document.createElement("span");
      value.className = "bar-value";
      value.textContent = fmt(r.value);
      track.append(fill, value);

      row.append(label, track);
      attachTooltip(row, r.tooltip);
      container.appendChild(row);
    }
  }

  // ---------- tooltip ร่วม ----------
  const tooltip = document.getElementById("tooltip");
  function attachTooltip(el, html) {
    el.addEventListener("mouseenter", () => {
      tooltip.innerHTML = html;
      tooltip.classList.remove("hidden");
    });
    el.addEventListener("mousemove", (e) => {
      const pad = 14;
      let x = e.clientX + pad;
      let y = e.clientY + pad;
      const r = tooltip.getBoundingClientRect();
      if (x + r.width > innerWidth - 8) x = e.clientX - r.width - pad;
      if (y + r.height > innerHeight - 8) y = e.clientY - r.height - pad;
      tooltip.style.left = `${x}px`;
      tooltip.style.top = `${y}px`;
    });
    el.addEventListener("mouseleave", () => tooltip.classList.add("hidden"));
  }
})();
