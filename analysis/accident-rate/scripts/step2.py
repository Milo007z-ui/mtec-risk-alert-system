"""ขั้นที่ 2: ทางพิเศษ (กทพ.) แบบ ก. รายสายทาง = ยอดรถผ่านทุกด่านในสาย ÷ 365 ปีงบ 2566–2568 (ดึงสดจาก API กทพ.)"""
import os
import json
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

HERE = os.path.dirname(os.path.abspath(__file__))
PROJ = os.environ.get("MTEC_OUT", os.path.join(HERE, "..", "outputs")) + "/"
DL = os.environ.get("MTEC_RAW", os.path.join(HERE, "..", "data-raw")) + "/"
SP = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data") + "/"
API = "https://exat-man.web.app/api/EXAT_TrafficStatByPlaza/{}"
CAT = "https://catalog.exat.co.th/dataset/4f2d1df0-4ee3-4f29-8e38-b4be3ae140d1"
CAT_RES = CAT + "/resource/029a49c5-81f3-4bde-a0cc-edb284a8a9bf"
DOCS = "https://exat-man.web.app/docs"
Y = (2566, 2567, 2568)

raw = pd.concat([pd.DataFrame(json.load(open(SP + f"exat_{y}.json", encoding="utf-8"))["result"]) for y in Y])
raw = raw[["year", "highway_name", "plaza_name", "traffic"]].rename(columns={"year": "ปีงบประมาณ", "highway_name": "สายทาง (highway_name)",
                                                                            "plaza_name": "ด่าน (plaza_name)", "traffic": "ยอดรถทั้งปี (traffic)"})
raw["ปีงบประมาณ"] = raw["ปีงบประมาณ"].astype(int); raw["ยอดรถทั้งปี (traffic)"] = raw["ยอดรถทั้งปี (traffic)"].astype(int)
raw["ค่าซ้ำกับด่านอื่นในสายเดียวกัน"] = raw.duplicated(["ปีงบประมาณ", "สายทาง (highway_name)", "ยอดรถทั้งปี (traffic)"], keep=False).map({True: "ซ้ำ", False: ""})
cat = pd.read_csv(SP + "exat_cat.csv", encoding="utf-8-sig")

rows = []
for name, g in raw.groupby("สายทาง (highway_name)"):
    r = {"สายทาง (highway_name)": name}
    for y in Y:
        s = g[g.ปีงบประมาณ == y]["ยอดรถทั้งปี (traffic)"]
        r[f"จำนวนด่าน {y}"] = len(s); r[f"ยอดรวมทั้งปี {y}"] = int(s.sum()); r[f"เฉลี่ยต่อวัน {y}"] = round(s.sum() / 365, 1)
    c66 = cat[(cat.year_exat == 2566) & (cat.highway_name == name)].traffic_all.sum()
    assert c66 == r["ยอดรวมทั้งปี 2566"], name        # CSV แคตตาล็อก = API
    r["V = เฉลี่ย 3 ปี (คัน/วัน)"] = round(sum(r[f"เฉลี่ยต่อวัน {y}"] for y in Y) / 3, 1)
    for y in Y: r[f"ลิงก์ API {y}"] = API.format(y)
    r["วิธีค้นในลิงก์"] = f"รวมค่า traffic ทุกแถวที่ highway_name = {name} แล้ว ÷ 365"
    rows.append(r)
R = pd.DataFrame(rows)

k = pd.read_excel(PROJ + "AADT-ครบทุกคลัสเตอร์-630-3ปี.xlsx", sheet_name="คลัสเตอร์630")
e = k[k.หน่วยงาน == "กทพ."].copy()
e["สายทาง (highway_name)"] = e["ตอนที่จับคู่"].str.replace("^ทางพิเศษ(?=[^ก])", "", regex=True)
e.loc[e["สายทาง (highway_name)"].str.startswith("กาญจนาภิเษก"), "สายทาง (highway_name)"] = "ทางพิเศษกาญจนาภิเษก(บางพลี-สุขสวัสดิ์)"
e = e.merge(R[["สายทาง (highway_name)"] + [f"เฉลี่ยต่อวัน {y}" for y in Y]], on="สายทาง (highway_name)", how="left")
miss = e[e["เฉลี่ยต่อวัน 2566"].isna()]
print("คลัสเตอร์ กทพ.", len(e), "จับคู่สายได้", len(e) - len(miss), "| ไม่มีสายใน API:", miss[["id", "route_code", "ถนน"]].values.tolist())
e.loc[e["เฉลี่ยต่อวัน 2566"].isna(), "สายทาง (highway_name)"] = "— ไม่มีสายนี้ใน API กทพ. —"
C = e[["id", "ถนน", "จังหวัด", "route_code", "กม. คลัสเตอร์", "สายทาง (highway_name)", "A", "เสียชีวิต", "บาดเจ็บ", "SI", "ระดับ_SI",
       "เฉลี่ยต่อวัน 2566", "เฉลี่ยต่อวัน 2567", "เฉลี่ยต่อวัน 2568"]].sort_values(["สายทาง (highway_name)", "id"]).reset_index(drop=True)
