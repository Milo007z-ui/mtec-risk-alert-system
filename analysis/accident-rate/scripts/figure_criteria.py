import os
"""รูปสรุปเกณฑ์แบ่งระดับจุดเสี่ยง: ① Accident Severity ② Accident Rate + RQC ③ รวมด้วยกฎค่าสูงสุด"""
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import FancyBboxPatch, Rectangle

plt.rcParams["font.family"] = "Tahoma"
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "outputs", "ภาพสรุปเกณฑ์แบ่งระดับจุดเสี่ยง-SI-AccidentRate-มีอ้างอิง.png")
BG, INK, MUTED = "#FFFFFF", "#1F2328", "#57606A"
BLUE, BLUE_BG = "#1C5CAB", "#EAF2FB"
ORG, ORG_BG = "#C2551F", "#FDF0E8"
LOW, MED, HIGH = "#CDEBD3", "#FCE8A6", "#F6C1B0"
LOW_T, MED_T, HIGH_T = "#1E6B33", "#7A5A00", "#9C2B12"

fig = plt.figure(figsize=(16, 12.2), facecolor=BG)
ax = fig.add_axes([0, 0, 1, 1]); ax.set_xlim(0, 160); ax.set_ylim(0, 122); ax.axis("off")

def box(x, y, w, h, fc, ec, r=1.2, lw=1.4):
    ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}", fc=fc, ec=ec, lw=lw))
def t(x, y, s, size=12, color=INK, weight="normal", ha="left", va="center", **kw):
    ax.text(x, y, s, fontsize=size, color=color, fontweight=weight, ha=ha, va=va, **kw)
def level_bar(x, y, w, labels, conds, h=6.2):
    cw = w / 3
    for i, (lab, cond, fc, tc) in enumerate(zip(labels, conds, (LOW, MED, HIGH), (LOW_T, MED_T, HIGH_T))):
        ax.add_patch(Rectangle((x + i * cw, y), cw - 0.6, h, fc=fc, ec="none"))
        t(x + i * cw + cw / 2 - 0.3, y + h * 0.68, lab, 12.5, tc, "bold", ha="center")
        t(x + i * cw + cw / 2 - 0.3, y + h * 0.27, cond, 11.5, tc, ha="center")

# ---------- หัวเรื่อง
t(80, 117.5, "เกณฑ์การแบ่งระดับจุดเสี่ยงอุบัติเหตุ: Accident Severity ร่วมกับ Accident Rate", 20, INK, "bold", ha="center")
t(80, 113.2, "คลัสเตอร์จุดเสี่ยง 598 จุด (มีข้อมูลปริมาณจราจรของหน่วยงานครบ 3 ปี 2566–2568) · แต่ละวิธีให้ระดับ ต่ำ / ปานกลาง / สูง แยกกัน แล้วนำมารวม",
  12.5, MUTED, ha="center")

# ---------- ① SI
X1, W = 4, 74
box(X1, 42, W, 67, BLUE_BG, BLUE)
ax.add_patch(FancyBboxPatch((X1, 101.5), W, 7.5, boxstyle="round,pad=0,rounding_size=1.2", fc=BLUE, ec=BLUE))
t(X1 + 2.5, 105.2, "วิธีที่ 1  Accident Severity Index (SI)", 16, "white", "bold")
t(X1 + W - 2.5, 105.2, "วัด \"เกิดแล้วรุนแรงแค่ไหน\"", 12, "white", ha="right")
box(X1 + 4, 86.5, W - 8, 11.5, "white", BLUE, lw=1.1)
t(X1 + W / 2, 92.3, r"$SI = \dfrac{F + PI}{\mathrm{Total\ Accidents}}$", 22, BLUE, ha="center")
for i, s in enumerate(["F    = จำนวนครั้งของอุบัติเหตุที่มีผู้เสียชีวิต",
                       "PI   = จำนวนผู้บาดเจ็บ (สาหัส + เล็กน้อย)",
                       "Total Accidents = จำนวนอุบัติเหตุทั้งหมดในคลัสเตอร์ (3 ปี)"]):
    t(X1 + 4, 81.5 - i * 4.3, s, 12.5)
