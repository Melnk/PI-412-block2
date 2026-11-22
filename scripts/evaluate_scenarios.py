"""Real integration scenarios with manually specified expected answers.

This small development set is not a held-out intelligence benchmark.
Full raw runs, including errors, are written before checking their outcomes.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from incidentlab.config import ROOT
from incidentlab.workflow import Workflow


def main():
    source = json.loads((ROOT / "evals/scenarios.json").read_text())
    evaluation_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6]
    output = ROOT / "results/scenarios" / evaluation_id
    output.mkdir(parents=True, exist_ok=True)
    workflow = Workflow()
    rows = []
    for case in source["cases"]:
        result = workflow.run(case["incident_id"])
        (output / (case["incident_id"] + ".json")).write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        row = {**case, "actual_cause": result["cause"], "actual_status": result["status"],
               "passed": result["cause"] == case["expected_cause"] and result["status"] == case["expected_status"],
               "run_id": result["run_id"], "trace_id": result["trace_id"], "stats": result["stats"]}
        rows.append(row)
        (output / "summary.json").write_text(json.dumps({"evaluation_id": evaluation_id,
                                                       "scope": source["scope"], "cases": rows}, indent=2) + "\n")
        print(json.dumps(row, ensure_ascii=False), flush=True)
    raise SystemExit(0 if all(row["passed"] for row in rows) else 1)


if __name__ == "__main__":
    main()
