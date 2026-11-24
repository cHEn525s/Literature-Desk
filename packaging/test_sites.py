"""Exercise the installed bridge in a disposable Zotero profile with local HTTP fixtures."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from io import BytesIO
from pypdf import PdfWriter
from pypdf.generic import DictionaryObject, NameObject, DecodedStreamObject
here=Path(__file__).resolve().parent
sys.path.insert(0,str(here.parent/"desktop"))
import engine
from site_manager import DEFAULTS, call
from delivery import export

def sample_pdf():
    writer=PdfWriter()
    page=writer.add_blank_page(500,700)
    font=DictionaryObject({NameObject("/Type"):NameObject("/Font"),NameObject("/Subtype"):NameObject("/Type1"),NameObject("/BaseFont"):NameObject("/Helvetica")})
    page[NameObject("/Resources")]=DictionaryObject({NameObject("/Font"):DictionaryObject({NameObject("/F1"):font})})
    stream=DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 600 Td (Why Most Published Research Findings Are False) Tj ET")
    page[NameObject("/Contents")]=stream
    out=BytesIO()
    writer.write(out)
    return out.getvalue()

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        path=self.path
        status=403 if "/denied/" in path else 200
        if path=="/sample.pdf":mime,data="application/pdf",sample_pdf()
        else:
            mime="text/html"
            data=b'<div class="question"><form class="answer"></form></div>' if "/human/" in path else b'<meta name="citation_pdf_url" content="/sample.pdf">'
        self.send_response(status)
        self.send_header("Content-Type",mime)
        self.end_headers()
        self.wfile.write(data)
    def log_message(self,*args): pass

def verify(root,live):
    assert len(set(DEFAULTS))==11
    server=ThreadingHTTPServer(("127.0.0.1",0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base="http://127.0.0.1:"+str(server.server_port)
    current=call(root,"current")["address"]
    for suffix,status in [("/ok/","可获取 PDF"),("/human/","需要人工验证")]:
        assert call(root,"probe",base+suffix)["status"]==status
    try:call(root,"probe",base+"/denied/")
    except ValueError as e:assert "403" in str(e)
    else:raise AssertionError("HTTP 403 incorrectly passed")
    assert call(root,"current")["address"]==current
    human=base+"/human/"
    assert call(root,"select",human)["address"]==human
    oldsrc=live
    old=root/"batches"/oldsrc.name
    shutil.copytree(oldsrc,old)
    batch=engine.read(old/"batch.json")
    for i,source in enumerate(batch["sources"]): source["path"]=str(old/"inputs"/str(i)/source["file"])
    engine.write(old/"batch.json",batch)
    new=engine.copy_batch(root,old,True)
    retained={p.name:p.read_bytes() for p in (new/"results").glob("*.json")}
    stop=threading.Event()
    try:engine.execute(root,new,stop,lambda s:None)
    except RuntimeError as e:assert "验证" in str(e),e
    else:raise AssertionError("expected verification pause")
    verify_record=engine.read(new/"verification.json")
    wid=verify_record["wid"]
    assert verify_record["address"].startswith(human)
    assert not (new/"results"/(wid+".json")).exists()
    assert call(root,"viewer",verify_record["address"])["address"]==verify_record["address"]
    # Simulate a user supplying the attachment during verification in the isolated profile.
    # The next bind should discover it and skip the remote acquire.
    data=engine.read(new/"batch.json")
    work=next(w for w in data["works"] if w["work_id"]==wid)
    file=root/"fixture.pdf"
    file.write_bytes(sample_pdf())
    work["local_pdf"]=dict(path=str(file),sha256=engine.digest(file.read_bytes()))
    engine.write(new/"batch.json",data)
    def progress(msg):
        if work["title"] in msg:stop.set()
    engine.execute(root,new,stop,progress)
    assert engine.read(new/"results"/(wid+".json"))["method"]=="local"
    assert not (new/"verification.json").exists()
    assert all((new/"results"/name).read_bytes()==raw for name,raw in retained.items())
    output=export(new,root)
    rows=[json.loads(s) for s in (output/"逐条结果.jsonl").read_text(encoding="utf-8").splitlines()]
    assert len(rows)==len(batch["records"]) and sum(r["status"]=="obtained" for r in rows)==sum(r["work_id"]==wid or r["work_id"]+".json" in retained for r in batch["records"])
    print("PASS",len(rows),"original rows;",len(retained),"inherited; one additional; cumulative export verified",flush=True)
    if "--online" in sys.argv:
        try: print("Live sample via",current,call(root,"probe",current),flush=True)
        except Exception as e: print("Live sample via",current,str(e),flush=True)
    server.shutdown()

if __name__=="__main__":
    live=Path(sys.argv[1]).resolve()  # 指定隔离的旧批次副本目录
    with tempfile.TemporaryDirectory(prefix="ld-site-test-") as folder:
        root=Path(folder)
        engine.setup(root)
        extension="desktop@local.invalid.xpi"
        shutil.copyfile(here/"build/dist/LiteratureDesk/bridge"/extension,root/"profile/extensions"/extension)
        proc=subprocess.Popen([str(Path(os.environ["ProgramFiles"])/"Zotero/zotero.exe"),"-no-remote","-profile",str(root/"profile")])
        try:
            deadline=time.monotonic()+100
            while not engine.connected(root):
                if time.monotonic()>deadline:raise RuntimeError("isolated bridge did not connect")
                time.sleep(.5)
            verify(root,live)
        finally:
            # Zotero's Windows launcher can hand off to another PID.
            env=dict(os.environ,LD_QA_PROFILE=str(root/"profile"))
            subprocess.run(["powershell.exe","-NoProfile","-Command",
                            "Get-CimInstance Win32_Process -Filter \"Name='zotero.exe'\" | "
                            "Where-Object { $_.CommandLine -and $_.CommandLine.TrimEnd([char]34).EndsWith($env:LD_QA_PROFILE) } | "
                            "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"],env=env,check=True)
            proc.wait(timeout=12)
            time.sleep(2)
