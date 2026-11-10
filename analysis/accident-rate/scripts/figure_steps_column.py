"""ภาพที่ 4-8 (ก)(ข)(ค) และ 4-9 (ก)(ข)(ค) แบบแบ่งทีละขั้น กว้าง 1 คอลัมน์ของเล่ม (6.95 ซม.) สีชุดเดิมของภาพต้นฉบับ
วาดที่ขนาดพิมพ์จริง ตัวอักษร 7.5–9.5 pt · ค่าตัวอย่างคำนวณสดจากข้อมูล"""
import os
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle, FancyBboxPatch

plt.rcParams["font.family"] = "Tahoma"
plt.rcParams["mathtext.fontset"] = "dejavusans"
HERE = os.path.dirname(os.path.abspath(__file__))
OUTD = os.path.join(HERE, "..", "outputs", "ภาพแบ่งขั้น-คอลัมน์")
os.makedirs(OUTD, exist_ok=True)

INK, MUTED = "#1F2328", "#57606A"
BLUE, BLUE_BG = "#1C5CAB", "#EAF2FB"
ORG, ORG_BG = "#C2551F", "#FDF0E8"
GRAY, GRAY_BG = "#57606A", "#F6F8FA"
LV = {"low": ("ต่ำ", "#CDEBD3", "#1E6B33"), "medium": ("ปานกลาง", "#FCE8A6", "#7A5A00"), "high": ("สูง", "#F6C1B0", "#9C2B12")}
ORDER = ("low", "medium", "high")
W = 6.95
X0, XW = 0.25, 6.45  # ขอบในของเนื้อหา


class C:
    def __init__(self, color, bg):
        self.color, self.bg = color, bg
        self.fig = plt.figure(figsize=(W / 2.54, 20 / 2.54), facecolor="white")
        self.ax = self.fig.add_axes([0, 0, 1, 1]); self.ax.set_xlim(0, W); self.ax.set_ylim(20, 0); self.ax.axis("off")
        self.y0 = None

    def t(self, x, y, s, size=8, weight="normal", ha="left", va="center", color=INK, **kw):
        self.ax.text(x, y, s, fontsize=size, fontweight=weight, ha=ha, va=va, color=color, **kw)

    def rect(self, x, y, w, h, fc="white", ec=None, lw=0.6, round_=False):
        st = "round,pad=0,rounding_size=0.12" if round_ else "square,pad=0"
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=st, fc=fc, ec=ec or "none", lw=lw))

    def panel_start(self, y, title, note=""):
        self.y0 = y
        self.title, self.note = title, note
        return y + 0.62

    def panel_end(self, y):
        h = y - self.y0
        self.ax.add_patch(FancyBboxPatch((0.04, self.y0), W - 0.08, h, boxstyle="round,pad=0,rounding_size=0.18",
                                         fc=self.bg, ec=self.color, lw=0.9, zorder=0))
        self.ax.add_patch(FancyBboxPatch((0.04, self.y0), W - 0.08, 0.55, boxstyle="round,pad=0,rounding_size=0.18",
                                         fc=self.color, ec=self.color, lw=0.9, zorder=0.5))
        self.ax.add_patch(Rectangle((0.04, self.y0 + 0.3), W - 0.08, 0.25, fc=self.color, ec="none", zorder=0.6))
        self.t(0.2, self.y0 + 0.29, self.title, 8.5, "bold", color="white", zorder=1)
        if self.note:
            self.t(W - 0.2, self.y0 + 0.29, self.note, 6.5, ha="right", color="white", zorder=1)

    def fbox(self, y, s, h=1.0, size=9.5):
        self.rect(X0, y, XW, h, "white", self.color, 0.7, True)
        self.t(W / 2, y + h / 2, s, size, ha="center", color=self.color)
        return y + h

    def fbox2(self, y, s1, s2, h=1.45, size=8.5):
        self.rect(X0, y, XW, h, "white", self.color, 0.7, True)
        self.t(W / 2, y + 0.5, s1, size, ha="center", color=self.color)
        self.t(W / 2, y + 1.15, s2, size, ha="center", color=self.color)
        return y + h

    def levels(self, y, conds, h=0.75):
        self.t(X0, y + 0.22, "เกณฑ์แบ่งระดับ", 8, "bold", color=self.color)
        y += 0.45; cw = XW / 3
        for i, (k, cond) in enumerate(zip(ORDER, conds)):
            lab, fc, tc = LV[k]
            self.rect(X0 + i * cw, y, cw - 0.08, h, fc)
            self.t(X0 + i * cw + cw / 2 - 0.04, y + 0.23, lab, 7.5, "bold", ha="center", color=tc)
            self.t(X0 + i * cw + cw / 2 - 0.04, y + 0.53, cond, 7.5, ha="center", color=tc)
        return y + h

    def table(self, y, cols, rows, h=0.42, fills=None, size=7.5):
        x = X0
        for name, w in cols:
            self.rect(x, y, w, h, self.color, "white", 0.6)
            self.t(x + w / 2, y + h / 2, name, 7, "bold", ha="center", color="white"); x += w
        for i, r in enumerate(rows):
            x = X0
            for j, ((name, w), v) in enumerate(zip(cols, r)):
                fc, tc, wt = "white", INK, "normal"
                if fills and j == len(cols) - 1:
                    _, fc, tc = fills[i]; wt = "bold"
                self.rect(x, y + h * (i + 1), w, h, fc, "#B7C6DA", 0.5)
                self.t(x + w / 2, y + h * (i + 1.5), v, size, wt, ha="center", color=tc)
                x += w
        return y + h * (len(rows) + 1)

    def save(self, h, name):
        self.fig.set_size_inches(W / 2.54, h / 2.54); self.ax.set_ylim(h, 0)
        p = os.path.join(OUTD, name)
        self.fig.savefig(p, dpi=300, facecolor="white"); plt.close(self.fig)
        print("saved", name, f"{W} x {h:.2f} cm")


