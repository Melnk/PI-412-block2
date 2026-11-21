"""Verify only the dedicated development VM, without changing other labs."""
import json
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from incidentlab.config import ROOT

GUEST_CHECK = r'''
import json,os,subprocess,sqlite3,sys
result={
    "python":subprocess.check_output(["python3","--version"],text=True).strip(),
    "host_home_present":os.path.exists(sys.argv[1]),
    "agent_user":subprocess.check_output(["id","incidentlab"],text=True).strip(),
    "agent_sudo_returncode":subprocess.run(["sudo","-n","-u","incidentlab","sudo","-n","true"],capture_output=True).returncode,
    "agent_can_write_workspace":subprocess.run(["sudo","-n","-u","incidentlab","test","-w","/opt/incidentlab"]).returncode==0,
    "egress_locked":False
}
with sqlite3.connect(":memory:") as db:
    db.execute("CREATE VIRTUAL TABLE docs USING fts5(content)")
    result["fts5"]=True
print(json.dumps(result))
'''


def main():
    lima = shutil.which("limactl")
    if not lima:
        raise SystemExit("Install Lima from its official source first")
    metadata = json.loads(subprocess.check_output([lima, "list", "pi412-block2", "--json"], text=True))
    response = subprocess.check_output([lima, "shell", "pi412-block2", "python3", "-", str(Path.home())],
                                       input=GUEST_CHECK, text=True)
    guest = json.loads(response)
    config = metadata["config"]
    report = {"timestamp_utc": datetime.now(timezone.utc).isoformat(), "vm": metadata["name"],
              "vm_type": metadata["vmType"], "arch": metadata["arch"],
              "mounts": config.get("mounts", []), "port_forwards": config.get("portForwards", []),
              "guest_checks": guest,
              "scope": "Development VM prerequisites; agent workflow and egress lockdown are pending"}
    (ROOT / "results/readiness/vm.json").write_text(json.dumps(report, indent=2)+"\n")
    print(json.dumps(report, indent=2))
    assert not report["mounts"]
    assert not guest["host_home_present"]
    assert guest["agent_sudo_returncode"] != 0
    assert guest["agent_can_write_workspace"]


if __name__ == "__main__":
    main()
