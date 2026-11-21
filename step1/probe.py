"""Prepare a fresh isolated fixture, then exercise the real Zotero bridge."""
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import sys
import time
import uuid
import zipfile

HERE = Path(__file__).resolve().parent
ROOT = HERE / "local-run"
PROFILE = ROOT / "profile"


def write(path, value):
    temp = path.with_suffix(".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    os.replace(temp, path)


def fixture_pdf():
    stream = b"BT /F1 14 Tf 40 700 Td (Synthetic bridge fixture) Tj ET"
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>",
               b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
               b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Resources << /Font << /F1 4 0 R >> >> /Contents 5 0 R >>",
               b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
               b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream"]
    data = bytearray(b"%PDF-1.4\n")
    offsets = [0]
    for n, obj in enumerate(objects, 1):
        offsets.append(len(data))
        data.extend(b"%d 0 obj\n" % n + obj + b"\nendobj\n")
    start = len(data)
    data.extend(b"xref\n0 6\n0000000000 65535 f \n")
    for offset in offsets[1:]:
        data.extend(b"%010d 00000 n \n" % offset)
    data.extend(b"trailer\n<< /Root 1 0 R /Size 6 >>\nstartxref\n%d\n%%%%EOF\n" % start)
    return bytes(data)


def prepare():
    ROOT.mkdir(exist_ok=False)
    for name in ["profile/extensions", "data", "commands", "receipts"]:
        (ROOT / name).mkdir(parents=True)
    write(PROFILE / "step1.json", {"root": str(ROOT), "token": uuid.uuid4().hex})
    prefs = {"extensions.zotero.dataDir": str(ROOT / "data"),
             "extensions.zotero.useDataDir": True,
             "extensions.zotero.httpServer.enabled": False,
             "extensions.zotero.firstRun2": False,
             "extensions.update.enabled": False,
             "extensions.autoDisableScopes": 0, "extensions.enabledScopes": 15}
    (PROFILE / "user.js").write_text("".join(
        f"user_pref({json.dumps(k)}, {json.dumps(v)});\n" for k, v in prefs.items()
    ), encoding="utf-8")
    with zipfile.ZipFile(PROFILE / "extensions/step1@local.invalid.xpi", "x") as z:
        for name in ["manifest.json", "bootstrap.js"]:
            z.write(HERE / name, name)
    (ROOT / "fixture.pdf").write_bytes(fixture_pdf())


def receive(path):
    deadline = time.monotonic() + 60
    while not path.exists():
        error = ROOT / "error.json"
        if error.exists():
            raise RuntimeError(error.read_text(encoding="utf-8"))
        if time.monotonic() >= deadline:
            raise TimeoutError(path.name)
        time.sleep(0.25)
    value = json.loads(path.read_text(encoding="utf-8"))
    if "error" in value:
        raise RuntimeError(value)
    return value


def exercise():
    cfg = receive(PROFILE / "step1.json")
    hello = receive(ROOT / "hello.json")
    assert hello["token"] == cfg["token"] and hello["protocol"] == 1
    assert Path(hello["data"]) == ROOT / "data" and Path(hello["profile"]) == PROFILE
    db = sqlite3.connect(ROOT / "bridge-lock.sqlite", timeout=0)
    try:
        db.execute("BEGIN EXCLUSIVE")
    except sqlite3.OperationalError as exc:
        if "locked" not in str(exc):
            raise
    else:
        raise RuntimeError("Second writer acquired active bridge lock")
    finally:
        db.close()
    results = []
    for name in ["01.json", "02.json"]:
        write(ROOT / "commands" / name, {"token": cfg["token"], "command_id": "fixture-bind", "op": "bind"})
        receipt = receive(ROOT / "receipts" / name)
        assert receipt["command_id"] == "fixture-bind"
        results.append(receipt["result"])
    first, second = results
    assert first == second and first["count"] == 1 and first["libraryID"] == hello["libraryID"]
    groups = first["collections"]
    assert len(groups) == 2 and {g["name"] for g in groups} == {"Group A", "Group B"}
    assert groups[0]["parent"] and groups[0]["parent"] == groups[1]["parent"]
    assert len(first["attachments"]) == 1
    attachment = Path(first["attachments"][0]["path"]).resolve()
    assert (ROOT / "data/storage") in attachment.parents
    content = attachment.read_bytes()
    assert content == fixture_pdf()
    write(ROOT / "verified.json", {"version": hello["version"], "deliveries": 2,
          "lock_contender": "denied", "result": first, "pdf_sha256": hashlib.sha256(content).hexdigest()})
    (ROOT / "finish").touch()
    print("PASS: isolated handshake, exclusive lock, duplicate command, groups, stored PDF")


if __name__ == "__main__":
    {"prepare": prepare, "exercise": exercise}[sys.argv[1]]()