# ===================== ภาพที่ 4-8 (ก) SI
c = C(BLUE, BLUE_BG)
y = c.panel_start(0.04, "ปัจจัยที่ 1  Accident Severity Index (SI)")
y = c.fbox(y + 0.2, r"$SI = \dfrac{F + PI}{A}$", 1.05, 11)
for i, s in enumerate(["F  = จำนวนครั้งที่มีผู้เสียชีวิต", "PI = จำนวนผู้บาดเจ็บ (สาหัส + เล็กน้อย)",
                       "A  = จำนวนอุบัติเหตุทั้งหมดในคลัสเตอร์ (3 ปี)"]):
    c.t(X0, y + 0.32 + i * 0.36, s, 7.5)
c.t(X0, y + 1.42, "ความหมาย: ผู้เสียชีวิต/บาดเจ็บเฉลี่ยต่ออุบัติเหตุ 1 ครั้ง", 7.5, color=MUTED)
y = c.levels(y + 1.7, ["SI < 1", "1 ≤ SI < 2", "SI ≥ 2"])
c.t(X0, y + 0.27, "สูตร [1] สมการ 2.6 · จุดตัด 1 และ 2 กำหนดโดยผู้วิจัย", 6.5, color=MUTED)
y += 0.5; c.panel_end(y); c.save(y + 0.05, "4-8ก-ปัจจัยที่1-SI.png")

# ===================== ภาพที่ 4-8 (ข) Rate + RQC
c = C(ORG, ORG_BG)
y = c.panel_start(0.04, "ปัจจัยที่ 2  Accident Rate + RQC")
steps = [("ขั้น 1  ปริมาณรถที่ผ่านตลอด 3 ปี (ล้านคัน)", r"$MEV = \dfrac{365 \times T \times V \times L}{1{,}000{,}000}$"),
         ("ขั้น 2  อัตราการเกิดอุบัติเหตุ ([1] สมการ 3.2)", r"$R = \dfrac{A}{MEV}$"),
         ("ขั้น 3  อัตราเฉลี่ยของกลุ่ม ([12] สมการ 4-10)", r"$R_a = \dfrac{\sum (V_i \times R_i)}{\sum V_i}$"),
         ("ขั้น 4  อัตราวิกฤติ 95% ([1] สมการ 3.4)", r"$R_c = R_a + K\sqrt{\dfrac{R_a}{MEV}} + \dfrac{1}{2 \times MEV}$")]
for lab, f in steps:
    c.t(X0, y + 0.3, lab, 7.5, "bold", color=ORG)
    y = c.fbox(y + 0.52, f, 1.0, 9)
