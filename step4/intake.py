"""Prepare a traceable, offline BibTeX/XLSX batch for the Zotero bridge."""
import argparse
from collections import defaultdict
from datetime import date, time
from difflib import SequenceMatcher
import hashlib
import io
import json
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unicodedata
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent / ".deps"))
sys.path.insert(0, str(Path(__file__).resolve().parent / ".deps/bib-libraries.zip"))
import bibtexparser
from bibtexparser.bparser import BibTexParser
from openpyxl import load_workbook


def digest(data):
    return hashlib.sha256(data).hexdigest()


def compact(value):
    return "".join(c for c in unicodedata.normalize("NFKD",value.casefold()) if c.isalnum())


def doi(value):
    value = re.sub(r"^(?:https?://(?:dx\.)?doi\.org/|doi:\s*)","",value.strip(),flags=re.I).lower()
    return value if re.fullmatch(r"10\.\d{4,9}/[^\s{}]+",value) and len(re.findall(r"10\.\d{4,9}/",value))==1 else ""


def pmid(value, url):
    if re.fullmatch(r"[1-9]\d{0,8}",value.strip()):
        return value.strip()
    parsed = urlsplit(url.strip())
    if parsed.hostname == "pubmed.ncbi.nlm.nih.gov":
        match = re.fullmatch(r"/([1-9]\d{0,8})/?",parsed.path)
        return match[1] if match else ""
    return ""


def bib_rows(raw):
    text = raw.decode("utf-8-sig")
    starts = list(re.finditer(r"(?im)^[ \t]*@(\w+)\s*[({]",text))
    parser = BibTexParser(common_strings=True)
    parser.ignore_nonstandard_types = False
    entries = bibtexparser.loads(text,parser=parser).entries
    blocks = []
    for i,m in enumerate(starts):
        if m[1].lower() not in {"string","preamble","comment"}:
            blocks.append(text[m.start():starts[i+1].start() if i+1<len(starts) else len(text)])
    if len(entries)!=len(blocks) or not entries:
        raise ValueError("BibTeX 原文与解析条数不一致，请核查条目边界")
    for i,(entry,block) in enumerate(zip(entries,blocks),1):
        key = re.match(r"\s*@\w+\s*[({]\s*([^,]+),",block)[1].strip()
        if key != entry["ID"]:
            raise ValueError(f"BibTeX 原引用键未能对齐：{key}")
        yield {"cite_key":key,"ordinal":i},entry,block,entry


COLUMNS = {"title":"标题","pmid":"PMID","doi":"DOI","year":"年份","author":"作者",
           "journal":"期刊","url":"URL","source_no":"来源记录号"}


def excel_rows(raw,sheet,mapping):
    book = load_workbook(io.BytesIO(raw),read_only=True,data_only=False)
    try:
        ws = book[sheet] if sheet else book.active
        rows = iter(ws.values)
        header = next(rows)
        names = [str(name) if name is not None else "" for name in header]
        if "" in names or len(set(names))!=len(names) or mapping["title"] not in names:
            raise ValueError(f"{ws.title} 表头缺失、重名或缺少题名映射")
        for n,row in enumerate(rows,2):
            if all(value is None for value in row):
                continue
            fields = dict(zip(names,row))
            values = {k:str(fields.get(col) if fields.get(col) is not None else "") for k,col in mapping.items()}
            for k in ("title","doi","pmid"):
                if values[k].startswith("="):
                    raise ValueError(f"{ws.title} 第 {n} 行的 {mapping[k]} 为公式，需核对其值")
            yield {"sheet":ws.title,"row":n,"source_record_no":values["source_no"]},fields,None,values
    finally:
        book.close()


def identify(records):
    parent = list(range(len(records)))
    def root(i):
        while parent[i]!=i:
            parent[i]=parent[parent[i]]
            i=parent[i]
        return i
    owners = {}
    for i,r in enumerate(records):
        for field in ("doi","pmid"):
            if r[field]:
                key=(field,r[field])
                parent[root(i)] = root(owners.setdefault(key,i))
    components=defaultdict(list)
    for i,r in enumerate(records):
        components[root(i)].append(r)
    works=[]
    for members in components.values():
        conflict=any(len({r[k] for r in members if r[k]})>1 for k in ("doi","pmid"))
        titles=[compact(r["title"]) for r in members if r["title"]]
        conflict |= any(SequenceMatcher(None,titles[0],t).ratio()<0.85 for t in titles[1:])
        for subset in ([[r] for r in members] if conflict else [members]):
            seed=subset[0]["record_id"]
            wid="W-"+digest(seed.encode())[:20]
            for r in subset:
                r["work_id"]=wid
            work={k:next((r[k] for r in subset if r[k]),"") for k in
                  ("doi","pmid","title","author","year","journal","url")}
            works.append(dict(work,work_id=wid,groups=sorted({r["group"] for r in subset}),
                              review="identity_conflict" if conflict else None,local_pdf=None))
    by_title=defaultdict(list)
    for w in works:
        if w["title"]:
            by_title[compact(w["title"])].append(w)
    for matches in by_title.values():
        if len(matches)>1:
            for w in matches:
                w["review"]="identity_conflict"
    return works


