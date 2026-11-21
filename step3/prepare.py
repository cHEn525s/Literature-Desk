"""Create the third-stage isolated profile and two independent queue journals."""
from pathlib import Path
import json
import os
import shutil
import zipfile

here = Path(__file__).resolve().parent
root = here / "local-run"
root.mkdir(exist_ok=False)
profile = root / "profile"
extensions = profile / "extensions"
extensions.mkdir(parents=True)
for name in ("data", "real/results", "controlled/results"):
    (root / name).mkdir(parents=True)
plugin, = (Path(os.environ["APPDATA"]) / "Zotero/Zotero/Profiles").glob(
    "*/extensions/scihub@example.com.xpi")
shutil.copyfile(plugin, extensions / plugin.name)
manifest = json.loads((here.parent / "step1/manifest.json").read_text(encoding="utf-8"))
manifest["name"] = "Step 3 queue probe"
manifest["applications"]["zotero"]["id"] = "step3@local.invalid"
with zipfile.ZipFile(extensions / "step3@local.invalid.xpi", "x") as archive:
    archive.writestr("manifest.json", json.dumps(manifest))
    archive.writestr("bootstrap.js", "\n".join((here / name).read_text(encoding="utf-8")
                     for name in ("queue.js", "bootstrap.js")))
prefs = {"extensions.zotero.dataDir": str(root / "data"),
         "extensions.zotero.useDataDir": True,
         "extensions.zotero.zoteroscihub.automatic_pdf_download": False,
         "extensions.zotero.httpServer.enabled": False,
         "extensions.zotero.firstRun2": False, "extensions.update.enabled": False,
         "extensions.autoDisableScopes": 0, "extensions.enabledScopes": 15}
(profile / "user.js").write_text("".join(
    f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k,v in prefs.items()
), encoding="utf-8")
papers = [
    ("10.1371/journal.pmed.0020124", "Why Most Published Research Findings Are False"),
    ("10.1371/journal.pmed.1000097", "Preferred Reporting Items for Systematic Reviews and Meta-Analyses: The PRISMA Statement"),
    ("10.1371/journal.pmed.0040296", "The Strengthening the Reporting of Observational Studies in Epidemiology (STROBE) Statement: Guidelines for Reporting Observational Studies"),
    ("10.1371/journal.pbio.1000412", "Improving Bioscience Research Reporting: The ARRIVE Guidelines for Reporting Animal Research"),
    ("10.1371/journal.pbio.3000410", "The ARRIVE guidelines 2.0: Updated guidelines for reporting animal research"),
]
(profile / "step3.json").write_text(json.dumps({"root":str(root), "papers":[
    {"doi":doi, "title":title, "offset":i*6*3600*1000}
    for i,(doi,title) in enumerate(papers)]}), encoding="utf-8")