for i, s in enumerate(["A = อุบัติเหตุ 3 ปี · V = AADT เฉลี่ย 3 ปี (คัน/วัน)", "T = 3 ปี · L = 1 กม. · K = 1.645",
                       "Vᵢ, Rᵢ = ค่าของแต่ละคลัสเตอร์ในกลุ่มหน่วยงานเดียวกัน"]):
    c.t(X0, y + 0.3 + i * 0.36, s, 7.5)
y = c.levels(y + 1.2, ["R ≤ Ra", "Ra < R ≤ Rc", "R > Rc"])
c.t(X0, y + 0.27, "ลำดับการเทียบ: MnDOT [13] · สูง = DF > 1", 6.5, color=MUTED)
y += 0.5; c.panel_end(y); c.save(y + 0.05, "4-8ข-ปัจจัยที่2-Rate.png")

# ===================== ภาพที่ 4-8 (ค) ระดับรวม
c = C(GRAY, GRAY_BG)
y = c.panel_start(0.04, "ระดับรวม = ระดับที่สูงกว่าของ 2 ปัจจัย")
c.t(X0, y + 0.3, "เกินเกณฑ์ด้านใดด้านหนึ่งถือว่าเสี่ยง (WisDOT [14] · [1] หน้า 55)", 7, color=MUTED)
gx, cw, ch = X0 + 1.55, 1.62, 0.5
gy = y + 1.5
c.t(gx + 1.5 * cw, gy - 0.72, "ระดับตาม Rate →", 7.5, "bold", ha="center", color=ORG)
for j, k in enumerate(ORDER):
    c.t(gx + j * cw + cw / 2, gy - 0.25, LV[k][0], 7.5, "bold", ha="center", color=ORG)
c.t(X0 + 0.12, gy + 1.5 * ch, "ระดับตาม SI", 7.5, "bold", ha="center", color=BLUE, rotation=90)
for i, k in enumerate(ORDER):
    c.t(gx - 0.12, gy + i * ch + ch / 2, LV[k][0], 7.5, "bold", ha="right", color=BLUE)
    for j in range(3):
        lab, fc, tc = LV[ORDER[max(i, j)]]
        c.rect(gx + j * cw, gy + i * ch, cw - 0.06, ch - 0.06, fc)
        c.t(gx + j * cw + cw / 2 - 0.03, gy + i * ch + ch / 2 - 0.03, lab, 7.5, "bold", ha="center", color=tc)
y = gy + 3 * ch + 0.2
c.t(X0, y + 0.25, "ผลกับ 598 คลัสเตอร์ (จำนวนวง)", 8, "bold")
data = [("high", 27, 84, 111), ("medium", 123, 72, 167), ("low", 448, 442, 320)]
x = X0; y += 0.5
cols = [("ระดับ", 1.55), ("SI", 1.5), ("Rate", 1.5), ("ระดับรวม", 1.9)]
for name, w in cols:
    c.rect(x, y, w, 0.42, GRAY, "white"); c.t(x + w / 2, y + 0.21, name, 7, "bold", ha="center", color="white"); x += w
for i, (k, a, b, s) in enumerate(data):
    lab, fc, tc = LV[k]; x = X0; yy = y + 0.42 * (i + 1)
    for (name, w), v in zip(cols, (lab, a, b, s)):
        c.rect(x, yy, w, 0.42, fc if name == "ระดับ" else "white", "#C9CED4", 0.5)
        c.t(x + w / 2, yy + 0.21, f"{v}", 7.5, "bold" if name in ("ระดับ", "ระดับรวม") else "normal", ha="center",
            color=tc if name == "ระดับ" else INK)
        x += w
y += 0.42 * 4
c.t(X0, y + 0.3, "ไม่มีคลัสเตอร์ใดได้ระดับสูงจากทั้งสองปัจจัย", 7, color=MUTED)
c.t(X0, y + 0.62, "→ สองปัจจัยวัดความเสี่ยงคนละมิติ", 7, color=MUTED)
y += 0.85; c.panel_end(y); c.save(y + 0.05, "4-8ค-ระดับรวม.png")

