"""Real readiness checks, not the final intelligence/hallucination benchmark."""
import json
import platform
from datetime import datetime, timezone

from pydantic import BaseModel, ConfigDict

from incidentlab.config import ROOT, load_settings
from incidentlab.llm import LLMError, LocalLLM


class Answer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    answer: str


CASES = [
    {"id": "extract", "prompt": "Read this data: service=checkout, errors=17. Return only the service name in answer.", "expected": "checkout"},
    {"id": "evidence", "prompt": "Given only: CPU=20%, database connections=100/100, log=database connection timeout. Choose the strongest supported issue: database or CPU. Return database or CPU in answer.", "expected": "database"},
    {"id": "abstain", "prompt": "The only evidence is 'the API failed'. What is the exact root cause? If evidence is insufficient, put unknown in answer. Do not invent details.", "expected": "unknown"},
]


def main():
    rows = []
    for model in load_settings().models:
        for case in CASES:
            row = {"model": model.id, "family": model.family, "case": case["id"],
                   "prompt": case["prompt"], "expected": case["expected"]}
            try:
                result = LocalLLM(model).json_reply("Follow the request. Use only the supplied facts. Return the required JSON object.",
                                                   case["prompt"], Answer.model_json_schema())
                parsed = Answer.model_validate(result["answer"])
                row.update(result)
                row["passed"] = parsed.answer.strip().lower() == case["expected"].lower()
            except (LLMError, ValueError) as error:
                row.update(passed=False, error=str(error))
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in ["model", "case", "passed", "latency_ms", "answer", "error"]}), flush=True)
    output = {"scope": "Development readiness only; 3 hand-written cases per model, no intelligence ranking claims",
              "timestamp_utc": datetime.now(timezone.utc).isoformat(), "platform": platform.platform(), "runs": rows}
    path = ROOT / "results/readiness/llm-smoke.json"
    path.write_text(json.dumps(output, indent=2, ensure_ascii=False)+"\n")
    raise SystemExit(0 if all(row["passed"] for row in rows) else 1)


if __name__ == "__main__":
    main()
