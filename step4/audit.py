"""Reconcile input rows, collection memberships and readable Zotero attachments."""
from pathlib import Path
from collections import Counter
import json
from intake import digest, match_files
from openpyxl import load_workbook

root=Path(__file__).resolve().parent/"local-run"
def read(name):
    return json.loads((root/(name+".json")).read_text(encoding="utf-8"))

report={}
for name in ("samples","pair","repeat"):
    batch=read(name)
    receipt=read(name+"-receipt")
    bound={r["work_id"]:r for r in receipt["rows"]}
    assert len(bound)==len(receipt["rows"])==len(batch["works"])
    verified={}
    for w in batch["works"]:
        row=bound[w["work_id"]]
        if "item" not in row:
            assert row["review"]
            continue
        assert {receipt["groupKeys"][g] for g in w["groups"]} <= set(row["groups"])
        paths=[Path(c["path"]) for c in row["candidates"] if c["path"]]
        check=dict(w,local_pdf=None)
        match_files([check],paths)
        if check["local_pdf"]:
            verified[w["work_id"]]=check["local_pdf"]
    for source in batch["sources"]:
        file=Path(source["path"])
        assert digest(file.read_bytes())==source["sha256"]
        subset=[r for r in batch["records"] if r["source_id"]==source["source_id"]]
        assert len(subset)==source["count"]
        if file.suffix.lower()==".xlsx":
            book=load_workbook(file,read_only=True,data_only=False)
            sheet=book[subset[0]["locator"]["sheet"]]
            cells=iter(sheet.values)
            header=next(cells)
            byrow={r["locator"]["row"]:r["fields"] for r in subset}
            for n,row in enumerate(cells,2):
                if n in byrow: assert byrow[n]==dict(zip(header,row))
            book.close()
        else:
            original=file.read_bytes().decode("utf-8-sig")
            assert all(r["raw_bib"] in original for r in subset)
    if name=="repeat": assert receipt==read("pair-receipt")
    results=[dict(record_id=r["record_id"],source_id=r["source_id"],group=r["group"],
                  locator=r["locator"],work_id=r["work_id"],item=bound[r["work_id"]].get("item"),
                  review=bound[r["work_id"]]["review"],local_pdf=verified.get(r["work_id"]))
             for r in batch["records"]]
    (root/(name+"-records.jsonl")).write_text("".join(json.dumps(r,ensure_ascii=False)+"\n"
                                              for r in results),encoding="utf-8")
    if name in {"pair","repeat"}:
        assert len(results)==2 and len(verified)==1 and all(r["local_pdf"] for r in results)
        assert len({r["item"] for r in results})==1 and len(receipt["rows"][0]["candidates"])==1
    report[name]=dict(records=len(results),works=len(bound),items=len({r["item"] for r in results if r["item"]}),
                      groups=dict(Counter(r["group"] for r in results)),review=sum(bool(r["review"]) for r in results),
                      local_works=len(verified),local_records=sum(bool(r["local_pdf"]) for r in results))
print(json.dumps(report,ensure_ascii=False,indent=2))
(root/"audit.json").write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding="utf-8")