def match_files(works,candidates):
    for path in candidates:
        try:
            if getattr(sys,"frozen",False):
                with tempfile.TemporaryDirectory() as temp:
                    output=Path(temp)/"pages.txt"
                    run=subprocess.run([sys.executable,"--extract-pdf",str(path),str(output)],timeout=45)
                    if run.returncode: continue
                    text=output.read_text(encoding="utf-8")
            else:
                run=subprocess.run(["pdftotext","-enc","UTF-8",str(path),"-"],capture_output=True,timeout=45)
                if run.returncode: continue
                text=run.stdout.decode("utf-8")
        except (OSError,UnicodeError,subprocess.TimeoutExpired):
            continue
        pages=[p for p in text.split("\f") if p.strip()]
        if len(pages)<2 or len(text.split())<400 or not re.search(r"(?i)\b(references|bibliography)\b",text):
            continue
        front=compact(pages[0])
        if re.search(r"(?im)^\s*(supplementary (material|appendix)|supporting information)\s*$",pages[0][:500]):
            continue
        for w in works:
            if w["review"] or w["local_pdf"] or not w["title"]: continue
            doi_match = w["doi"] and w["doi"] in re.sub(r"\s+","",pages[0].lower())
            pmid_match = w["pmid"] and re.search(r"\bPMID\s*:?\s*"+re.escape(w["pmid"])+r"\b",pages[0],re.I)
            if compact(w["title"]) in front and (doi_match or pmid_match):
                w["local_pdf"]={"path":str(path),"sha256":digest(path.read_bytes())}
    return len(candidates)


def prepare(paths,sheet,mapping,folders,parent_name,group_names,options_by_path=None):
    records,sources=[],[]
    group_ids=set()
    for ordinal,path in enumerate(paths,1):
        raw=path.read_bytes()
        source_id=f"S{ordinal}-{digest(raw)[:12]}"
        options=(options_by_path or {}).get(str(path),{})
        group=options.get("group") or group_names.get(path.name,path.stem)
        if group in group_ids and path.name not in group_names and not options.get("group"):
            group=f"{group} ({ordinal})"
        group_ids.add(group)
        if path.suffix.lower()==".bib": rows=bib_rows(raw)
        elif path.suffix.lower()==".xlsx": rows=excel_rows(raw,options.get("sheet",sheet),{**mapping,**options.get("mapping",{})})
        else: raise ValueError(f"不支持的输入：{path}")
        count=0
        for count,(locator,fields,block,v) in enumerate(rows,1):
            r={k:str(v.get(k,"") or "") for k in ("title","year","author","url","journal")}
            r.update(record_id=f"{source_id}:{count}",source_id=source_id,group=group,
                     locator=locator,fields=fields,raw_bib=block,doi=doi(str(v.get("doi",""))),
                     pmid=pmid(str(v.get("pmid","")),r["url"]))
            records.append(r)
        sources.append(dict(source_id=source_id,file=path.name,path=str(path.resolve()),
                            sha256=digest(raw),group=group,count=count))
    works=identify(records)
    candidates=match_files(works,sorted({p.resolve() for f in folders for p in f.rglob("*.pdf")}))
    return dict(schema=1,parent=parent_name,sources=sources,records=records,works=works,
                scanned_candidates=candidates)


if __name__=="__main__":
    p=argparse.ArgumentParser()
    p.add_argument("inputs",nargs="+",type=Path)
    p.add_argument("--sheet")
    p.add_argument("--mapping",type=json.loads,default={})
    p.add_argument("--groups",type=json.loads,default={})
    p.add_argument("--parent",required=True)
    p.add_argument("--pdf-dir",action="append",type=Path,default=[])
    p.add_argument("--out",required=True,type=Path)
    args=p.parse_args()
    batch=prepare(args.inputs,args.sheet,{**COLUMNS,**args.mapping},args.pdf_dir,args.parent,args.groups)
    args.out.parent.mkdir(parents=True,exist_ok=True)
    tmp=args.out.with_suffix(".tmp")
    tmp.write_text(json.dumps(batch,ensure_ascii=False,default=lambda v:v.isoformat()
                              if isinstance(v,(date,time)) else str(v)),encoding="utf-8")
    tmp.replace(args.out)
    print(f"{len(batch['records'])} records, {len(batch['works'])} works")
