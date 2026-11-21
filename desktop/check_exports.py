"""Offline delivery regression checks using the two samples and a 589-row batch."""
from pathlib import Path
from tempfile import TemporaryDirectory
import json
from delivery import export
from engine import HERE,create,read,write
from intake import bib_rows
from openpyxl import load_workbook

def lines(path):
    return [json.loads(s) for s in path.read_text(encoding="utf-8").splitlines()]

with TemporaryDirectory(dir=HERE/"local-run") as temp:
    root=Path(temp)
    (root/"batches").mkdir()
    batch=read(HERE.parent/"intake/local-run/samples.json")
    files=[Path(s["path"]) for s in batch["sources"]]
    options={str(p):dict(group=p.stem,sheet="纳入记录",mapping={}) for p in files}
    job=create(root,files,"原始样例",[],options)
    dest=export(job,root)
    rows=lines(dest/"逐条结果.jsonl")
    assert len(rows)==616 and all(r["status"]=="pending" for r in rows)
    miss=dest/"未下载题录"
    bib=next(miss.glob("*.bib"))
    assert [r[1] for r in bib_rows(bib.read_bytes())]==[r[1] for r in bib_rows(files[0].read_bytes())]
    wb=load_workbook(next(miss.glob("*.xlsx")),read_only=True)
    orig=load_workbook(files[1],read_only=True)
    assert list(wb["纳入记录"].values)==list(orig["纳入记录"].values)
    wb.close();orig.close()
    pair=read(HERE.parent/"intake/local-run/pair.json")
    raw=pair["records"][0]["raw_bib"]
    source=root/"add_1-589.bib"
    source.write_text("\n".join(raw.replace("{one,",f"{{key{i},",1) for i in range(588))+
                      "\n@article{missing,title={Unobtained test article}}\n",encoding="utf-8")
    job=create(root,[source],"命名验收",[],{str(source):dict(group="add_1",sheet=None)})
    w=read(job/"batch.json")["works"][0]
    write(job/"results"/(w["work_id"]+".json"),dict(item="test",pdf=pair["works"][0]["local_pdf"],
          method="local",reason=None,at="2026-11-20T00:00:00Z"))
    dest=export(job,root)
    miss=dest/"未下载题录/add_1-588-1.bib"
    assert [row[0]["cite_key"] for row in bib_rows(miss.read_bytes())]==["missing"]
    assert len(list((dest/"正文PDF").iterdir()))==1
    assert sum(r["status"]=="obtained" for r in lines(dest/"逐条结果.jsonl"))==588
    print("PASS: 616 source records and all nine Excel columns round-trip; 588 obtained rows share one PDF, one missing record named correctly.")
