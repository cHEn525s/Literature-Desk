"""Keep Zotero's logical paths stable when its on-disk library is relocated."""
import ctypes
from contextlib import contextmanager
import hashlib
import os
from pathlib import Path
import shutil
import stat
import subprocess
import uuid


@contextmanager
def closed_profile(root):
    profile=root/"profile"
    profile.mkdir(parents=True,exist_ok=True)
    kernel=ctypes.WinDLL("kernel32",use_last_error=True)
    kernel.CreateFileW.restype=ctypes.c_void_p
    handle=kernel.CreateFileW(str(profile/"parent.lock"),0xC0000000,0,None,4,128,None)
    if handle==ctypes.c_void_p(-1).value:
        raise RuntimeError("请先正常关闭专用 Zotero 窗口，再选择文库位置。")
    try: yield
    finally: kernel.CloseHandle(ctypes.c_void_p(handle))


def relocate(root,folder):
    source=root/"data"
    origin=source.resolve()
    target=(Path(folder)/"ZoteroFullText-Data").resolve()
    if target==origin:return f"当前文库已在 {origin}"
    if target.exists() or target.is_relative_to(root.resolve()) or target.is_relative_to(origin):
        raise ValueError("请另选文件夹。目标子目录必须尚不存在，并且位于当前工作区和文库之外。")
    if ctypes.windll.kernel32.GetDriveTypeW(target.anchor)!=3:
        raise ValueError("请选择本机固定磁盘。")
    with closed_profile(root):
        target.mkdir()
        files=0
        if source.exists():
            for directory,dirs,names in os.walk(origin):
                base=Path(directory)
                new=target/base.relative_to(origin)
                new.mkdir(exist_ok=True)
                for name in dirs+names:
                    if (base/name).lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT:
                        raise ValueError("文库中含其他文件链接，请核查。原文库仍保留。")
                for name in names:
                    src,dst=base/name,new/name
                    shutil.copy2(src,dst)
                    with src.open("rb") as a,dst.open("rb") as b:
                        if hashlib.file_digest(a,"sha256").digest()!=hashlib.file_digest(b,"sha256").digest():
                            raise OSError(f"复制校验失败：{src}")
                    files+=1
        suffix=uuid.uuid4().hex[:12]
        link=root/("data.link-"+suffix)
        backup=root/("data.backup-"+suffix)
        env=dict(os.environ,ZFT_LINK=str(link),ZFT_DEST=str(target))
        script="$ErrorActionPreference='Stop'; New-Item -ItemType Junction -Path $env:ZFT_LINK -Target $env:ZFT_DEST | Out-Null"
        subprocess.run(["powershell.exe","-NoProfile","-NonInteractive","-Command",script],
                       env=env,check=True,creationflags=subprocess.CREATE_NO_WINDOW)
        if link.resolve()!=target: raise OSError("目标路径核对失败")
        old_link=source.is_symlink() or (source.exists() and source.lstat().st_file_attributes & stat.FILE_ATTRIBUTE_REPARSE_POINT)
        if source.exists(): source.rename(backup)
        try: link.rename(source)
        except OSError:
            if backup.exists(): backup.rename(source)
            raise
        note=""
        if backup.exists():
            if old_link:
                backup.rmdir()
                note=f"原目录保留在 {origin}"
            else: note=f"原件保留在 {backup}，确认可打开原 PDF 后可手动清理该备份。"
        return f"文库位置：{target}。已校验 {files} 个文件。{note}"
