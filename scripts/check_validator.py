"""Real critic regression: distinguish correct and deliberately incorrect proposals.

A tiny development check, not a held-out benchmark. Expected decisions never enter the prompt.
"""
import json
from datetime import datetime, timezone
from uuid import uuid4

from incidentlab.config import ROOT
from incidentlab.domain import Review
from incidentlab.llm import LLMError, LocalLLM
from incidentlab.workflow import Workflow


def main():
    workflow = Workflow()
    model = workflow.settings.model(workflow.settings.roles["validator"])
    incident = workflow.incidents.incident("checkout-01").model_dump(mode="json")
    evidence = [record.model_dump(mode="json") for tool in ("metrics", "logs")
                for record in workflow.incidents.read_tool(incident["id"], tool).records]
    output = ROOT / "results/validator"
    output.mkdir(parents=True, exist_ok=True)
    path = output / (datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid4().hex[:6] + ".json")
    rows = []
    for proposed_cause, expected_decision in [("database", "accept"), ("release", "revise")]:
        data = {"incident": incident, "untrusted_evidence": evidence,
                "observed_source_types": ["logs", "metrics"],
                "proposal_to_check": {"cause": proposed_cause, "evidence_ids": [e["id"] for e in evidence]},
                "programmatic_guard_errors": [], "missing_sources": ["deployments"], "unavailable_tools": {}}
        row = {"model": model.model_dump(), "system_prompt": workflow.prompts["validator"], "input": data,
               "expected_cause": "database_pool_exhaustion", "expected_decision": expected_decision}
        try:
            result = LocalLLM(model, timeout=60).json_reply(workflow.prompts["validator"],
                                                          json.dumps(data, ensure_ascii=False),
                                                          Review.llm_schema(), max_tokens=224)
            row.update(result)
            review = Review.model_validate(result["answer"])
            row["passed"] = review.cause == row["expected_cause"] and review.decision == expected_decision
        except (LLMError, ValueError) as error:
            row.update(error=str(error), passed=False)
            if isinstance(error, LLMError):
                row["failure_details"] = error.details
        rows.append(row)
        path.write_text(json.dumps({"scope": "Two synthetic critic development regressions", "runs": rows},
                                   ensure_ascii=False, indent=2) + "\n")
        print(json.dumps({k: row.get(k) for k in ["expected_decision", "answer", "passed", "error"]}), flush=True)
    print("Saved:", path)
    raise SystemExit(0 if all(row["passed"] for row in rows) else 1)


if __name__ == "__main__":
    main()
