"""Pinned asset downloader. No model code execution or unverified archives."""
import argparse
import hashlib
import json
import os
import platform
import tarfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def download(url, target, expected):
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        temporary = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=180) as source, temporary.open("wb") as destination:
            while chunk := source.read(8 * 1024 * 1024):
                destination.write(chunk)
        os.replace(temporary, target)
    with target.open("rb") as source:
        actual = hashlib.file_digest(source, "sha256").hexdigest()
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {target.name}; do not use this asset")
    print(f"Verified {target.name}: {actual}", flush=True)


def fetch_model(model):
    url = f"https://huggingface.co/{model['repository']}/resolve/{model['revision']}/{model['filename']}"
    download(url, ROOT / "models" / model["filename"], model["sha256"])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--models", action="store_true")
    parser.add_argument("--engine", action="store_true")
    args = parser.parse_args()
    if not (args.models or args.engine):
        parser.error("Choose --models and/or --engine")
    if args.models:
        manifest = json.loads((ROOT / "config/model-manifest.json").read_text())
        with ThreadPoolExecutor(3) as pool:
            list(pool.map(fetch_model, manifest))
    if args.engine:
        if (platform.system(), platform.machine()) != ("Darwin", "x86_64"):
            raise SystemExit("This pinned engine package is macOS Intel only; see infra/README.md for Linux build.")
        manifest = json.loads((ROOT / "config/engine-manifest.json").read_text())
        archive = ROOT / "runtime" / manifest["url"].rsplit("/", 1)[-1]
        download(manifest["url"], archive, manifest["sha256"])
        with tarfile.open(archive) as source:
            source.extractall(ROOT / "runtime/llama", filter="data")


if __name__ == "__main__":
    main()
