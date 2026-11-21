"""Exercise terminal cancellation and relocation against disposable copies."""
import json
from contextlib import closing
from pathlib import Path
import shutil
import sqlite3
import sys
import time
import tkinter as tk
import uuid
from unittest.mock import patch

here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/"step5"))
from desktop import App
from engine import read,write
from library_location import closed_profile,relocate
from delivery import export

qa=here/"build"/("qa110-"+uuid.uuid4().hex[:8])
root=qa/"workspace"
root.mkdir(parents=True)
prior=here.parent/"step4/local-run/data"
source=root/"data"
source.mkdir()
shutil.copyfile(prior/"zotero.sqlite",source/"zotero.sqlite")
pdf=next((prior/"storage").rglob("*.pdf"))
local=source/pdf.relative_to(prior)
local.parent.mkdir(parents=True)
shutil.copyfile(pdf,local)
def counts():
    with closing(sqlite3.connect((source/"zotero.sqlite").as_uri()+"?mode=ro",uri=True)) as db:
        return db.execute("select count(*) from items").fetchone()
before=counts()
with closed_profile(root):
    try:relocate(root,qa/"blocked")
    except RuntimeError:pass
    else:raise AssertionError("live profile accepted")
(qa/"library").mkdir()
relocate(root,qa/"library")
assert source.resolve()==(qa/"library/ZoteroFullText-Data").resolve()
assert counts()==before and local.read_bytes()==pdf.read_bytes()
(source/"write-check").write_text("ok")
assert (source.resolve()/"write-check").exists()
win=tk.Tk();win.withdraw()
app=App(win,root)
def wait(pred,seconds=10):
    until=time.monotonic()+seconds
    while not pred():
        if time.monotonic()>until:raise AssertionError(app.status.get())
        win.update();time.sleep(.025)
def choose(path):
    with patch("desktop.filedialog.askopenfilenames",return_value=[str(path)]):
        app.select()
    app.prepare();wait(lambda:not app.busy)
    assert app.job
fixture=here.parent/"step4/local-run/fixture/group-A.bib"
choose(fixture)
job=app.job
(root/"profile").mkdir(exist_ok=True)
write(root/"profile/desktop.json",{"token":"test"})
write(root/"hello.json",{"token":"test","at":int(time.time()*1000)})
app.start();wait(lambda:(job/"pending.json").exists())
with patch("desktop.messagebox.askyesno",return_value=True):app.abort()
wait(lambda:not app.busy)
assert read(job/"phase.json")=="aborted"
snap=export(job,qa)
assert json.loads((snap/"逐条结果.jsonl").read_text(encoding="utf8"))["reason_code"]=="batch_aborted"
app.close()
win=tk.Tk();win.withdraw()
app=App(win,root)
assert app.phase=="aborted"
choose(fixture)
assert app.job!=job and app.phase=="ready"
app.close()
print("PASS: cancel pending, export, reopen, switch batch; locked profile refused; database and stored PDF migrated with stable paths.")
