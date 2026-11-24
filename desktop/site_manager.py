import queue
import re
import threading
import time
import tkinter as tk
import uuid
from datetime import datetime
from tkinter import ttk, simpledialog, messagebox
from urllib.parse import urlsplit
from pypdf import PdfReader
from engine import connected, read, write

DEFAULTS = ["http://sci-hub."+suffix for suffix in ("al","mk","ee","vg","st")] + [
    "https://"+host for host in ("sci-hub.mobi","sci-hub.run","scihub.asia","sci-hub.se","sci-hub.st","sci-hub.ru")]

def address(value):
    value=value.strip().rstrip("/")
    url=urlsplit(value)
    if url.scheme not in {"https","http"} or not url.hostname or url.username or url.password or url.query or url.fragment:
        raise ValueError("请输入完整的 HTTP 或 HTTPS 站点地址")
    return value+"/"

def call(root,op,url=""):
    if not connected(root): raise ValueError("请先连接专用 Zotero")
    hello=read(root/"hello.json")
    if hello.get("sites")!=1: raise ValueError("请正常关闭专用 Zotero，再点“连接专用 Zotero”加载新版桥接")
    key=uuid.uuid4().hex
    reply=root/"replies"/(key+".site.json")
    pdf=root/"replies"/(key+".probe.pdf")
    write(root/"site-request.json",dict(id=key,op=op,address=url,token=hello["token"],until=int(time.time()*1000)+45000))
    deadline=time.monotonic()+48
    try:
        while not reply.is_file():
            if time.monotonic()>deadline: raise TimeoutError("专用 Zotero 请求超时")
            time.sleep(.15)
        result=read(reply)
        if result.get("error"): raise ValueError(result["error"])
        if result.get("status")=="待核对测试论文":
            with pdf.open("rb") as stream:
                page=PdfReader(stream).pages[0]
                text=re.sub(r"\s+","",page.extract_text() or "").casefold()
                if "10.1371/journal.pmed.0020124" not in text and "whymostpublishedresearchfindingsarefalse" not in text:
                    raise ValueError("PDF 首页未匹配固定论文")
            result["status"]="可获取 PDF"
        return result
    finally:
        pdf.unlink(missing_ok=True)

class SiteManager:
    def __init__(self,app):
        self.root=app.root
        self.path=self.root/"sites.json"
        self.data=read(self.path) if self.path.exists() else {address(s):{} for s in DEFAULTS}
        self.events=queue.Queue()
        self.busy=False
        self.win=tk.Toplevel(app.window)
        self.win.title("站点管理")
        self.win.transient(app.window)
        self.win.grab_set()
        self.current=tk.StringVar(value="读取中")
        ttk.Label(self.win,textvariable=self.current).pack(anchor="w",padx=8,pady=5)
        self.table=ttk.Treeview(self.win,columns=("url","status","detail","time"),show="headings",selectmode="browse")
        for col,title,width in zip(self.table["columns"],("站点","本次结果","原因或实际落点","测试时间"),(185,105,345,130)):
            self.table.heading(col,text=title)
            self.table.column(col,width=width)
        self.table.pack(fill="both",expand=True)
        bar=ttk.Frame(self.win)
        bar.pack(fill="x")
        self.buttons=[]
        for title,fn in [("添加",lambda:self.edit(False)),("编辑",lambda:self.edit(True)),("移除",self.remove),
                         ("测试所选",lambda:self.probe(False)),("测试全部",lambda:self.probe(True)),
                         ("设为当前",self.select),("打开验证页",self.viewer)]:
            btn=ttk.Button(bar,text=title,command=fn)
            btn.pack(side="left",padx=2,pady=5)
            self.buttons.append(btn)
        self.refresh()
        self.win.protocol("WM_DELETE_WINDOW",self.close)
        self.work(lambda:self.events.put(("current",call(self.root,"current")["address"])))
        self.win.after(120,self.poll)

    def close(self):
        if self.busy:
            messagebox.showinfo("站点管理","本次测试完成后即可关闭。",parent=self.win)
        else:self.win.destroy()

    def refresh(self):
        chosen=self.table.selection()
        self.table.delete(*self.table.get_children())
        for url,row in self.data.items():
            self.table.insert("","end",iid=url,values=(url,row.get("status","未测试"),row.get("detail",""),row.get("time","")))
        if chosen and chosen[0] in self.data:self.table.selection_set(chosen[0])

    def save(self):
        write(self.path,self.data)
        self.refresh()

    def chosen(self):
        rows=self.table.selection()
        if rows:return rows[0]
        messagebox.showinfo("站点管理","请先选中一个站点。",parent=self.win)

    def edit(self,existing):
        old=self.chosen() if existing else None
        if existing and not old:return
        value=simpledialog.askstring("站点地址","HTTP 或 HTTPS 地址",initialvalue=old or "",parent=self.win)
        if not value:return
        try:new=address(value)
        except ValueError as e:
            messagebox.showerror("站点地址",str(e),parent=self.win)
            return
        if old!=new:
            if old:self.data.pop(old)
            self.data.setdefault(new,{})
            self.save()
        self.table.selection_set(new)

    def remove(self):
        url=self.chosen()
        if url:
            self.data.pop(url)
            self.save()

    def work(self,fn):
        self.busy=True
        for b in self.buttons:b.state(["disabled"])
        def run():
            try:fn()
            except Exception as e:self.events.put(("error",str(e)))
            finally:self.events.put(("done",None))
        threading.Thread(target=run,daemon=True).start()

    def probe(self,all_sites):
        urls=list(self.data) if all_sites else [self.chosen()]
        if not urls or not urls[0]:return
        def run():
            for url in urls:
                try:
                    result=call(self.root,"probe",url)
                    status,detail=result["status"],result["landing"]
                except Exception as e:status,detail="测试失败",str(e)
                self.events.put(("result",(url,dict(status=status,detail=detail,time=datetime.now().strftime("%m-%d %H:%M:%S")))))
        self.work(run)

    def select(self):
        url=self.chosen()
        if url:self.work(lambda:self.events.put(("current",call(self.root,"select",url)["address"])))

    def viewer(self):
        url=self.chosen()
        if url and self.data[url].get("status")=="需要人工验证":
            self.work(lambda:call(self.root,"viewer",self.data[url]["detail"]))
        elif url:messagebox.showinfo("验证页","请先测试站点，出现人工验证时可以打开对应页面。",parent=self.win)

    def poll(self):
        while not self.events.empty():
            kind,value=self.events.get()
            if kind=="current":
                self.current.set("插件当前地址："+value)
                self.data.setdefault(address(value),{})
                self.save()
            elif kind=="result":
                url,row=value
                self.data[url]=row
                self.save()
            elif kind=="error":
                self.current.set("站点操作提示："+value)
            else:
                self.busy=False
                for b in self.buttons:b.state(["!disabled"])
        self.win.after(120,self.poll)
