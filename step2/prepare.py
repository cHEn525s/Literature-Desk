"""Prepare one isolated integration run. Launch Zotero separately with -profile."""
import json
import os
from pathlib import Path
import shutil
import zipfile

here = Path(__file__).resolve().parent
root = here / "local-run"
root.mkdir(exist_ok=False)
profile = root / "profile"
extensions = profile / "extensions"
extensions.mkdir(parents=True)
(root / "data").mkdir()
source, = (Path(os.environ["APPDATA"]) / "Zotero/Zotero/Profiles").glob(
    "*/extensions/scihub@example.com.xpi")
shutil.copyfile(source, extensions / source.name)
manifest = json.loads((here.parent / "step1/manifest.json").read_text(encoding="utf-8"))
manifest["name"] = "Step 2 single paper probe"
manifest["applications"]["zotero"]["id"] = "step2@local.invalid"
with zipfile.ZipFile(extensions / "step2@local.invalid.xpi", "x") as archive:
    archive.writestr("manifest.json", json.dumps(manifest))
    archive.write(here / "bootstrap.js", "bootstrap.js")
prefs = {"extensions.zotero.dataDir": str(root / "data"),
         "extensions.zotero.useDataDir": True,
         "extensions.zotero.zoteroscihub.automatic_pdf_download": False,
         "extensions.zotero.httpServer.enabled": False,
         "extensions.zotero.firstRun2": False, "extensions.update.enabled": False,
         "extensions.autoDisableScopes": 0, "extensions.enabledScopes": 15}
(profile / "user.js").write_text("".join(
    f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k,v in prefs.items()
), encoding="utf-8")
(profile / "step2.json").write_text(json.dumps({
    "root": str(root), "doi":"10.1371/journal.pmed.0020124",
    "title":"Why Most Published Research Findings Are False"
}), encoding="utf-8")
