"""Read-only check of both journals, wall-clock progress, and actual PDF contents."""
import hashlib
import json
import re
import subprocess
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent / "local-run"


def read(file):
    return json.loads(file.read_text(encoding="utf-8"))


def compact(text):
    return "".join(c for c in unicodedata.normalize("NFKD", text.casefold()) if c.isalnum())


def utc(ms):
    return datetime.fromtimestamp(ms / 1000, timezone.utc).isoformat()


def verify_pdf(receipt, paper):
    file = Path(receipt["path"]).resolve(strict=True)
    assert (ROOT / "data/storage") in file.parents
    text = subprocess.check_output(["pdftotext", "-enc", "UTF-8", str(file), "-"],
                                   timeout=30).decode("utf-8")
    pages = [p for p in text.split("\f") if p.strip()]
    front = compact(" ".join(pages[:2]))
    title_ok = compact(paper["title"]) in front
    doi_ok = compact(paper["doi"]) in front
    body_ok = len(pages) >= 2 and len(text.split()) >= 400 and bool(
        re.search(r"(?i)\b(references|bibliography)\b", text))
    return {"doi": paper["doi"], "pages":len(pages), "bytes":file.stat().st_size,
            "title_match":title_ok, "doi_match":doi_ok, "body":body_ok,
            "verified":title_ok and doi_ok and body_ok,
            "sha256":hashlib.sha256(file.read_bytes()).hexdigest()}


def audit(name, papers):
    directory = ROOT / name
    state = read(directory / "state.json")
    receipts = [read(directory / "results" / f"{i}.json") for i in range(state["next"])]
    assert len(receipts) == state["obtained"] + state["missing"]
    assert state["calls"] == state["next"] + (state["active"] is not None)
    details = []
    for i, result in enumerate(receipts):
        assert result["index"] == i
        if name == "controlled":
            assert result["status"] == ("missing" if i % 5 == 1 else "obtained")
        elif result["status"] == "obtained":
            details.append(verify_pdf(result, papers[i]))
    gaps = [b["at"]-a["at"] for a,b in zip(receipts,receipts[1:])]
    return {"phase":state["phase"], "start":utc(state["started"]),
            "last_progress":utc(state["last"]), "observed_seconds":(state["last"]-state["started"])/1000,
            "longest_gap_seconds":max(gaps,default=0)/1000,"calls":state["calls"],
            "obtained":state["obtained"], "missing":state["missing"], "total":state["tasks"],
            "reason":state.get("reason"), "pdfs":details}


if __name__ == "__main__":
    papers = read(ROOT / "profile/step3.json")["papers"]
    print(json.dumps({n:audit(n,papers) for n in ("real","controlled")}, indent=2))
