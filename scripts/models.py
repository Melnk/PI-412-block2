"""Start and stop only the project's loopback llama.cpp processes."""
import argparse
import json
import os
import signal
import socket
import subprocess
import time
from urllib.parse import urlsplit

import psutil

from incidentlab.config import ROOT, load_settings
from incidentlab.llm import probe

STATE = ROOT / "runtime/model-processes.json"


def start():
    settings = load_settings()
    binary = ROOT / "runtime/llama/llama-b12359/llama-server"
    if not binary.exists():
        raise SystemExit("Engine missing. Run scripts/fetch_assets.py --engine first.")
    running = json.loads(STATE.read_text()) if STATE.exists() else {}
    logs = ROOT / "runtime/logs"
    logs.mkdir(parents=True, exist_ok=True)
    # Exclude inherited LLAMA_* settings, tool configuration and proxy credentials.
    env = {k: v for k, v in os.environ.items() if k in {"PATH", "HOME", "TMPDIR", "LANG"}}
    for model in settings.models:
        if probe(model)["ready"]:
            print(f"{model.id}: endpoint already ready; not taking ownership")
            continue
        port = urlsplit(model.base_url).port
        with socket.socket() as check:
            if check.connect_ex(("127.0.0.1", port)) == 0:
                raise SystemExit(f"Port {port} is occupied by an unready/unrelated service")
        weight = ROOT / "models" / model.filename
        if not weight.exists():
            raise SystemExit(f"Missing {model.filename}. Run scripts/fetch_assets.py --models.")
        command = [str(binary), "-m", str(weight), "--alias", model.id,
                   "--host", "127.0.0.1", "--port", str(port),
                   "--threads", str(settings.threads), "--threads-batch", str(settings.threads),
                   "--ctx-size", str(settings.context_tokens), "--parallel", "1",
                   "--gpu-layers", "0", "--jinja", "--reasoning", "off",
                   "--no-op-offload", "--metrics", "--no-webui", "--no-agent", "--cors-origins", "localhost"]
        with (logs / f"{model.id}.log").open("ab") as log:
            proc = subprocess.Popen(command, stdout=log, stderr=log, cwd=ROOT, env=env,
                                    start_new_session=True)
        running[model.id] = {"pid": proc.pid, "created": psutil.Process(proc.pid).create_time()}
        STATE.write_text(json.dumps(running, indent=2)+"\n")
        print(f"{model.id}: starting pid={proc.pid}", flush=True)
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        statuses = [probe(model) for model in settings.models]
        if all(s["ready"] for s in statuses):
            print(json.dumps(statuses, indent=2))
            return
        time.sleep(1)
    raise SystemExit("Readiness timed out; inspect runtime/logs/*.log")


def stop():
    if not STATE.exists():
        return
    running = json.loads(STATE.read_text())
    for name, record in running.items():
        try:
            proc = psutil.Process(record["pid"])
            if abs(proc.create_time() - record["created"]) < .01 and str(ROOT) in " ".join(proc.cmdline()):
                proc.send_signal(signal.SIGTERM)
                print(f"Stopped {name} ({proc.pid})")
        except psutil.NoSuchProcess:
            pass
    STATE.unlink()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=["start", "stop", "status"])
    action = parser.parse_args().action
    if action == "start":
        start()
    elif action == "stop":
        stop()
    else:
        print(json.dumps([probe(m) for m in load_settings().models], indent=2))
