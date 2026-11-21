import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import uuid
import zipfile
from datetime import datetime, timezone

HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE.parent/"step4"))
from intake import COLUMNS, digest, match_files, prepare
from openpyxl import load_workbook

def read(path):
    return json.loads(path.read_text(encoding="utf-8"))

def write(path,value):
    temp=path.with_name(path.name+"."+uuid.uuid4().hex+".tmp")
    temp.write_text(json.dumps(value,ensure_ascii=False,default=str),encoding="utf-8")
    os.replace(temp,path)

def setup(root):
    root.mkdir(parents=True,exist_ok=True)
    profile=root/"profile"
    extensions=profile/"extensions"
    for folder in (extensions,root/"data",root/"replies",root/"batches"):
        folder.mkdir(parents=True,exist_ok=True)
    config=profile/"desktop.json"
    bundled=Path(sys.executable).parent/"bridge"/"desktop@local.invalid.xpi"
    installed=extensions/"desktop@local.invalid.xpi"
    if config.exists():
        if getattr(sys,"frozen",False) and (not installed.exists() or bundled.read_bytes()!=installed.read_bytes()):
            if connected(root): raise RuntimeError("请关闭专用 Zotero，再重新连接以更新桥接插件")
            shutil.copyfile(bundled,installed)
        return
    plugins=list((Path(os.environ["APPDATA"])/"Zotero/Zotero/Profiles").glob("*/extensions/scihub@example.com.xpi"))
    if not plugins: raise ValueError("请先在 Zotero 中安装 Sci-Hub 插件")
    shutil.copyfile(plugins[0],extensions/plugins[0].name)
    if getattr(sys,"frozen",False): shutil.copyfile(bundled,installed)
    else:
        manifest=read(HERE.parent/"step1/manifest.json")
        manifest["name"]="文献正文获取桌面桥接"
        manifest["applications"]["zotero"]["id"]="desktop@local.invalid"
        with zipfile.ZipFile(installed,"w") as z:
            z.writestr("manifest.json",json.dumps(manifest))
            z.writestr("bootstrap.js",(HERE.parent/"step4/bind.js").read_text(encoding="utf-8")+
                       (HERE/"bridge.js").read_text(encoding="utf-8"))
    prefs={"extensions.zotero.useDataDir":True,"extensions.zotero.dataDir":str(root/"data"),
           "extensions.zotero.zoteroscihub.automatic_pdf_download":False,
           "extensions.zotero.httpServer.enabled":False,"extensions.zotero.firstRun2":False,
           "extensions.update.enabled":False,"extensions.autoDisableScopes":0,"extensions.enabledScopes":15}
    (profile/"user.js").write_text("".join(f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k,v in prefs.items()),encoding="utf-8")
    write(config,{"root":str(root),"token":uuid.uuid4().hex})

def connected(root):
    try:
        hello=read(root/"hello.json")
        return hello["token"]==read(root/"profile/desktop.json")["token"] and time.time()-hello["at"]/1000<10
    except (OSError,ValueError,KeyError): return False

def launch(root,exe=None):
    if connected(root):
        write(root/"focus.json",{"token":read(root/"profile/desktop.json")["token"],"id":uuid.uuid4().hex})
        return
    setup(root)
    if not connected(root):
        location=root/"zotero-path.json"
        if exe:
            if Path(exe).name.lower()!="zotero.exe": raise ValueError("请选择 zotero.exe")
            write(location,str(exe))
        exe=Path(read(location)) if location.exists() else Path(os.environ["ProgramFiles"])/"Zotero/zotero.exe"
        if not exe.is_file(): raise FileNotFoundError("找不到 Zotero 程序",str(exe))
        subprocess.Popen([str(exe),"-no-remote","-profile",str(root/"profile")])

def copy_batch(root,old,missing_only=False):
    batch=read(old/"batch.json")
    retained={}
    if missing_only:
        for work in batch["works"]:
            wid=work["work_id"]
            result_file=old/"results"/(wid+".json")
            result=read(result_file) if result_file.is_file() else {}
            pdf=result.get("pdf")
            if pdf:
                path=Path(pdf["path"])
                if path.is_file() and digest(path.read_bytes())==pdf["sha256"]:
                    retained[wid]=result
        if len(retained)==len(batch["works"]):
            return None
    new_id=uuid.uuid4().hex
    job=root/"batches"/new_id
    job.mkdir()
    for i,s in enumerate(batch["sources"]):
        src=Path(s["path"])
        dest=job/"inputs"/str(i)/s["file"]
        dest.parent.mkdir(parents=True)
        shutil.copyfile(src,dest)
        if digest(dest.read_bytes())!=s["sha256"]: raise ValueError("输入快照校验失败："+s["file"])
        s["path"]=str(dest)
    for w in batch["works"]:
        pdf=w.get("local_pdf")
        if pdf and not Path(pdf["path"]).is_file():w["local_pdf"]=None
    batch["batch_id"]=new_id
    (job/"results").mkdir()
    if missing_only:
        batch["retry_from"]=old.name
        for wid,result in retained.items():
            write(job/"results"/(wid+".json"),result)
    else:
        batch.pop("retry_from",None)
    write(job/"batch.json",batch)
    write(root/"current.json",new_id)
    return job

