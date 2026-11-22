import json
import shutil

import pytest
from fastapi.testclient import TestClient

from incidentlab.app import RUN_LOCK, app, get_workflow
from incidentlab.config import ROOT
from incidentlab.domain import Analysis, Limits
from incidentlab.llm import LLMError
from incidentlab.tools import IncidentStore, ToolError
from incidentlab.workflow import Workflow, verify_proposal


class ScriptedGateway:
    """Unit-test double. Its outputs are not model experiment results."""
    def __init__(self, order=("metrics", "logs", "deployments"), reject_first=False,
                 invalid_citation=False, fail=False):
        self.order = order
        self.reject_first = reject_first
        self.invalid_citation = invalid_citation
        self.fail = fail
        self.reviews = 0

    def reply(self, model, system, prompt, schema, max_tokens, timeout):
        if self.fail:
            raise LLMError("Test model is offline")
        data = json.loads(prompt)
        if "allowed_actions" in data:
            actions = data["allowed_actions"]
            action = "analyze" if "analyze" in actions else next(a for a in self.order if a in actions)
            answer = {"action": action, "reason": "Collect another independent source"}
        elif "proposal_to_check" in data:
            self.reviews += 1
            proposal = Analysis.model_validate({**data["proposal_to_check"], "reason": "test"}).model_dump()
            rejected = self.reject_first and self.reviews == 1
            answer = {"decision": "revise" if rejected else "accept", "cause": proposal["cause"],
                      "reason": "Need release history" if rejected else "Independent sources agree"}
            if data["programmatic_guard_errors"] or proposal["cause"] == "unknown":
                answer.update(decision="insufficient", cause="unknown")
        else:
            evidence = data["untrusted_evidence"]
            sources = {e["source"] for e in evidence}
            answer = {"cause": "database_pool_exhaustion" if len(sources) >= 2 else "unknown",
                      "evidence_ids": [e["id"] for e in evidence][:4], "reason": "Pool saturation and timeout"}
            if self.invalid_citation:
                answer["evidence_ids"] = ["invented"]
        return {"answer": answer, "raw_output": json.dumps(answer), "usage": {
            "prompt_tokens": 20, "completion_tokens": 15}, "latency_ms": 1}


def engine(tmp_path, **kwargs):
    return Workflow(gateway=ScriptedGateway(**kwargs), output=tmp_path)


def test_connected_graph_has_real_trace_and_persistence(tmp_path):
    workflow = engine(tmp_path)
    result = workflow.run("checkout-01")
    assert result["status"] == "supported"
    assert result["cause"] == "database_pool_exhaustion"
    assert {c["role"] for c in result["model_calls"]} == {"planner", "analyst", "validator"}
    analyst = next(c for c in result["model_calls"] if c["role"] == "analyst")
    validator = next(c for c in result["model_calls"] if c["role"] == "validator")
    assert analyst["family"] != validator["family"]
    assert all(span["trace_id"] == result["trace_id"] for span in result["spans"])
    root = next(span for span in result["spans"] if span["name"] == "investigation")
    assert root["parent_id"] is None
    assert any(span["parent_id"] == root["span_id"] for span in result["spans"])
    assert workflow.runs.read(result["run_id"]) == result
    assert result["stats"]["tool_calls"] == 2
    assert all("expected_cause" not in json.dumps(call) for call in result["model_calls"])


def test_rejected_proposal_routes_to_new_tool_and_second_analysis(tmp_path):
    result = engine(tmp_path, reject_first=True).run("checkout-01")
    assert result["status"] == "supported"
    assert result["stats"]["analysis_rounds"] == 2
    assert result["stats"]["tool_calls"] == 3
    events = result["trajectory"]
    review = next(i for i, event in enumerate(events) if event["kind"] == "review")
    assert any(e["kind"] == "tool" and e["tool"] == "deployments" for e in events[review+1:])


def test_tool_choice_is_not_a_fixed_order(tmp_path):
    result = engine(tmp_path, order=("logs", "metrics", "deployments")).run("checkout-01")
    assert next(e for e in result["trajectory"] if e["kind"] == "tool")["tool"] == "logs"


def test_nonexistent_citations_can_never_be_accepted(tmp_path):
    result = engine(tmp_path, invalid_citation=True).run("checkout-01")
    assert result["status"] == "insufficient_evidence"
    assert result["cause"] == "unknown"
    assert result["guard_errors"]
    assert not result["citations"]
    assert result["stats"]["analysis_rounds"] <= 2


def test_accept_word_cannot_override_disagreement_between_models(tmp_path):
    class DisagreeingGateway(ScriptedGateway):
        def reply(self, *args, **kwargs):
            result = super().reply(*args, **kwargs)
            if "decision" in result["answer"]:
                result["answer"].update(cause="application_error", decision="accept")
            return result

    result = Workflow(gateway=DisagreeingGateway(), output=tmp_path).run("checkout-01")
    assert result["status"] == "insufficient_evidence"
    assert result["cause"] == "unknown"
    assert not result["citations"]


def test_missing_evidence_and_failed_source_remain_unknown(tmp_path):
    result = engine(tmp_path).run("checkout-03")
    assert result["status"] == "insufficient_evidence"
    assert result["cause"] == "unknown"
    assert "deployments" in result["source_failures"]


