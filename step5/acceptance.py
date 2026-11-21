"""Exercise the actual Tk actions with file dialogs supplied by the test."""
import csv
import json
import time
import tkinter as tk
from pathlib import Path
from unittest.mock import patch
from desktop import App
from engine import HERE, connected, read
from openpyxl import Workbook, load_workbook

from uuid import uuid4
root=HERE/"local-run"/("acceptance-"+uuid4().hex[:8])
root.mkdir(parents=True,exist_ok=False)
inputs=root/"test-inputs"
inputs.mkdir()
out=root/"exports"
out.mkdir()
pair=read(HERE.parent/"step4/local-run/pair.json")
w=pair["works"][0]
bib=inputs/"add_1-2.bib"
bib.write_text("@string{jour = {Test Journal}}\n"+pair["records"][0]["raw_bib"]+
    "\n@article{unavailable, title={Missing local fixture},journal=jour,note={保留{嵌套}字段}}\n",encoding="utf-8")
sheet=inputs/"跨组.xlsx"
wb=Workbook();ws=wb.active;ws.title="纳入记录"
ws.append(["标题","PMID","来源记录号","分工","是否纳入"])
ws.append([w["title"],w["pmid"],"001","甲","是"])
wb.save(sheet)
other=inputs/"缺件.xlsx"
wb=Workbook();ws=wb.active;ws.title="清单"
ws.append(["标题","来源记录号","自定义列"]);ws.append(["另一篇缺件","0002","保留"]);wb.save(other)
live=inputs/"真实下载.bib"
live.write_text("@article{prisma, title={Preferred Reporting Items for Systematic Reviews and Meta-Analyses: The PRISMA Statement},doi={10.1371/journal.pmed.1000097}}",encoding="utf-8")
window=tk.Tk();window.withdraw()
app=App(window,root)
def until(test,timeout=180):
    end=time.monotonic()+timeout
    while not test():
        if time.monotonic()>end:raise RuntimeError(app.status.get())
        window.update();time.sleep(.035)
    window.update()
def click(name):
    window.update()
    until(lambda:str(app.buttons[name]["state"])=="normal",5)
    app.buttons[name].invoke()
def finish():
    until(lambda:not app.busy)
with patch("desktop.filedialog.askopenfilenames",return_value=list(map(str,[bib,sheet,other,live]))):
    click("选择文件")
with patch("desktop.filedialog.askdirectory",return_value=str(Path(w["local_pdf"]["path"]).parent)):
    click("本地 PDF 目录")
click("导入预览");finish()
assert app.job,app.status.get()
click("连接专用 Zotero");until(lambda:connected(root),60)
click("开始")
until(lambda:(app.job/"pending.json").exists())
click("暂停");finish()
assert app.status.get()=="已暂停",app.status.get()
job=app.job
first=list((job/"results").glob("*.json"))
assert 0<len(first)<4
before={f:f.stat().st_mtime_ns for f in first}
app.close()
window=tk.Tk();window.withdraw()
app=App(window,root)
assert app.job==job
click("继续");finish()
assert app.status.get()=="已完成",app.status.get()
assert all(f.stat().st_mtime_ns==stamp for f,stamp in before.items())
with patch("desktop.filedialog.askdirectory",return_value=str(out)):
    click("导出交付");finish()
destination=app.last_export
assert destination,app.status.get()
rows=[json.loads(line) for line in (destination/"逐条结果.jsonl").read_text(encoding="utf-8").splitlines()]
assert len(rows)==5 and rows[0]["pdf_path"]==rows[2]["pdf_path"] and rows[0]["method"]=="local"
assert rows[1]["reason_code"]==rows[3]["reason_code"]=="no_doi"
miss=destination/"未下载题录"
assert "@string" in (miss/"add_1-1-1.bib").read_text(encoding="utf-8")
from intake import bib_rows
assert [r[0]["cite_key"] for r in bib_rows((miss/"add_1-1-1.bib").read_bytes())]==["unavailable"]
wb=load_workbook(miss/"缺件-0-1.xlsx")
assert list(wb.active.values)==[("标题","来源记录号","自定义列"),("另一篇缺件","0002","保留")]
wb.close()
with (destination/"分组汇总.csv").open(encoding="utf-8-sig") as f:
    summary=list(csv.DictReader(f))
assert summary[1]["未取得"]=="0" and not summary[1]["缺件文件"]
assert len(list((destination/"正文PDF").glob("*.pdf")))==len({r["pdf_path"] for r in rows if r["pdf_path"]})
print(json.dumps({"snapshot":str(destination),"rows":len(rows),"live":rows[-1]["status"],
      "live_reason":rows[-1]["reason_code"],"pdfs":summary[-1]["已取得"],"summary":summary},ensure_ascii=False))
app.close()