C["V = เฉลี่ย 3 ปี"] = None; C["T (ปี)"] = 3; C["L (กม.)"] = 1
print(C.groupby("สายทาง (highway_name)").agg(n=("id", "size"), A=("A", "sum")).to_string())

out = PROJ + "ขั้นที่2-ปริมาณจราจร-ทางพิเศษ-กทพ-3ปี.xlsx"
with pd.ExcelWriter(out, engine="openpyxl") as w:
    R.to_excel(w, sheet_name="7 สายทาง", index=False)
    C.to_excel(w, sheet_name="126 คลัสเตอร์ + Accident Rate", index=False)
    raw.to_excel(w, sheet_name="รายด่าน (ข้อมูลดิบจาก API)", index=False)
    pd.DataFrame({"รายการ": [
        "แหล่งข้อมูล", "", "", "", "วิธีคำนวณ V", "ตรวจเทียบแล้ว", "ข้อควรระวัง ①", "ข้อควรระวัง ②", "ข้อควรระวัง ③", "สูตร"],
        "รายละเอียด": [
        f"API สถิติปริมาณจราจรจำแนกตามด่าน ของการทางพิเศษแห่งประเทศไทย: {API.format('{ปีงบ}')} (เปิดลิงก์ในเบราว์เซอร์ได้เลย ได้ข้อมูลแบบ JSON)",
        f"เอกสาร API (หน้าเว็บอธิบายวิธีเรียก): {DOCS}",
        f"หน้าชุดข้อมูลในแคตตาล็อกข้อมูลเปิดของ กทพ.: {CAT}",
        f"ไฟล์ CSV ในแคตตาล็อก (มีปีงบ 2564–2566 ใช้ตรวจเทียบปี 2566): {CAT_RES}",
        "ยอดรถผ่านด่านทั้งปีของทุกด่านในสายเดียวกัน รวมกัน ÷ 365 = รถเฉลี่ยต่อวันของสาย แล้วเฉลี่ย 3 ปีงบ (2566, 2567, 2568)",
        "ยอดรวมปี 2566 จาก API = จากไฟล์ CSV ในแคตตาล็อก ทุกสาย (ตรงกันทุกคัน)",
        "เป็นปริมาณรถที่ขึ้นทางพิเศษผ่านด่านของทั้งสาย ไม่ใช่ AADT ที่วัดตรงจุดเกิดเหตุ ทุกคลัสเตอร์ในสายเดียวกันจึงได้ค่า V เท่ากัน",
        "ด่านประชาชื่น (ขาเข้า-ในเมือง) กับ (ขาเข้า-นอกเมือง) ของสายศรีรัช มีตัวเลขเท่ากันทุกปี (ทำเครื่องหมาย 'ซ้ำ' ในชีตรายด่าน) อาจเป็นการบันทึกซ้ำของ กทพ. แต่ใช้ตามตัวเลขที่ กทพ. เผยแพร่",
        "ปีงบ 2566 = 1 ต.ค. 2565 – 30 ก.ย. 2566 (ปีงบประมาณ ไม่ใช่ปีปฏิทิน)",
        "R = A × 1,000,000 / (365 × T × V × L) · T = 3 ปี · L = 1 กม."]}).to_excel(w, sheet_name="แหล่งข้อมูลและวิธีตรวจ", index=False)

wb = load_workbook(out); blue = PatternFill("solid", fgColor="1C5CAB"); orange = PatternFill("solid", fgColor="EB6834")
for ws in wb:
    for c in ws[1]: c.font = Font(bold=True, color="FFFFFF"); c.fill = blue; c.alignment = Alignment(wrap_text=True, vertical="center")
    ws.row_dimensions[1].height = 42; ws.freeze_panes = "B2"; ws.auto_filter.ref = ws.dimensions
    for j in range(1, ws.max_column + 1): ws.column_dimensions[get_column_letter(j)].width = 14
    ws.column_dimensions["A"].width = 34
