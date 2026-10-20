"""รูปตัวอย่างการคำนวณ R, Ra, Rc และการแบ่งระดับแบบละเอียด จากข้อมูลจริง (ทล.35 ดาวคะนอง–แสมดำ)"""
import os
import numpy as np, pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "..", "outputs", "ภาพตัวอย่างการคำนวณ-R-Ra-Rc-ดาวคะนอง-แสมดำ.png")
plt.rcParams["font.family"] = "Tahoma"; plt.rcParams["mathtext.fontset"] = "dejavusans"

# ---------- ค่าจริงจากข้อมูล (คำนวณสด ไม่พิมพ์มือ)
M = pd.read_pickle(os.path.join(HERE, "data", "M598.pkl"))
Z = M.set_index("id").loc[["zone_60", "zone_56", "zone_46"]]
z0 = Z.iloc[0]; a66, a67, a68 = (int(z0[f"AADT {y}"]) for y in (2566, 2567, 2568))
V, m, Ra, Rc = z0.V, z0.m, z0.Ra, z0.Rc
G = M[M.หน่วยงาน == "ทล."]; SA, SM, SV, SVR = int(G.A.sum()), G.m.sum(), G.V.sum(), (G.V * G.R).sum()
K = 1.645; sq = np.sqrt(Ra / m); ksq = K * sq; half = 1 / (2 * m)
assert np.isclose(Ra + ksq + half, Rc) and np.isclose(SVR / SV, Ra)

BG, INK, MUTED = "#FFFFFF", "#1F2328", "#57606A"
NAVY, NAVY_BG, ORG = "#1C5CAB", "#EEF4FB", "#C2551F"
LOW, MED, HIGH = "#CDEBD3", "#FCE8A6", "#F6C1B0"; LOW_T, MED_T, HIGH_T = "#1E6B33", "#7A5A00", "#9C2B12"
fig = plt.figure(figsize=(13, 21.0), facecolor=BG)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 100); ax.set_ylim(0, 162); ax.axis("off")

def t(x, y, s, size=12, color=INK, weight="normal", ha="left", va="center"):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va)
def step(y_top, h, num, title, ref):
    ax.add_patch(FancyBboxPatch((3, y_top - h), 94, h, boxstyle="round,pad=0,rounding_size=1", fc=NAVY_BG, ec=NAVY, lw=1.3))
    ax.add_patch(FancyBboxPatch((3, y_top - 4.6), 94, 4.6, boxstyle="round,pad=0,rounding_size=1", fc=NAVY, ec=NAVY))
    t(5, y_top - 2.3, f"ขั้นที่ {num}  {title}", 14.5, "white", "bold")
    t(95, y_top - 2.3, ref, 10.5, "white", ha="right")
def wbox(x, y, w, h):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle="round,pad=0,rounding_size=0.6", fc="white", ec="#B7C6DA", lw=1))

# ---------- หัวเรื่อง
t(50, 159, "ตัวอย่างการคำนวณ R, Ra, Rc และการแบ่งระดับจุดเสี่ยง จากข้อมูลจริง", 19, INK, "bold", ha="center")
t(50, 155.8, "ทางหลวงหมายเลข 35 (ดาวคะนอง – แสมดำ) ตอนควบคุม 0100 · กรุงเทพมหานคร · 3 คลัสเตอร์บนถนนเส้นเดียวกัน", 12, MUTED, ha="center")

# ---------- ขั้นที่ 0 ข้อมูลตั้งต้น
y = 152.5; step(y, 23, 0, "ข้อมูลตั้งต้น", "อุบัติเหตุ: MOT Data Catalog 2566–2568 · AADT: กรมทางหลวง")
cols = [6, 22, 37, 52, 67, 82]
for x, hh in zip(cols, ["คลัสเตอร์", "ช่วง กม.", "A (ครั้ง, 3 ปี)", "เสียชีวิต", "บาดเจ็บ", "SI"]): t(x, y - 7.2, hh, 11.5, NAVY, "bold")
for i, (zid, r) in enumerate(Z.iterrows()):
    yy = y - 10.2 - i * 2.9
    for x, v in zip(cols, [zid, r["กม. คลัสเตอร์"], f"{int(r.A)}", f"{int(r.เสียชีวิต)}", f"{int(r.บาดเจ็บ)}", f"{r.SI:.2f}"]): t(x, yy, v, 12)
t(6, y - 21.1, f"AADT ของสถานีตัวแทนตอนควบคุม (station_id 127, ทล.35 กม. 6+500):  ปี 2566 = {a66:,}  ·  2567 = {a67:,}  ·  2568 = {a68:,} คัน/วัน", 11.2)
t(6, y - 18.6, "ค่าคงที่:  T = 3 ปี (2566–2568)  ·  L = 1 กม.  ·  K = 1.645 (ความเชื่อมั่น 95%)", 11.2)

