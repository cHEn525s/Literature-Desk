import msvcrt
import os
from pathlib import Path
import queue
import threading
import time
from datetime import datetime
import tkinter as tk
from tkinter import filedialog, messagebox, simpledialog, ttk
from engine import HERE, COLUMNS, connected, create, copy_batch, execute, history, launch, read, write
from openpyxl import load_workbook
from delivery import export
from library_location import relocate
from site_manager import SiteManager, call as site_call

class App:
    def __init__(self,window,root):
        self.window=window
        self.root=root
        root.mkdir(parents=True,exist_ok=True)
        self.lock=(root/"desktop.lock").open("a+b")
        self.lock.seek(0)
        msvcrt.locking(self.lock.fileno(),msvcrt.LK_NBLCK,1)
        self.files=[]
        self.options={}
        self.folders=[]
        self.job=None
        self.busy=False
        self.phase="draft"
        self.operation=None
        self.events=queue.Queue()
        self.stop=threading.Event()
        self.last_export=None
        self.connect_until=0
        window.title("Literature Desk")
        window.geometry("880x510")
        window.minsize(700,420)
        frame=ttk.Frame(window,padding=18)
        frame.pack(fill="both",expand=True)
        top=ttk.Frame(frame)
        top.pack(fill="x")
        ttk.Label(top,text="批次父分类").pack(side="left")
        self.parent=tk.StringVar(value="本批文献")
        ttk.Entry(top,textvariable=self.parent,width=26).pack(side="left",padx=8)
        self.connection=tk.StringVar()
        ttk.Label(top,textvariable=self.connection).pack(side="right")
        self.buttons={}
        def button(bar,text,fn):
            b=ttk.Button(bar,text=text,command=fn)
            b.pack(side="left",padx=(0,6))
            self.buttons[text]=b
        bar=ttk.Frame(frame)
        bar.pack(fill="x",pady=12)
        button(bar,"选择文件",self.select)
        button(bar,"打开历史批次",self.open_history)
        button(bar,"分组与列映射",self.configure)
        button(bar,"本地 PDF 目录",self.folder)
        button(bar,"导入预览",self.prepare)
        button(bar,"连接专用 Zotero",self.connect)
        button(bar,"文库位置",self.location)
        button(bar,"站点管理",self.sites)
        self.table=ttk.Treeview(frame,columns=("file","sheet","group","count"),show="headings",height=8)
        for col,label,width in zip(("file","sheet","group","count"),("原文件","工作表","Zotero 子分类","原始条数"),(260,130,190,75)):
            self.table.heading(col,text=label)
            self.table.column(col,width=width)
        self.table.pack(fill="both",expand=True)
        self.status=tk.StringVar(value="选择 BibTeX 或 Excel 文件开始。")
        ttk.Label(frame,textvariable=self.status,wraplength=790).pack(fill="x",pady=8)
        actions=ttk.Frame(frame)
        actions.pack(fill="x")
        button(actions,"开始",self.start)
        button(actions,"暂停",self.pause)
        button(actions,"继续",self.start)
        button(actions,"中止任务",self.abort)
        button(actions,"导出交付",self.deliver)
        button(actions,"用原题录新建批次",self.restart_batch)
        button(actions,"只重跑未取得",self.retry_missing)
        self.verify_bar=ttk.Frame(frame)
        ttk.Button(self.verify_bar,text="打开验证页",command=self.open_verification).pack(side="left")
        ttk.Button(self.verify_bar,text="已完成验证，继续当前篇",command=self.start).pack(side="left")
        if (root/"current.json").exists():
            self.show_job(root/"batches"/read(root/"current.json"))
        self.window.protocol("WM_DELETE_WINDOW",self.close)
        self.update()

    def close(self):
        if self.busy:
            self.pause()
            self.status.set("正在收尾，请在停点保存后关闭窗口。")
            return
        self.window.after_cancel(self.timer)
        self.lock.close()
        self.window.destroy()

    def table_rows(self,rows):
        self.table.delete(*self.table.get_children())
        for values in rows: self.table.insert("","end",values=values)

    def show_files(self):
        self.table_rows([(p.name,self.options[str(p)]["sheet"] or "—",self.options[str(p)]["group"],"待预览") for p in self.files])

    def select(self):
        chosen=filedialog.askopenfilenames(filetypes=[("题录文件","*.bib *.xlsx")])
        if not chosen: return
        if self.job and self.phase!="aborted" and (self.job/"pending.json").exists():
            messagebox.showwarning("请求待确认","请先继续原批次并核对未决请求。")
            return
        try:
            files=list(dict.fromkeys(Path(x) for x in chosen))
            options={}
            for p in files:
                sheet=None
                if p.suffix.lower()==".xlsx":
                    book=load_workbook(p,read_only=True)
                    sheet="纳入记录" if "纳入记录" in book.sheetnames else book.active.title
                    book.close()
                options[str(p)]=dict(sheet=sheet,group=p.stem,mapping={})
            self.files,self.options,self.job=files,options,None
            self.phase="draft"
            self.show_files()
            self.status.set("核对工作表与分组后，点击“导入预览”。")
        except Exception as e: messagebox.showerror("输入文件",str(e))

    def open_history(self):
        if self.job and self.phase!="aborted" and (self.job/"pending.json").exists():
            messagebox.showwarning("请求待确认","请先继续或中止当前批次，再切换批次。")
            return
        self.status.set("正在读取历史批次和取得数…")
        self.worker(lambda:("history",history(self.root)),"history")

    def choose_history(self,entries):
        self.status.set("请选择需要打开的历史批次。" if entries else "还没有已保存的批次。")
        if not entries: return
        dialog=tk.Toplevel(self.window)
        dialog.title("打开历史批次")
        dialog.transient(self.window)
        table=ttk.Treeview(dialog,columns=("time","file","phase","got","id"),show="headings",selectmode="browse")
        for col,title,width in zip(table["columns"],("创建时间","原始文件","状态","已取得 / 原始条数","批次编号"),(145,280,75,130,85)):
            table.heading(col,text=title)
            table.column(col,width=width)
        phases={"ready":"待开始","aborted":"已中止","done":"已完成","running":"待继续","paused":"已暂停"}
        for stamp,job,phase,name,total,got in entries:
            table.insert("","end",iid=job.name,values=(datetime.fromtimestamp(stamp).strftime("%Y-%m-%d %H:%M"),
                         name,phases.get(phase,phase),f"{got} / {total}",job.name[:8]))
        bar=ttk.Scrollbar(dialog,orient="vertical",command=table.yview)
        table.configure(yscrollcommand=bar.set)
        bar.pack(side="right",fill="y")
        table.pack(fill="both",expand=True)
        def choose(event=None):
            selection=table.selection()
            if selection:
                job=self.root/"batches"/selection[0]
                self.show_job(job)
                write(self.root/"current.json",job.name)
                self.files,self.options,self.folders=[],{},[]
                dialog.destroy()
        table.bind("<Double-1>",choose)
        table.bind("<Return>",choose)
        ttk.Button(dialog,text="打开选中批次",command=choose).pack(pady=6)
        dialog.grab_set()

    def configure(self):
        selected=self.table.selection()
        if not selected or self.job: return
        p=self.files[self.table.index(selected[0])]
        option=self.options[str(p)].copy()
        group=simpledialog.askstring("子分类","目标子分类名称",initialvalue=option["group"])
        if not group or not group.strip(): return
        option["group"]=group.strip()
        if p.suffix.lower()==".xlsx":
            book=load_workbook(p,read_only=True)
            try:
                sheet=simpledialog.askstring("工作表","可选工作表："+ "、".join(book.sheetnames),initialvalue=option["sheet"])
                if sheet not in book.sheetnames: return
                option["sheet"]=sheet
                headers=list(next(book[sheet].values))
                keys=list(COLUMNS)
                defaults=[option["mapping"].get(k,COLUMNS[k]) for k in keys]
                columns=simpledialog.askstring("字段映射","依次填写 "+ " / ".join(COLUMNS[k] for k in keys)+
                    " 对应的列名，用 | 分隔。可留空。\n表头："+ "、".join(map(str,headers)),initialvalue="|".join(defaults))
                if columns is None:return
                values=[v.strip() for v in columns.split("|")]
                if len(values)!=len(keys) or values[0] not in headers:
                    messagebox.showerror("字段映射","请检查字段数量及标题列名称");return
                option["mapping"]=dict(zip(keys,values))
            finally: book.close()
        self.options[str(p)]=option
        self.show_files()

    def folder(self):
        d=filedialog.askdirectory(title="添加本地 PDF 搜索目录")
        if d and Path(d) not in self.folders:
            self.folders.append(Path(d))
            self.status.set("本地 PDF 目录："+"、".join(map(str,self.folders)))

    def worker(self,fn,operation):
        if self.busy:return
        self.busy=True
        self.operation=operation
        self.stop.clear()
        def run():
            try: self.events.put(fn())
            except Exception as e:self.events.put(("end","已停止："+str(e)))
        threading.Thread(target=run,daemon=True).start()

    def location(self):
        current=(self.root/"data").resolve()
        if not messagebox.askokcancel("文库位置",f"当前位置：{current}\n\n先关闭专用 Zotero，再选择目标文件夹。程序会在其中新建 ZoteroFullText-Data，复制并校验已有文库及 PDF，保留原件。"):return
        folder=filedialog.askdirectory(title="选择存放专用文库及 PDF 的父目录")
        if folder:
            self.status.set("正在复制并核对文库，请保持专用 Zotero 关闭。")
            self.worker(lambda:("end",relocate(self.root,folder)),"relocate")

    def abort(self):
        if not self.job or not messagebox.askyesno("中止本批次","结束本批并停止派发剩余论文？已取得结果可以导出。已提交给 Zotero 的单项调用可能自行结束。"):return
        (self.job/"aborted").touch()
        write(self.job/"phase.json","aborted")
        self.stop.set()
        self.phase="aborted"
        self.status.set("已中止。可以导出已处理结果，或点“选择文件”开始其他批次。")

    def prepare(self):
        name=self.parent.get().strip()
        self.worker(lambda:("job",create(self.root,self.files,name,self.folders,self.options)),"prepare")

    def show_job(self,job):
        batch=read(job/"batch.json")
        self.job=job
        state=job/"phase.json"
        self.phase=read(state) if state.exists() else "ready"
        if (job/"aborted").exists(): self.phase="aborted"
        if self.phase=="running":self.phase="paused"
        self.parent.set(batch["parent"])
        sheets={r["source_id"]:r["locator"].get("sheet","—") for r in batch["records"]}
        self.table_rows([(s["file"],sheets.get(s["source_id"],"—"),s["group"],s["count"]) for s in batch["sources"]])
        self.status.set(f"原始题录 {len(batch['records'])} 条，归并后 {len(batch['works'])} 篇，已处理 {len(list((job/'results').glob('*.json')))} 篇。")
        if batch.get("retry_from") and self.phase=="ready":
            retained=len(list((job/"results").glob("*.json")))
            self.status.set(f"已保留 {retained} 篇正文，待重跑 {len(batch['works'])-retained} 篇。点“开始”运行。")
        if self.phase=="paused":self.status.set("已暂停。"+self.status.get())
        if self.phase=="aborted":self.status.set("已中止。"+self.status.get())

    def connect(self):
        try:
            launch(self.root)
            self.connect_until=time.monotonic()+45
        except FileNotFoundError:
            exe=filedialog.askopenfilename(title="定位已安装的 Zotero",filetypes=[("Zotero","zotero.exe")])
            if exe:
                try: launch(self.root,exe);self.connect_until=time.monotonic()+45
                except Exception as e:self.status.set(str(e))
        except Exception as e:self.status.set(str(e))

    def sites(self):
        if self.job and self.phase!="aborted" and (self.job/"pending.json").exists():
            messagebox.showinfo("站点管理","请先继续原请求并等待结果，或中止任务后切换。")
            return
        SiteManager(self)

    def open_verification(self):
        address=read(self.job/"verification.json")["address"]
        def open_page():
            site_call(self.root,"viewer",address)
            return "end","请在专用 Zotero 完成验证，再点“已完成验证，继续当前篇”。"
        self.worker(open_page,"viewer")

    def restart_batch(self):
        if self.job and self.phase in {"aborted","done"}:
            self.worker(lambda:("job",copy_batch(self.root,self.job)),"prepare")

    def retry_missing(self):
        if self.busy or not self.job or self.phase not in {"aborted","done"}:return
        def prepare_retry():
            job=copy_batch(self.root,self.job,missing_only=True)
            return ("job",job) if job else ("end","本批正文已全部取得，无需重跑。")
        self.status.set("正在核对已取得的 PDF，准备缺件批次。")
        self.worker(prepare_retry,"prepare")

    def start(self):
        if self.job and not self.busy:
            self.phase="running"
            write(self.job/"phase.json",self.phase)
            self.worker(lambda:("end",execute(self.root,self.job,self.stop,
                  lambda s:self.events.put(("progress",s)))),"run")

    def pause(self):
        self.stop.set()
        self.status.set("已请求暂停，当前条目完成后保存停点。")

    def deliver(self):
        d=filedialog.askdirectory(title="选择交付目录")
        if d and self.job:self.worker(lambda:("export",export(self.job,Path(d))),"export")

    def update(self):
        while not self.events.empty():
            event,value=self.events.get()
            if event=="progress":self.status.set(value);continue
            self.busy=False
            if self.operation=="run":
                if (self.job/"aborted").exists():
                    self.phase="aborted"
                    value="已中止。可以导出已处理结果，或点“选择文件”开始其他批次。"
                else:self.phase="done" if value=="已完成" else "paused"
                write(self.job/"phase.json",self.phase)
            self.operation=None
            if event=="job":self.show_job(value)
            elif event=="history":self.choose_history(value)
            elif event=="export":
                self.last_export=value
                self.status.set("已导出："+str(value))
            else:self.status.set(value)
        online=connected(self.root)
        if self.connect_until:
            if online:
                self.connect_until=0
                hints={"aborted":"当前批次已中止。点“用原题录新建批次”，再点“开始”。","paused":"当前批次已暂停，点“继续”。","ready":"批次已就绪，点“开始”。","done":"当前批次已完成，可导出交付。"}
                self.status.set(f"已连接：{(self.root/'data').resolve()}。"+hints.get(self.phase,"请选择输入文件。"))
            elif time.monotonic()>=self.connect_until:
                self.connect_until=0
                self.status.set(f"尚未收到桥接回应。请检查专用 Zotero 窗口和文库位置：{(self.root/'data').resolve()}")
        self.connection.set("专用库已连接" if online else ("正在连接…" if self.connect_until else "专用库未连接"))
        for label,b in self.buttons.items():
            enabled=not self.busy
            if label=="暂停": enabled=self.operation=="run"
            elif label=="中止任务":enabled=self.phase in {"ready","paused","running"} and self.operation in {None,"run"}
            elif label=="连接专用 Zotero":enabled=enabled and not self.connect_until
            elif label in {"用原题录新建批次","只重跑未取得"}:enabled=enabled and self.phase in {"aborted","done"}
            elif label=="开始":enabled=enabled and self.phase=="ready"
            elif label=="继续":enabled=enabled and self.phase=="paused"
            elif label=="导出交付": enabled=enabled and bool(self.job)
            elif label in {"分组与列映射","导入预览","本地 PDF 目录"}:enabled=enabled and bool(self.files) and not self.job
            b.configure(state="normal" if enabled else "disabled")
        if self.job and self.phase=="paused" and not self.busy and (self.job/"verification.json").exists():
            self.verify_bar.pack(anchor="w",pady=4)
        else:self.verify_bar.pack_forget()
        self.timer=self.window.after(150,self.update)

if __name__=="__main__":
    win=tk.Tk()
    try: app=App(win,HERE/"local-run")
    except OSError as e:
        messagebox.showerror("打开失败","请检查是否已有桌面端正在运行。\n"+str(e));win.destroy()
    else:win.mainloop()
