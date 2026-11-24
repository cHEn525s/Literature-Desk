import csv
import json
import re
import shutil
import tempfile
import uuid
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from openpyxl import Workbook, load_workbook
from engine import read, digest

def missing_file(path,source,rows,misses):
    original=Path(source["path"])
    if digest(original.read_bytes())!=source["sha256"]: raise ValueError("原始快照校验失败")
    if path.suffix.lower()==".bib":
        text=original.read_bytes().decode("utf-8-sig")
        parts=[]
        pos=0
        keep={r["record_id"] for r in misses}
        for r in rows:
            raw=r["raw_bib"]
            start=text.index(raw,pos)
            parts.append(text[pos:start])
            if r["record_id"] in keep: parts.append(raw)
            pos=start+len(raw)
        path.write_bytes(("".join(parts)+text[pos:]).encode("utf-8"))
    else:
        sheet=misses[0]["locator"]["sheet"]
        wanted={1,*[r["locator"]["row"] for r in misses]}
        book=load_workbook(original,read_only=True,data_only=False)
        output=Workbook()
        dest=output.active
        dest.title=sheet
        try:
            out_row=0
            for n,row in enumerate(book[sheet],1):
                if n not in wanted: continue
                out_row+=1
                for col,cell in enumerate(row,1):
                    if cell.value is None: continue
                    target=dest.cell(out_row,col,cell.value)
                    target.data_type=cell.data_type
                    target.number_format=cell.number_format
            output.save(path)
        finally: book.close(); output.close()

def export(job,directory):
    batch=read(job/"batch.json")
    final=directory/("交付-"+datetime.now().strftime("%Y%m%d-%H%M%S")+"-"+uuid.uuid4().hex[:6])
    with tempfile.TemporaryDirectory(dir=directory) as temp:
        out=Path(temp)/"snapshot"
        pdfs=out/"正文PDF"
        missing=out/"未下载题录"
        pdfs.mkdir(parents=True)
        missing.mkdir()
        outcomes={}
        for w in batch["works"]:
            wid=w["work_id"]
            file=job/"results"/(wid+".json")
            result=read(file) if file.exists() else {"reason":"batch_aborted" if (job/"aborted").exists() else "pending"}
            pdf=result.get("pdf")
            relative=None
            additional=[]
            if pdf:
                dest=pdfs/(wid+".pdf")
                shutil.copyfile(pdf["path"],dest)
                if digest(dest.read_bytes())!=pdf["sha256"]: raise ValueError("正文在核验后发生变化，请重新核验")
                relative=dest.relative_to(out).as_posix()
                for number,other in enumerate(result.get("additional_pdfs",[]),1):
                    extra=out/"同条目其他PDF"/f"{wid}-{number}.pdf"
                    extra.parent.mkdir(exist_ok=True)
                    shutil.copyfile(other["path"],extra)
                    if digest(extra.read_bytes())!=other["sha256"]: raise ValueError("其他 PDF 在取得后发生变化")
                    additional.append(dict(path=extra.relative_to(out).as_posix(),sha256=other["sha256"]))
            outcomes[wid]=dict(status="obtained" if pdf else ("pending" if not file.exists() else
                ("review" if result["reason"] in {"wrong_attachment","unverified_pdf","identity_conflict","library_identity_conflict"} else "missing")),
                doi=w["doi"] or None,pmid=w["pmid"] or None,method=result.get("method"),
                pdf_path=relative,pdf_sha256=pdf["sha256"] if pdf else None,
                item_key=result.get("item"),verified_at=result.get("at"),reason_code=result.get("reason"),
                acquisition_rule=result.get("acquisition_rule"),additional_pdfs=additional,pdf_errors=result.get("pdf_errors",[]))
        by_source=defaultdict(list)
        for r in batch["records"]: by_source[r["source_id"]].append(r)
        used=set()
        with (out/"逐条结果.jsonl").open("w",encoding="utf-8") as manifest, (out/"分组汇总.csv").open("w",encoding="utf-8-sig",newline="") as f:
            writer=csv.writer(f)
            writer.writerow(["组","原文件","原始条数","本地复用","新下载","已取得","未取得","缺件文件"])
            for s in batch["sources"]:
                rows=by_source[s["source_id"]]
                misses=[]
                methods=Counter()
                for r in rows:
                    outcome=outcomes[r["work_id"]]
                    if outcome["status"]=="obtained": methods[outcome["method"]]+=1
                    else: misses.append(r)
                    detail={k:r[k] for k in ("record_id","source_id","locator","work_id","title")}
                    detail.update(schema_version="1.0",batch_id=batch["batch_id"],source_name=s["file"],
                                  source_sha256=s["sha256"],group_id=s["group"],library_id=1,**outcome)
                    manifest.write(json.dumps(detail,ensure_ascii=False)+"\n")
                got=sum(methods.values())
                assert got+len(misses)==s["count"]
                name=""
                if misses:
                    stem=Path(s["file"]).stem
                    stem=re.sub("-"+str(s["count"])+"$","",stem) or stem
                    ext=Path(s["file"]).suffix
                    name=f"{stem}-{got}-{len(misses)}{ext}"
                    if name.casefold() in used: name=f"{stem}-{s['source_id']}-{got}-{len(misses)}{ext}"
                    used.add(name.casefold())
                    missing_file(missing/name,s,rows,misses)
                writer.writerow([s["group"],s["file"],len(rows),methods["local"],methods["downloaded"],got,len(misses),name])
            totals=Counter(v["method"] for v in outcomes.values() if v["status"]=="obtained")
            total=sum(totals.values())
            writer.writerow(["全批唯一论文","",len(outcomes),totals["local"],totals["downloaded"],total,len(outcomes)-total,""])
        out.rename(final)
    return final