def test_llm_outage_is_not_mislabeled_insufficient_evidence(tmp_path):
    result = engine(tmp_path, fail=True).run("checkout-01")
    assert result["status"] == "error"
    assert result["error"]
    assert result["stats"]["llm_calls"] == 1
    assert any(span["status"] == "ERROR" for span in result["spans"])


def test_call_budget_stops_before_an_extra_model_request(tmp_path):
    workflow = Workflow(gateway=ScriptedGateway(), output=tmp_path, limits=Limits(max_calls=1))
    result = workflow.run("checkout-01")
    assert result["status"] == "budget_exceeded"
    assert result["stats"]["llm_calls"] == 1
    assert len(result["model_calls"]) == 1


def test_output_reservation_budget_blocks_before_call(tmp_path):
    workflow = Workflow(gateway=ScriptedGateway(), output=tmp_path,
                        limits=Limits(max_reserved_output_tokens=64))
    result = workflow.run("checkout-01")
    assert result["status"] == "budget_exceeded"
    assert not result["model_calls"]


def test_deadline_stops_before_a_model_request(tmp_path):
    workflow = Workflow(gateway=ScriptedGateway(), output=tmp_path, limits=Limits(timeout_seconds=1e-9))
    result = workflow.run("checkout-01")
    assert result["status"] == "budget_exceeded"
    assert not result["model_calls"]


def test_short_model_codes_normalize_without_changing_meaning():
    assert Analysis(cause="database", evidence_ids=["m01", "l01"], reason="test").cause == "database_pool_exhaustion"
    with pytest.raises(ValueError):
        Analysis(cause=["database"], evidence_ids=[], reason="test")


def test_injected_log_remains_data_and_tools_stay_read_only(tmp_path):
    result = engine(tmp_path).run("checkout-04")
    assert any("Ignore all previous" in r["text"] for r in result["evidence"])
    assert {e["tool"] for e in result["trajectory"] if e["kind"] == "tool"} <= {"metrics", "logs", "deployments"}
    assert result["cause"] == "database_pool_exhaustion"


@pytest.mark.parametrize("identifier", ["../evals", "/etc", "checkout-01/../checkout-02"])
def test_tool_paths_cannot_escape_fixture_directory(identifier):
    with pytest.raises(ToolError):
        IncidentStore().incident(identifier)


def test_fixture_symlink_cannot_read_outside_allowlist(tmp_path):
    store = tmp_path / "incidents"
    store.mkdir()
    target = tmp_path / "outside"
    target.mkdir()
    (store / "checkout-01").symlink_to(target, target_is_directory=True)
    with pytest.raises(ToolError):
        IncidentStore(store).incident("checkout-01")


def test_tool_refuses_wrong_provenance(tmp_path):
    folder = tmp_path / "incidents/checkout-01"
    folder.mkdir(parents=True)
    shutil.copy2(ROOT / "fixtures/incidents/checkout-01/incident.json", folder / "incident.json")
    data = json.loads((ROOT / "fixtures/incidents/checkout-01/metrics.json").read_text())
    data["records"][0]["source"] = "logs"
    (folder / "metrics.json").write_text(json.dumps(data))
    with pytest.raises(ToolError, match="provenance"):
        IncidentStore(tmp_path / "incidents").read_tool("checkout-01", "metrics")


def test_guard_requires_two_independent_source_types():
    proposal = Analysis(cause="database_pool_exhaustion", evidence_ids=["l01", "l02"], reason="fake")
    assert verify_proposal(proposal, [{"id": "l01", "source": "logs"}, {"id": "l02", "source": "logs"}])


def test_api_runs_and_retrieves_a_complete_investigation(tmp_path):
    workflow = engine(tmp_path)
    app.dependency_overrides[get_workflow] = lambda: workflow
    try:
        client = TestClient(app)
        assert len(client.get("/incidents").json()) == 5
        response = client.post("/investigations", json={"incident_id": "checkout-01"})
        assert response.status_code == 200
        result = response.json()
        assert result["status"] == "supported"
        assert client.get("/investigations/" + result["run_id"]).json() == result
        assert client.post("/investigations", json={"incident_id": "../evals"}).status_code == 422
        assert client.post("/investigations", json={"incident_id": "not-present"}).status_code == 404
        assert client.get("/investigations/not-a-uuid").status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_busy_api_does_not_start_a_parallel_investigation(tmp_path):
    app.dependency_overrides[get_workflow] = lambda: engine(tmp_path)
    RUN_LOCK.acquire()
    try:
        assert TestClient(app).post("/investigations", json={"incident_id": "checkout-01"}).status_code == 429
    finally:
        RUN_LOCK.release()
        app.dependency_overrides.clear()


def test_model_outage_api_exposes_saved_failed_run(tmp_path):
    workflow = engine(tmp_path, fail=True)
    app.dependency_overrides[get_workflow] = lambda: workflow
    try:
        client = TestClient(app)
        response = client.post("/investigations", json={"incident_id": "checkout-01"})
        assert response.status_code == 503
        assert client.get("/investigations/" + response.json()["run_id"]).status_code == 200
    finally:
        app.dependency_overrides.clear()


def test_ui_and_static_assets_are_served_without_remote_dependencies():
    client = TestClient(app)
    response = client.get("/")
    assert response.status_code == 200
    assert "IncidentLab" in response.text
    assert "default-src 'self'" in response.headers["Content-Security-Policy"]
    assert client.get("/static/app.js").status_code == 200
    assert client.get("/static/style.css").status_code == 200