# ---------- ขั้นที่ 1 V
y = 127.5; step(y, 11.5, 1, "หาปริมาณจราจรเฉลี่ยต่อวัน (V)", "ค่าเฉลี่ยของ AADT ปี 2566–2568")
wbox(6, y - 10.6, 88, 5.3)
t(50, y - 7.95, rf"$V = \dfrac{{{a66:,} + {a67:,} + {a68:,}}}{{3}} = \mathbf{{{V:,.2f}}}$ คัน/วัน".replace(",", "{,}"), 14.5, NAVY, ha="center")

# ---------- ขั้นที่ 2 MEV
y = 114.5; step(y, 13.5, 2, "หาปริมาณรถที่ผ่านตลอดช่วงที่ศึกษา (MEV)", "AASHTO (2010) HSM สมการ 4-8 หน้า 4-42")
wbox(6, y - 10.6, 88, 5.3)
t(50, y - 7.95, rf"$MEV = \left(\dfrac{{V}}{{1,000,000}}\right) \times T \times 365 = \left(\dfrac{{{V:,.2f}}}{{1,000,000}}\right) \times 3 \times 365 = \mathbf{{{m:.2f}}}$".replace(",", "{,}"), 14, NAVY, ha="center")
t(6, y - 12.3, "MEV (Million Entering Vehicles) คือ ปริมาณรถทั้งหมดที่ผ่านจุดที่ศึกษาตลอดช่วงเวลาที่ศึกษา หน่วยเป็นล้านคัน · HSM ใช้ TEV และ n ของทางแยก งานนี้ใช้ V และ T แทน", 9.8, MUTED)

# ---------- ขั้นที่ 3 R
y = 100.0; step(y, 24.3, 3, "หาอัตราการเกิดอุบัติเหตุ (R) ของแต่ละคลัสเตอร์", "ณัฐพงศ์ (2558) สมการ 3.2 · HSM สมการ 4-9 (L = 1 กม.)")
wbox(6, y - 10.8, 88, 5.6)
t(50, y - 8.0, r"$R = \dfrac{A \times 1{,}000{,}000}{365 \times T \times V \times L} = \dfrac{A}{MEV}$", 15, NAVY, ha="center")
for i, (zid, r) in enumerate(Z.iterrows()):
    yy = y - 14.2 - i * 3.9
    t(6, yy, zid, 12, INK, "bold")
    t(19, yy, rf"$R = \dfrac{{{int(r.A)} \times 1,000,000}}{{365 \times 3 \times {V:,.2f} \times 1}} = \dfrac{{{int(r.A)*1_000_000:,}}}{{{365*3*V:,.0f}}} = \mathbf{{{r.R:.4f}}}$".replace(",", "{,}"), 11.3, INK)

# ---------- ขั้นที่ 4 Ra
y = 74.5; step(y, 17, 4, "หาอัตราการเกิดอุบัติเหตุเฉลี่ยของกลุ่ม (Ra)", "AASHTO (2010) HSM สมการ 4-10 หน้า 4-43")
wbox(6, y - 11.0, 88, 5.8)
t(50, y - 8.1, rf"$R_a = \dfrac{{\sum (V_i \times R_i)}}{{\sum V_i}} = \dfrac{{{SVR:,.2f}}}{{{SV:,.0f}}} = \mathbf{{{Ra:.4f}}}$".replace(",", "{,}"), 14.5, NAVY, ha="center")
t(6, y - 13.4, f"Rᵢ = ค่า R ของคลัสเตอร์ที่ i (ขั้นที่ 3) · Vᵢ ใช้แทน TEVᵢ ของ HSM · คิดจากคลัสเตอร์กรมทางหลวงทั้งหมด {len(G)} แห่ง · ตรวจซ้ำ: ΣA / ΣMEV = {SA:,} / {SM:,.2f} = {SA/SM:.4f}", 10.6, MUTED)
t(6, y - 15.6, f"กลุ่ม ทล. {len(G)} จาก {len(M)} คลัสเตอร์ที่มีข้อมูล · กลุ่ม กทพ. {(M.หน่วยงาน == 'กทพ.').sum()} และ ทช. {(M.หน่วยงาน == 'ทช.').sum()} คลัสเตอร์ คิด Ra แยกของตัวเอง (HSM: reference populations)", 10.6, MUTED)

# ---------- ขั้นที่ 5 Rc
y = 55.5; step(y, 18.5, 5, "หาอัตราการเกิดอุบัติเหตุวิกฤติ (Rc)", "ณัฐพงศ์ (2558) สมการ 3.4 · HSM สมการ 4-11 (K = P = 1.645)")
wbox(6, y - 17.6, 88, 12.4)
t(50, y - 8.3, r"$R_c = R_a + K\left[\dfrac{R_a}{MEV}\right]^{0.5} + \dfrac{1}{2 \times MEV}$", 14, NAVY, ha="center")
t(50, y - 12.6, rf"$= {Ra:.4f} + 1.645\left[\dfrac{{{Ra:.4f}}}{{{m:.2f}}}\right]^{{0.5}} + \dfrac{{1}}{{2 \times {m:.2f}}}$", 13, INK, ha="center")
t(50, y - 16.0, rf"$= {Ra:.4f} + (1.645 \times {sq:.5f}) + {half:.5f} = {Ra:.4f} + {ksq:.5f} + {half:.5f} = \mathbf{{{Rc:.4f}}}$", 13, INK, ha="center")

