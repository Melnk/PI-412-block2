"""Run the full real-LLM scenario, printing a short summary and saved path."""
import argparse
import json

from incidentlab.workflow import Workflow


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("incident_id", nargs="?", default="checkout-01")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    workflow = Workflow()
    result = workflow.run(args.incident_id)
    if args.json:
        print(json.dumps(result, indent=2, ensure_ascii=False))
    else:
        print(result["summary"])
        print(result["next_step"])
        print(json.dumps(result["stats"], ensure_ascii=False))
        print("Run:", result["run_id"], "Trace:", result["trace_id"])
        print("JSON:", workflow.runs.folder / (result["run_id"] + ".json"))
    raise SystemExit(0 if result["status"] in {"supported", "insufficient_evidence"} else 1)


if __name__ == "__main__":
    main()
