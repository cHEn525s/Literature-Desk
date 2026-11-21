"""Exercise the two reference inputs and a separate known cross-group pair."""
from pathlib import Path
import json
import shutil
import sys
import zipfile
from intake import COLUMNS, prepare
from openpyxl import Workbook

here=Path(__file__).resolve().parent
workspace=here.parent.parent
root=here/"local-run"
profile=root/"profile"
profile.mkdir(parents=True,exist_ok=False)
(profile/"extensions").mkdir()
(root/"data").mkdir()

def write(path,obj):
    path.write_text(json.dumps(obj,ensure_ascii=False,default=str),encoding="utf-8")

real_inputs=[workspace/"VPN needed/8-134.bib",
             workspace.parent/"肿瘤购买效益/原始表格/历史原表/C34_肺癌_Chen.xlsx"]
real=prepare(real_inputs,"纳入记录",COLUMNS,[workspace/"ScanSci_5篇测试"],"第四步 · 两个原始输入",{})
write(root/"samples.json",real)
assert [s["count"] for s in real["sources"]]==[134,482]
assert sum(bool(r["pmid"]) for r in real["records"][:134] if not r["fields"].get("doi"))==88
assert all(len(r["fields"])==9 for r in real["records"][134:])
assert len({r["record_id"] for r in real["records"]})==616

doi="10.1371/journal.pmed.0020124"
title="Why Most Published Research Findings Are False"
fixture=root/"fixture"
fixture.mkdir()
bib=fixture/"group-A.bib"
bib.write_text("@article{one, title={"+title+"},doi={"+doi+"},url={https://pubmed.ncbi.nlm.nih.gov/16060722/}}",encoding="utf-8")
xlsx=fixture/"group-B.xlsx"
wb=Workbook()
ws=wb.active
ws.title="纳入记录"
ws.append(["标题","PMID","来源记录号","分工","是否纳入"])
ws.append([title,"16060722","001","甲","是"])
wb.save(xlsx)
pair=prepare([bib,xlsx],"纳入记录",COLUMNS,[here.parent/"step2/local-run/data/storage"],
             "第四步 · 跨组复用",{})
assert len(pair["works"])==1 and pair["works"][0]["local_pdf"]
write(root/"pair.json",pair)
write(root/"repeat.json",pair)
manifest=json.loads((here.parent/"step1/manifest.json").read_text(encoding="utf-8"))
manifest["name"]="Step 4 isolated intake"
manifest["applications"]["zotero"]["id"]="step4@local.invalid"
with zipfile.ZipFile(profile/"extensions/step4@local.invalid.xpi","x") as z:
    z.writestr("manifest.json",json.dumps(manifest))
    z.writestr("bootstrap.js", (here/"bind.js").read_text(encoding="utf-8") + (here/"bridge.js").read_text(encoding="utf-8"))
prefs={"extensions.zotero.useDataDir":True,"extensions.zotero.dataDir":str(root/"data"),
       "extensions.zotero.httpServer.enabled":False,"extensions.zotero.firstRun2":False,
       "extensions.update.enabled":False,"extensions.autoDisableScopes":0,"extensions.enabledScopes":15}
(profile/"user.js").write_text("".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n"
                                        for k,v in prefs.items()),encoding="utf-8")
write(profile/"step4.json",{"root":str(root),"jobs":["samples","pair","repeat"]})
print("Prepared",len(real["works"]),"sample works and one cross-group fixture")
