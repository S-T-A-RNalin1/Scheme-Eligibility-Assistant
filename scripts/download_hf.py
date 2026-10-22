"""Download the shrijayan/gov_myscheme PDFs from Hugging Face.

Usage:  HF_TOKEN=... python scripts/download_hf.py
The token is read from the environment only; never commit it.
"""
import os
import pathlib
from concurrent.futures import ThreadPoolExecutor

import requests

REPO = "shrijayan/gov_myscheme"
OUT = pathlib.Path(__file__).absolute().parent.parent / "data" / "raw_pdfs"
HEADERS = {"Authorization": f"Bearer {os.environ['HF_TOKEN']}"} if os.environ.get("HF_TOKEN") else {}


def list_pdfs():
    url = f"https://huggingface.co/api/datasets/{REPO}/tree/main/text_data?recursive=true"
    files = requests.get(url, headers=HEADERS, timeout=60).json()
    # The dataset ships duplicate "<slug> copy.pdf" files; skip them.
    return [f["path"] for f in files if f["path"].endswith(".pdf") and " copy" not in f["path"]]


def fetch(path):
    dest = OUT / pathlib.Path(path).name
    if dest.exists() and dest.stat().st_size > 0:
        return
    for attempt in range(4):
        try:
            r = requests.get(f"https://huggingface.co/datasets/{REPO}/resolve/main/{path}", headers=HEADERS, timeout=60)
            r.raise_for_status()
            dest.write_bytes(r.content)
            return
        except requests.RequestException as exc:
            err = exc
    print(f"failed {path}: {err}")


if __name__ == "__main__":
    OUT.mkdir(parents=True, exist_ok=True)
    paths = list_pdfs()
    print(f"{len(paths)} PDFs listed")
    with ThreadPoolExecutor(8) as pool:
        list(pool.map(fetch, paths))
    print(f"{len(list(OUT.glob('*.pdf')))} PDFs on disk in {OUT}")