ws = wb["7 สายทาง"]; h = {c.value: c.column for c in ws[1]}
for r in range(2, ws.max_row + 1):
    for y in Y:
        c = ws.cell(r, h[f"ลิงก์ API {y}"]); c.hyperlink = c.value; c.font = Font(color="0563C1", underline="single")
        ws.cell(r, h[f"ยอดรวมทั้งปี {y}"]).number_format = "#,##0"; ws.cell(r, h[f"เฉลี่ยต่อวัน {y}"]).number_format = "#,##0.0"
    ws.cell(r, h["V = เฉลี่ย 3 ปี (คัน/วัน)"]).number_format = "#,##0.0"
for y in Y: ws.column_dimensions[get_column_letter(h[f"ลิงก์ API {y}"])].width = 30
ws.column_dimensions[get_column_letter(h["วิธีค้นในลิงก์"])].width = 60

ws = wb["126 คลัสเตอร์ + Accident Rate"]; h = {c.value: c.column for c in ws[1]}; n = ws.max_row
extra = ["ตัวตั้ง A×1,000,000", "ตัวหาร 365×T×V×L", "R (ครั้ง/ล้านคัน-กม.)", "อันดับ R"]
for name in extra: ws.cell(1, ws.max_column + 1, name)
h = {c.value: c.column for c in ws[1]}; L = lambda x: get_column_letter(h[x])
for x in extra + ["V = เฉลี่ย 3 ปี"]: ws.cell(1, h[x]).fill = orange; ws.cell(1, h[x]).font = Font(bold=True, color="FFFFFF")
for r in range(2, n + 1):
    if ws[f"{L('เฉลี่ยต่อวัน 2566')}{r}"].value is None: continue
    ws[f"{L('V = เฉลี่ย 3 ปี')}{r}"] = f"=AVERAGE({L('เฉลี่ยต่อวัน 2566')}{r}:{L('เฉลี่ยต่อวัน 2568')}{r})"
    ws[f"{L(extra[0])}{r}"] = f"={L('A')}{r}*1000000"
    ws[f"{L(extra[1])}{r}"] = f"=365*{L('T (ปี)')}{r}*{L('V = เฉลี่ย 3 ปี')}{r}*{L('L (กม.)')}{r}"
    ws[f"{L(extra[2])}{r}"] = f"={L(extra[0])}{r}/{L(extra[1])}{r}"
    ws[f"{L(extra[3])}{r}"] = f"=IF(ISNUMBER({L(extra[2])}{r}),RANK({L(extra[2])}{r},${L(extra[2])}$2:${L(extra[2])}${n},0),\"\")"
    for x in ("เฉลี่ยต่อวัน 2566", "เฉลี่ยต่อวัน 2567", "เฉลี่ยต่อวัน 2568", "V = เฉลี่ย 3 ปี", extra[0], extra[1]): ws[f"{L(x)}{r}"].number_format = "#,##0"
    ws[f"{L(extra[2])}{r}"].number_format = "0.0000"
ws.column_dimensions[L("ถนน")].width = 26; ws.column_dimensions[L("สายทาง (highway_name)")].width = 36
ws = wb["รายด่าน (ข้อมูลดิบจาก API)"]; ws.column_dimensions["B"].width = 36; ws.column_dimensions["C"].width = 34
for r in range(2, ws.max_row + 1):
    ws.cell(r, 4).number_format = "#,##0"
    if ws.cell(r, 5).value == "ซ้ำ":
        for j in range(1, 6): ws.cell(r, j).fill = PatternFill("solid", fgColor="FFF2CC")
ws = wb["แหล่งข้อมูลและวิธีตรวจ"]; ws.column_dimensions["A"].width = 18; ws.column_dimensions["B"].width = 150
wb.save(out); print("saved", out)
C["V"] = C[[f"เฉลี่ยต่อวัน {y}" for y in Y]].mean(axis=1); C["R"] = C.A * 1e6 / (365 * 3 * C.V)
print(R[["สายทาง (highway_name)"] + [f"เฉลี่ยต่อวัน {y}" for y in Y] + ["V = เฉลี่ย 3 ปี (คัน/วัน)"]].to_string())
print(C.sort_values("R", ascending=False)[["id", "ถนน", "สายทาง (highway_name)", "A", "V", "R"]].head(5).round(4).to_string())
