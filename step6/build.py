"""Build from the source modules and an explicit bridge allowlist."""
import json
from importlib.metadata import distribution
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

here=Path(__file__).resolve().parent
project=here.parent
build=here/"build"
import tkinter
tkinter.Tcl().eval("info library")
subprocess.run([sys.executable,"-m","PyInstaller","--clean","--noconfirm","--windowed",
    "--onedir","--noupx","--name","LiteratureDesk","--icon",str(here/"LiteratureDesk.ico"),
    "--specpath",str(build),
    "--add-data",str(here/"titlebar.png")+";.",
    "--distpath",str(build/"dist"),"--workpath",str(build/"analysis"),
    "--paths",str(project/"step4"),"--paths",str(project/"step5"),
    str(here/"main.py")],check=True)
app=build/"dist/LiteratureDesk"
for resource in ["_tkinter.pyd","_tcl_data/init.tcl","_tk_data/tk.tcl"]:
    if not (app/"_internal"/resource).is_file():
        raise RuntimeError(f"桌面界面组件未打包：{resource}")
bridge=app/"bridge"
bridge.mkdir(exist_ok=True)
manifest=json.loads((project/"step1/manifest.json").read_text(encoding="utf-8"))
manifest.update(name="文献正文获取工具桥接",version="1.1.1",description="连接本机桌面程序和专用 Zotero 文库")
manifest["applications"]["zotero"].update(id="desktop@local.invalid",update_url="https://example.invalid/zotero-fulltext/updates.json")
with zipfile.ZipFile(bridge/"desktop@local.invalid.xpi","w",zipfile.ZIP_DEFLATED) as archive:
    archive.writestr("manifest.json",json.dumps(manifest,ensure_ascii=False))
    archive.writestr("bootstrap.js",(project/"step4/bind.js").read_text(encoding="utf-8")+
                     (project/"step5/bridge.js").read_text(encoding="utf-8"))
notices=app/"licenses"
notices.mkdir(exist_ok=True)
for name in ["pypdf","openpyxl","et_xmlfile","bibtexparser","pyparsing","PyInstaller"]:
    dist=distribution(name)
    for f in dist.files or []:
        if f.name.lower().startswith(("license","licence","copying")):
            shutil.copyfile(dist.locate_file(f),notices/(name+"-"+f.name))
base=Path(sys.base_prefix)
for f in [base/"LICENSE.txt",*base.glob("tcl/*/license.terms")]:
    if f.is_file():shutil.copyfile(f,notices/(f.parent.name+"-"+f.name))
subprocess.run([str(build/"inno/ISCC.exe"),"/Qp",str(here/"installer.iss")],check=True)
