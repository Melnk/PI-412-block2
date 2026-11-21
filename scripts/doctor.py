"""Check development dependencies and asset integrity without training models."""
import argparse
import hashlib
import json
import platform
import sqlite3
from datetime import datetime, timezone
from importlib.metadata import version

from incidentlab.config import ROOT, load_settings
from incidentlab.llm import probe


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ml", action="store_true")
    args = parser.parse_args()
    checks = {}
    settings = load_settings()
    checks["families"] = [m.family for m in settings.models]
    checks["versions"] = {p: version(p) for p in ["fastapi", "langgraph", "pydantic", "httpx", "langgraph-checkpoint-sqlite"]}
    with sqlite3.connect(":memory:") as db:
        db.execute("CREATE VIRTUAL TABLE docs USING fts5(content)")
        db.execute("INSERT INTO docs VALUES ('database connection timeout')")
        checks["sqlite_fts5"] = bool(db.execute("SELECT * FROM docs WHERE docs MATCH 'timeout'").fetchone())
    manifest = json.loads((ROOT / "config/model-manifest.json").read_text())
    checks["assets"] = []
    for model in manifest:
        target = ROOT / "models" / model["filename"]
        if target.exists():
            with target.open("rb") as source:
                digest = hashlib.file_digest(source, "sha256").hexdigest()
            checks["assets"].append({"id": model["name"], "verified": digest == model["sha256"], "bytes": target.stat().st_size})
        else:
            checks["assets"].append({"id": model["name"], "verified": False})
    checks["model_endpoints"] = [probe(model) for model in settings.models]
    if args.ml:
        import torch
        layer = torch.nn.Linear(3, 1)
        value = layer(torch.ones(2, 3)).square().sum()
        value.backward()
        checks["torch"] = {"version": torch.__version__, "device": "cpu",
                           "forward_backward_finite": bool(torch.isfinite(value) and torch.isfinite(layer.weight.grad).all())}
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(),
              "scope": "Development prerequisites, not a trained agent or recommender", "checks": checks}
    (ROOT / "results/readiness/environment.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    good = checks["sqlite_fts5"] and all(m["verified"] for m in checks["assets"])
    if args.ml:
        good &= checks["torch"]["forward_backward_finite"]
    raise SystemExit(0 if good else 1)


if __name__ == "__main__":
    main()