# ---------- ขั้นที่ 6 แบ่งระดับ
y = 35.0; step(y, 33, 6, "จัดระดับจุดเสี่ยงโดยเทียบ R กับ Ra และ Rc", "ลำดับขั้นตาม MnDOT (2010) · DF > 1 ตามณัฐพงศ์ หน้า 54")
# เส้นจำนวน (สเกลลอการิทึม)
x0, x1 = 10, 90; lo, hi = np.log10(0.08), np.log10(1.2)
X = lambda v: x0 + (np.log10(v) - lo) / (hi - lo) * (x1 - x0)
yl = y - 13.0
ax.add_patch(Rectangle((x0, yl - 1.3), X(Ra) - x0, 2.6, fc=LOW, ec="none"))
ax.add_patch(Rectangle((X(Ra), yl - 1.3), X(Rc) - X(Ra), 2.6, fc=MED, ec="none"))
ax.add_patch(Rectangle((X(Rc), yl - 1.3), x1 - X(Rc), 2.6, fc=HIGH, ec="none"))
t((x0 + X(Ra)) / 2, yl, "ต่ำ", 11, LOW_T, "bold", ha="center"); t((X(Ra) + X(Rc)) / 2, yl, "กลาง", 10, MED_T, "bold", ha="center")
t((X(Rc) + x1) / 2, yl, "สูง", 11, HIGH_T, "bold", ha="center")
for v, lab in ((Ra, f"Ra = {Ra:.4f}"), (Rc, f"Rc = {Rc:.4f}")):
    ax.plot([X(v), X(v)], [yl - 2.2, yl + 2.2], color=INK, lw=1.6); t(X(v) + (-0.6 if v == Ra else 0.6), yl - 3.4, lab, 10.5, INK, "bold", ha="right" if v == Ra else "left")
for i, (zid, r) in enumerate(Z.iterrows()):
    ax.annotate(f"{zid}\nR = {r.R:.4f}", xy=(X(r.R), yl + 1.3), xytext=(X(r.R) + (-3, 4, 0)[i], yl + 5.2),
                ha="center", fontsize=10.5, color=INK, arrowprops=dict(arrowstyle="-|>", color=INK, lw=1.1))
t(x1, yl - 3.4, "R (สเกลลอการิทึม)", 9.5, MUTED, ha="right")
# ตารางผล
cx = [6, 21, 41, 66, 80]
for x, hh in zip(cx, ["คลัสเตอร์", "R", "เทียบเกณฑ์", "DF = R/Rc", "ระดับ"]): t(x, y - 20.0, hh, 11.5, NAVY, "bold")
LV = {"low": ("ต่ำ", LOW, LOW_T), "medium": ("ปานกลาง", MED, MED_T), "high": ("สูง", HIGH, HIGH_T)}
for i, (zid, r) in enumerate(Z.iterrows()):
    yy = y - 23.4 - i * 3.1
    lab, fc, tc = LV[r["ระดับ_Rate"]]
    cond = {"low": f"R ≤ Ra  ({r.R:.4f} ≤ {Ra:.4f})", "medium": f"Ra < R ≤ Rc  ({Ra:.4f} < {r.R:.4f} ≤ {Rc:.4f})",
            "high": f"R > Rc  ({r.R:.4f} > {Rc:.4f})"}[r["ระดับ_Rate"]]
    ax.add_patch(Rectangle((79, yy - 1.3), 14, 2.6, fc=fc, ec="none"))
    for x, v, wgt in zip(cx, [zid, f"{r.R:.4f}", cond, f"{r.R / Rc:.2f}", lab], ["bold", "normal", "normal", "normal", "bold"]):
        t(x if x != 80 else 86, yy, v, 11.3 if x != 41 else 10.3, tc if x == 80 else INK, wgt, ha="center" if x == 80 else "left")

# ---------- ท้ายรูป
t(50, 0.9, "ที่มา: ณัฐพงศ์ ซื่อสัตย์ (2558) สมการ 3.2–3.4 · AASHTO (2010) Highway Safety Manual สมการ 4-8 ถึง 4-11 · Minnesota DOT (2010) · ค่าทุกตัวคำนวณจากไฟล์ ค่า-R-Ra-Rc-598คลัสเตอร์.xlsx",
  9.5, MUTED, ha="center")
fig.savefig(OUT, dpi=150, facecolor=BG); print("saved", os.path.abspath(OUT))
