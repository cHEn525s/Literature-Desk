import os
from pathlib import Path
import sys

def main():
    if len(sys.argv)==4 and sys.argv[1]=="--extract-pdf":
        from pypdf import PdfReader
        try:
            reader=PdfReader(sys.argv[2])
            if reader.is_encrypted:return 1
            Path(sys.argv[3]).write_text("\f".join(page.extract_text() for page in reader.pages),encoding="utf-8")
            return 0
        except Exception:return 1
    import tkinter as tk
    from tkinter import messagebox
    from desktop import App
    win=tk.Tk()
    title_icon=tk.PhotoImage(file=str(Path(__file__).with_name("titlebar.png")))
    win.iconphoto(True,title_icon)
    try:
        app=App(win,Path(os.environ["LOCALAPPDATA"])/"ZoteroFullText"/"workspace")
    except Exception as e:
        messagebox.showerror("文献正文获取工具","无法打开工作目录，请检查是否已打开程序。\n"+str(e))
        win.destroy()
        return 1
    win.mainloop()
    return 0

if __name__=="__main__":
    sys.exit(main())