t(X1 + 4, 67.3, "ความหมาย: จำนวนผู้เสียชีวิต/บาดเจ็บเฉลี่ยต่ออุบัติเหตุ 1 ครั้ง", 12, MUTED)
t(X1 + 4, 62.2, "เกณฑ์แบ่งระดับ", 13, BLUE, "bold")
level_bar(X1 + 4, 52.5, W - 8, ["ต่ำ", "ปานกลาง", "สูง"], ["SI < 1", "1 ≤ SI < 2", "SI ≥ 2"])
t(X1 + 4, 48.3, "สูตร: ณัฐพงศ์ (2558) สมการ 2.6 หน้า 7", 10.3, MUTED)
t(X1 + 4, 45.3, "จุดตัด 1 และ 2 กำหนดโดยผู้วิจัย สอดคล้องกับช่วงที่ราบของการกระจาย SI", 10.3, MUTED)

# ---------- ② Rate + RQC
X2 = 82
box(X2, 42, W, 67, ORG_BG, ORG)
ax.add_patch(FancyBboxPatch((X2, 101.5), W, 7.5, boxstyle="round,pad=0,rounding_size=1.2", fc=ORG, ec=ORG))
t(X2 + 2.5, 105.2, "วิธีที่ 2  Accident Rate + Rate Quality Control", 16, "white", "bold")
t(X2 + W - 2.5, 105.2, "วัด \"เกิดบ่อยผิดปกติไหม\"", 12, "white", ha="right")
steps = [("ขั้น 1  อัตราการเกิดอุบัติเหตุ (ณัฐพงศ์ สมการ 3.2)", r"$R = \dfrac{A \times 1{,}000{,}000}{365 \times T \times V \times L}$", 7.0, 17),
         ("ขั้น 2  Ra ค่าเฉลี่ยถ่วงน้ำหนักด้วยปริมาณจราจร (HSM สมการ 4-10)", r"$R_a = \dfrac{\sum\,(V_i \times R_i)}{\sum\,V_i}$", 7.0, 17),
         ("ขั้น 3  Rc ค่าวิกฤติ 95% (ณัฐพงศ์ สมการ 3.4 · HSM สมการ 4-11)",
          r"$R_c = R_a + K\left[\dfrac{R_a}{\frac{365 \times T \times V \times L}{1{,}000{,}000}}\right]^{0.5} + \dfrac{1}{2 \times \left(\frac{365 \times T \times V \times L}{1{,}000{,}000}\right)}$", 12.5, 16.5)]
y = 99.0
for lab, f, h, fs in steps:
    t(X2 + 4, y, lab, 11, MUTED)
    box(X2 + 4, y - 2.0 - h, W - 8, h, "white", ORG, r=0.8, lw=1.0)
    t(X2 + W / 2, y - 2.0 - h / 2, f, fs, ORG, ha="center")
    y = y - 2.0 - h - 2.4
t(X2 + 4, 59.6, "V = AADT เฉลี่ย 3 ปี (คัน/วัน) · T = 3 ปี · L = 1 กม. · K = 1.645 · Vᵢ, Rᵢ ของแต่ละคลัสเตอร์ในกลุ่ม", 10.4)
t(X2 + 4, 56.3, "เกณฑ์แบ่งระดับ", 13, ORG, "bold", va="center")
level_bar(X2 + 4, 47.4, W - 8, ["ต่ำ", "ปานกลาง", "สูง"], ["R ≤ Ra", "Ra < R ≤ Rc", "R > Rc"])
t(X2 + 4, 44.6, "ลำดับขั้นตาม MnDOT (2010): เทียบค่าเฉลี่ย Ra ก่อน แล้วทดสอบค่าวิกฤติ Rc · สูง = DF > 1 (ณัฐพงศ์ หน้า 54)", 10.0, MUTED)