# ===================== ข้อมูลตัวอย่าง 4-9
M = pd.read_pickle(os.path.join(HERE, "data", "M598.pkl"))
Z = M.set_index("id").loc[["zone_60", "zone_56", "zone_46"]]
z0 = Z.iloc[0]; a66, a67, a68 = (int(z0[f"AADT {yy}"]) for yy in (2566, 2567, 2568))
V, m, Ra, Rc = z0.V, z0.m, z0.Ra, z0.Rc
G = M[M.หน่วยงาน == "ทล."]; SV, SVR = G.V.sum(), (G.V * G.R).sum()
K = 1.645; sq = np.sqrt(Ra / m); half = 1 / (2 * m)
assert np.isclose(Ra + K * sq + half, Rc) and np.isclose(SVR / SV, Ra) and np.allclose(Z.R, Z.A / m)
f = lambda s: s.replace(",", "{,}")


def step_title(c, y, s, ref=""):
    c.t(X0, y + 0.28, s, 8, "bold", color=BLUE)
    if ref:
        c.t(W - X0, y + 0.28, ref, 6.5, ha="right", color=MUTED)
    return y + 0.5


# ===================== ภาพที่ 4-9 (ก) ขั้นที่ 0–2
c = C(BLUE, BLUE_BG)
y = c.panel_start(0.04, "ทล.35 ดาวคะนอง–แสมดำ: ขั้นที่ 0–2")
y = step_title(c, y + 0.05, "ขั้นที่ 0  ข้อมูลตั้งต้น", "อุบัติเหตุ 2566–2568")
y = c.table(y, [("คลัสเตอร์", 1.35), ("ช่วง กม.", 1.35), ("A", 0.9), ("ตาย", 0.9), ("เจ็บ", 0.9), ("SI", 1.05)],
            [[zid, r["กม. คลัสเตอร์"], f"{int(r.A)}", f"{int(r.เสียชีวิต)}", f"{int(r.บาดเจ็บ)}", f"{r.SI:.2f}"] for zid, r in Z.iterrows()])
c.t(X0, y + 0.3, "AADT ทล.35 กม. 6+500 (คัน/วัน):", 7.5)
c.t(X0, y + 0.66, f"2566 = {a66:,} · 2567 = {a67:,} · 2568 = {a68:,}", 7.5)
c.t(X0, y + 1.02, "ค่าคงที่: T = 3 ปี · L = 1 กม. · K = 1.645", 7.5)
y = step_title(c, y + 1.25, "ขั้นที่ 1  ปริมาณจราจรเฉลี่ย (V)")
y = c.fbox2(y, f(rf"$V = \dfrac{{{a66:,} + {a67:,} + {a68:,}}}{{3}}$"), f(rf"$= \mathbf{{{V:,.2f}}}$ คัน/วัน"))
y = step_title(c, y + 0.1, "ขั้นที่ 2  ปริมาณรถที่ผ่าน (MEV)", "[12] สมการ 4-8")
y = c.fbox2(y, f(rf"$MEV = \dfrac{{365 \times 3 \times {V:,.2f} \times 1}}{{1,000,000}}$"), rf"$= \mathbf{{{m:.2f}}}$ ล้านคัน")
y += 0.2; c.panel_end(y); c.save(y + 0.05, "4-9ก-ขั้นที่0-2.png")

# ===================== ภาพที่ 4-9 (ข) ขั้นที่ 3–5
c = C(BLUE, BLUE_BG)
y = c.panel_start(0.04, "ทล.35 ดาวคะนอง–แสมดำ: ขั้นที่ 3–5")
y = step_title(c, y + 0.05, "ขั้นที่ 3  อัตราการเกิดอุบัติเหตุ (R)", "[1] สมการ 3.2")
y = c.table(y, [("คลัสเตอร์", 1.6), ("A", 1.0), ("R = A / MEV", 2.35), ("R", 1.5)],
            [[zid, f"{int(r.A)}", f"{int(r.A)} / {m:.2f}", f"{r.R:.4f}"] for zid, r in Z.iterrows()])