def create(root,files,parent,folders,options):
    if not files or not parent.strip(): raise ValueError("请选择输入文件并填写父分类")
    if not getattr(sys,"frozen",False) and not shutil.which("pdftotext"): raise ValueError("找不到 pdftotext，无法核验正文")
    batch_id=uuid.uuid4().hex
    job=root/"batches"/batch_id
    job.mkdir(parents=True)
    sources=[]
    for index,path in enumerate(files):
        folder=job/"inputs"/str(index)
        folder.mkdir(parents=True)
        snapshot=folder/path.name
        shutil.copyfile(path,snapshot)
        if path.suffix.lower()==".xlsx":
            book=load_workbook(snapshot,read_only=True,data_only=False)
            try:
                sheet=book[options[str(path)]["sheet"]]
                if any(c.data_type=="f" for row in sheet for c in row):
                    raise ValueError(f"{path.name} 含公式，请先提供保留原字段的值副本以便导出缺件")
            finally: book.close()
        sources.append(snapshot)
    batch=prepare(sources,None,COLUMNS,folders,parent,{},options_by_path={
        str(src):options[str(orig)] for src,orig in zip(sources,files)})
    if not batch["records"]: raise ValueError("没有可处理的题录")
    batch["batch_id"]=batch_id
    (job/"results").mkdir()
    write(job/"batch.json",batch)
    write(root/"current.json",batch_id)
    return job

def check_abort(job):
    if (job/"aborted").exists(): raise RuntimeError("批次已中止")

def rpc(root,job,op,payload,progress=None):
    check_abort(job)
    pending=job/"pending.json"
    if not pending.exists():
        if not connected(root): raise RuntimeError("桥接未连接，请打开专用 Zotero 后继续")
        cmd=dict(id=uuid.uuid4().hex,token=read(root/"profile/desktop.json")["token"],batch_id=job.name,op=op,**payload)
        write(pending,cmd)
    cmd=read(pending)
    write(root/"request.json",cmd)
    start=time.monotonic()
    last=-1
    reply=root/"replies"/(cmd["id"]+".json")
    while not reply.exists():
        check_abort(job)
        elapsed=int(time.monotonic()-start)
        stage="下载插件返回结果" if op=="acquire" else "Zotero 绑定条目"
        if elapsed>=120: raise RuntimeError(f"等待{stage}已达 120 秒。已保存请求；请查看专用 Zotero 的验证窗口或插件提示，处理后点“继续”核对原请求。")
        if progress and elapsed!=last:
            progress(f"等待{stage} · {elapsed} 秒")
            last=elapsed
        time.sleep(.15)
    result=read(reply)
    if "error" in result:
        pending.unlink()
        raise RuntimeError(result["error"])
    return cmd,result

def execute(root,job,stop,progress):
    batch=read(job/"batch.json")
    for i,w in enumerate(batch["works"],1):
        check_abort(job)
        target=job/"results"/(w["work_id"]+".json")
        if target.exists(): continue
        if stop.is_set(): return "已暂停"
        label=f"{i}/{len(batch['works'])}　{w['title']}"
        progress(label)
        def stage(message): progress(f"{label}　|　{message}")
        pending=job/"pending.json"
        old=read(pending) if pending.exists() else {}
        if old and old.get("wid")!=w["work_id"]:
            if (job/"results"/(old["wid"]+".json")).exists(): pending.unlink(); old={}
            else: raise RuntimeError("待处理命令与当前条目不一致")
        method="local"
        if old.get("op")=="acquire":
            item=old["item"]
            row={}
        else:
            sub={"parent":batch["parent"],"sources":[{"group":g} for g in w["groups"]],"works":[w]}
            _,row=rpc(root,job,"bind",{"wid":w["work_id"],"batch":sub},stage)
            item=row.get("item")
        check=dict(w,local_pdf=None)
        def inspect(candidates):
            paths=[Path(c["path"]) for c in candidates if c.get("path") and Path(c["path"]).is_file()]
            match_files([check],paths)
        inspect(row.get("candidates",[]))
        if not check["local_pdf"] and w["local_pdf"]:
            inspect([w["local_pdf"]])
        reason=row.get("review") or w.get("review")
        if not reason and not check["local_pdf"]:
            if row.get("candidates"): reason="wrong_attachment"
            elif not w["doi"]: reason="no_doi"
            else:
                if old.get("op")!="acquire": pending.unlink()
                _,reply=rpc(root,job,"acquire",{"wid":w["work_id"],"item":item,"doi":w["doi"]},stage)
                method="downloaded"
                inspect(reply.get("candidates",[]))
                reason=reply.get("missing") or ("unverified_pdf" if not check["local_pdf"] else None)
        pdf=check["local_pdf"]
        write(target,dict(item=item,pdf=pdf,method=method if pdf else None,reason=reason,
                          at=datetime.now(timezone.utc).isoformat() if pdf else None))
        pending.unlink(missing_ok=True)
    return "已完成"