# ---------- ลูกศรลงไปส่วนรวม
for x in (X1 + W / 2, X2 + W / 2):
    ax.annotate("", xy=(80, 37.5), xytext=(x, 42), arrowprops=dict(arrowstyle="-|>", color=MUTED, lw=1.6,
                connectionstyle="arc3,rad=0"))

# ---------- ③ รวม
box(4, 2, 152, 35.5, "#F6F8FA", "#8C959F")
t(8, 33.2, "รวม 2 วิธี:  ระดับรวม = ระดับที่สูงกว่า ระหว่าง SI กับ Rate", 16, INK, "bold")
t(8, 28.6, "เกินเกณฑ์ด้านความรุนแรงหรือด้านอัตราอย่างใดอย่างหนึ่ง ถือว่าเสี่ยง (WisDOT Figure 3 · ณัฐพงศ์ หน้า 55)", 12, MUTED)
# ตาราง 3x3
gx, gy, cw, ch = 34, 3.6, 15.5, 5.6
lv = [("ต่ำ", LOW, LOW_T), ("ปานกลาง", MED, MED_T), ("สูง", HIGH, HIGH_T)]
t(gx + 1.5 * cw, gy + 3 * ch + 4.9, "ระดับตาม Rate →", 11.5, ORG, "bold", ha="center")
t(gx - 22, gy + 1.5 * ch, "ระดับ\nตาม SI\n↓", 11.5, BLUE, "bold", ha="center", linespacing=1.3)
for j, (name, _, _) in enumerate(lv):
    t(gx + j * cw + cw / 2, gy + 3 * ch + 1.6, name, 11.5, ORG, "bold", ha="center")
for i, (name, _, _) in enumerate(lv):
    yy = gy + (2 - i) * ch
    t(gx - 1.2, yy + ch / 2, name, 11.5, BLUE, "bold", ha="right")
    for j in range(3):
        k = max(i, j); lab, fc, tc = lv[k]
        ax.add_patch(Rectangle((gx + j * cw, yy), cw - 0.5, ch - 0.5, fc=fc, ec="none"))
        t(gx + j * cw + cw / 2 - 0.25, yy + ch / 2 - 0.2, lab, 12, tc, "bold", ha="center")
# ผลลัพธ์จริง
rx = 92
t(rx, 25.0, "ผลกับ 598 คลัสเตอร์", 13.5, INK, "bold")
hdr = ["", "SI อย่างเดียว", "Rate อย่างเดียว", "SI + Rate"]
data = [("สูง", 27, 84, 111, HIGH, HIGH_T), ("ปานกลาง", 123, 72, 167, MED, MED_T), ("ต่ำ", 448, 442, 320, LOW, LOW_T)]
xs = [rx, rx + 15, rx + 31, rx + 48]
for x, hh in zip(xs, hdr): t(x + (6 if hh else 0), 20.8, hh, 11, MUTED, ha="center" if hh else "left")
for i, (lab, a, b, c, fc, tc) in enumerate(data):
    y = 16.6 - i * 4.4
    ax.add_patch(Rectangle((rx - 0.5, y - 2), 11, 4, fc=fc, ec="none"))
    t(rx + 5, y, lab, 11.5, tc, "bold", ha="center")
    for x, v, bold in ((xs[1], a, False), (xs[2], b, False), (xs[3], c, True)):
        t(x + 6, y, f"{v}", 12.5, INK, "bold" if bold else "normal", ha="center")
t(rx, 3.8, "ไม่มีคลัสเตอร์ใดที่ได้ระดับสูงจากทั้งสองวิธี → สองวิธีวัดความเสี่ยงคนละมิติ", 10.8, MUTED)

fig.savefig(OUT, dpi=150, facecolor=BG)
print("saved", OUT)