y = step_title(c, y + 0.1, "ขั้นที่ 4  อัตราเฉลี่ยของกลุ่ม (Ra)", "[12] สมการ 4-10")
c.rect(X0, y, XW, 2.0, "white", BLUE, 0.7, True)
c.t(W / 2, y + 0.52, r"$R_a = \dfrac{\sum (V_i \times R_i)}{\sum V_i}$", 9, ha="center", color=BLUE)
c.t(W / 2, y + 1.48, f(rf"$= \dfrac{{{SVR:,.2f}}}{{{SV:,.0f}}} = \mathbf{{{Ra:.4f}}}$"), 9, ha="center", color=BLUE)
y += 2.0
c.t(X0, y + 0.27, f"คิดจากคลัสเตอร์กรมทางหลวงทั้งหมด {len(G)} วง", 7, color=MUTED)
y = step_title(c, y + 0.45, "ขั้นที่ 5  อัตราวิกฤติ (Rc)", "[1] สมการ 3.4")
c.rect(X0, y, XW, 2.55, "white", BLUE, 0.7, True)
c.t(W / 2, y + 0.5, r"$R_c = R_a + K\sqrt{\dfrac{R_a}{MEV}} + \dfrac{1}{2 \times MEV}$", 9, ha="center", color=BLUE)
c.t(W / 2, y + 1.35, rf"$= {Ra:.4f} + 1.645\sqrt{{\dfrac{{{Ra:.4f}}}{{{m:.2f}}}}} + \dfrac{{1}}{{2 \times {m:.2f}}}$", 8.5, ha="center", color=BLUE)
c.t(W / 2, y + 2.15, rf"$= {Ra:.4f} + {K * sq:.4f} + {half:.4f} = \mathbf{{{Rc:.4f}}}$", 8.5, ha="center", color=BLUE)
y += 2.55 + 0.2; c.panel_end(y); c.save(y + 0.05, "4-9ข-ขั้นที่3-5.png")

# ===================== ภาพที่ 4-9 (ค) ขั้นที่ 6
c = C(BLUE, BLUE_BG)
y = c.panel_start(0.04, "ทล.35 ดาวคะนอง–แสมดำ: ขั้นที่ 6")
y = step_title(c, y + 0.05, "เทียบ R กับ Ra และ Rc แล้วจัดระดับ", "MnDOT [13]")
x0, x1 = X0, X0 + XW; lo, hi = np.log10(0.08), np.log10(1.2)
X = lambda v: x0 + (np.log10(v) - lo) / (hi - lo) * (x1 - x0)
yl = y + 1.05
for a, b, k in ((x0, X(Ra), "low"), (X(Ra), X(Rc), "medium"), (X(Rc), x1, "high")):
    c.rect(a, yl, b - a, 0.4, LV[k][1])
c.t((x0 + X(Ra)) / 2, yl + 0.2, "ต่ำ", 7, "bold", ha="center", color=LV["low"][2])
c.t((X(Rc) + x1) / 2, yl + 0.2, "สูง", 7, "bold", ha="center", color=LV["high"][2])
for v, lab, ha, dy in ((Ra, f"Ra = {Ra:.4f}", "right", 0.72), (Rc, f"Rc = {Rc:.4f}", "left", 0.72)):
    c.ax.plot([X(v), X(v)], [yl - 0.1, yl + dy - 0.15], color=INK, lw=1.0)
    c.t(X(v) + (0.04 if ha == "left" else -0.04), yl + dy, lab, 6.5, "bold", ha=ha)
for (zid, r), dx in zip(Z.iterrows(), (-0.55, 0.45, -0.3)):
    c.ax.annotate(f"{zid}\nR = {r.R:.4f}", xy=(X(r.R), yl), xytext=(X(r.R) + dx, yl - 0.6), ha="center", va="center",
                  fontsize=6.5, color=INK, linespacing=1.1, arrowprops=dict(arrowstyle="-|>", color=INK, lw=0.7))
c.t(x1, yl + 0.72, "(สเกลลอการิทึม)", 6, ha="right", color=MUTED)
COND = {"low": "R ≤ Ra", "medium": "Ra < R ≤ Rc", "high": "R > Rc"}
y = c.table(yl + 1.05, [("คลัสเตอร์", 1.3), ("R", 1.1), ("เทียบเกณฑ์", 1.75), ("DF", 0.95), ("ระดับ", 1.35)],
            [[zid, f"{r.R:.4f}", COND[r["ระดับ_Rate"]], f"{r.R / Rc:.2f}", LV[r["ระดับ_Rate"]][0]] for zid, r in Z.iterrows()],
            fills=[LV[r["ระดับ_Rate"]] for _, r in Z.iterrows()])
c.t(X0, y + 0.27, "DF = R / Rc · DF > 1 คือเกินค่าวิกฤติ", 7, color=MUTED)
y += 0.5; c.panel_end(y); c.save(y + 0.05, "4-9ค-ขั้นที่6.png")
