/**
 * dashboard.js — โหลด GeoJSON แล้วสรุปสถิติเป็น KPI + กราฟ + ตาราง
 */

(async function main() {
  const LEVELS = [
    { key: "high", label: "สูง", color: "var(--risk-high)", ink: "#fff" },
    { key: "medium", label: "ปานกลาง", color: "var(--risk-medium)", ink: "#fff" },
    { key: "low", label: "ต่ำ", color: "var(--risk-low)", ink: "#0b0b0b" },
  ];

  let zones;
  try {
    const resp = await fetch("data/risk_points_bkk_metro.geojson");
    if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
    zones = (await resp.json()).features.map((f) => f.properties);
  } catch (err) {
    document.getElementById("loading").classList.add("hidden");
    const el = document.getElementById("load-error");
    el.textContent = `โหลดข้อมูลไม่สำเร็จ (${err.message}) — ตรวจว่าเปิดผ่าน server ไม่ใช่ file://`;
    el.classList.remove("hidden");
    return;
  }

  const sum = (key) => zones.reduce((acc, z) => acc + (z[key] || 0), 0);
  const score = (z) => z.deaths * 3 + z.serious_injury * 2 + z.minor_injury;
  const fmt = (n) => n.toLocaleString("th-TH");

  // ---------- KPI ----------
  const byLevel = {};
  for (const lv of LEVELS) byLevel[lv.key] = zones.filter((z) => z.level === lv.key).length;

  document.getElementById("kpi-zones").textContent = fmt(zones.length);
  document.getElementById("kpi-zones-sub").textContent =
    `สูง ${byLevel.high} · ปานกลาง ${byLevel.medium} · ต่ำ ${byLevel.low}`;
  document.getElementById("kpi-accidents").textContent = fmt(sum("accident_count"));
  document.getElementById("kpi-deaths").textContent = fmt(sum("deaths"));
  document.getElementById("kpi-deaths-sub").textContent =
    `ใน ${zones.filter((z) => z.deaths > 0).length} จุดที่มีผู้เสียชีวิต`;
  document.getElementById("kpi-injured").textContent = fmt(sum("serious_injury") + sum("minor_injury"));
  document.getElementById("kpi-injured-sub").textContent =
    `สาหัส ${fmt(sum("serious_injury"))} · เล็กน้อย ${fmt(sum("minor_injury"))}`;

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
    seg.title = `${lv.label} ${count} จุด (${pct.toFixed(1)}%)`;
    levelBar.appendChild(seg);

    const item = document.createElement("span");
    item.innerHTML = `<span class="swatch" style="background:${lv.color}"></span>` +
      `${lv.label} <strong>${count}</strong> จุด (${pct.toFixed(1)}%)`;
    levelLegend.appendChild(item);
  }
  // ป้ายตัวเลขในท่อนต้องไม่ล้น — ถ้าท่อนแคบกว่าตัวเลข ให้ซ่อน (legend มีค่าครบอยู่แล้ว)
  requestAnimationFrame(() => {
    for (const seg of levelBar.children) {
      if (seg.scrollWidth > seg.offsetWidth) seg.textContent = "";
    }
  });

  // ---------- กราฟจังหวัด ----------
  const byProvince = new Map();
  for (const z of zones) {
    if (!byProvince.has(z.province)) byProvince.set(z.province, { total: 0, high: 0, medium: 0, low: 0 });
    const p = byProvince.get(z.province);
    p.total++;
    p[z.level]++;
  }
  const provinces = [...byProvince.entries()].sort((a, b) => b[1].total - a[1].total);

  drawBars({
    container: document.getElementById("province-chart"),
    rows: provinces.map(([name, p]) => ({
      label: name,
      value: p.total,
      tooltip: `<strong>${name}</strong><br>จุดเสี่ยง ${p.total} จุด<br>` +
        `🔴 สูง ${p.high} · 🟠 ปานกลาง ${p.medium} · 🟡 ต่ำ ${p.low}`,
    })),
    color: "var(--series-1)",
  });

  // ---------- กราฟสาเหตุ (top 7 + อื่นๆ) ----------
  const byCause = new Map();
  for (const z of zones) {
    byCause.set(z.top_cause, (byCause.get(z.top_cause) || 0) + z.accident_count);
  }
  const causes = [...byCause.entries()].sort((a, b) => b[1] - a[1]);
  const topCauses = causes.slice(0, 7);
  const otherTotal = causes.slice(7).reduce((acc, [, n]) => acc + n, 0);
  if (otherTotal > 0) topCauses.push([`อื่นๆ (${causes.length - 7} สาเหตุ)`, otherTotal]);

  drawBars({
    container: document.getElementById("cause-chart"),
    rows: topCauses.map(([name, n]) => ({
      label: name,
      value: n,
      tooltip: `<strong>${name}</strong><br>อุบัติเหตุสะสม ${fmt(n)} ครั้ง`,
    })),
    color: "var(--series-2)",
  });

  // ---------- ตาราง 10 อันดับ ----------
  const tbody = document.querySelector("#top-table tbody");
  const top10 = [...zones].sort((a, b) => score(b) - score(a)).slice(0, 10);
  top10.forEach((z, i) => {
    const lv = LEVELS.find((l) => l.key === z.level) || LEVELS[2];
    const tr = document.createElement("tr");
    tr.innerHTML = `
      <td>${i + 1}</td>
      <td>${z.road}</td>
      <td>${z.province}</td>
      <td><span class="level-chip ${z.level}" style="background:${lv.color}">${lv.label}</span></td>
      <td class="num">${z.accident_count}</td>
      <td class="num">${z.deaths}</td>
      <td class="num">${z.serious_injury}</td>
      <td class="num">${z.minor_injury}</td>
      <td class="num">${score(z)}</td>`;
    tbody.appendChild(tr);
  });

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
