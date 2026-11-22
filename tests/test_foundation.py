import json

import httpx
import pytest
from fastapi.testclient import TestClient

from incidentlab.app import app
from incidentlab.config import ROOT, Settings, load_settings
from incidentlab.llm import LLMError, LocalLLM


def config_data():
    return json.loads((ROOT / "config/models.json").read_text())


def test_config_uses_three_distinct_families():
    settings = load_settings()
    assert len({model.family for model in settings.models}) == 3


def test_independent_validator_is_required():
    data = config_data()
    data["roles"]["validator"] = data["roles"]["analyst"]
    with pytest.raises(ValueError, match="different model families"):
        Settings.model_validate(data)


@pytest.mark.parametrize("url", ["https://example.com", "http://192.168.0.1:8121",
                               "http://127.0.0.1:8121/secret", "http://user:pass@localhost:8121"])
def test_remote_and_credential_endpoints_rejected(url):
    data = config_data()
    data["models"][0]["base_url"] = url
    with pytest.raises(ValueError):
        Settings.model_validate(data)


@pytest.mark.parametrize("filename", ["../secret.gguf", "/tmp/model.gguf", "sub\\model.gguf", "model.py"])
def test_weight_path_must_stay_in_models(filename):
    data = config_data()
    data["models"][0]["filename"] = filename
    with pytest.raises(ValueError):
        Settings.model_validate(data)


def test_duplicate_model_ids_rejected():
    data = config_data()
    data["models"][1]["id"] = data["models"][0]["id"]
    with pytest.raises(ValueError, match="unique"):
        Settings.model_validate(data)


def test_unknown_role_model_rejected():
    data = config_data()
    data["roles"]["planner"] = "missing"
    with pytest.raises(ValueError):
        Settings.model_validate(data)


def test_transport_enforces_budget_and_keeps_model_metadata():
    def respond(request):
        payload = json.loads(request.content)
        assert payload["max_tokens"] == 32
        assert payload["temperature"] == 0
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {
            "content": '{"answer":"checkout"}'}}], "usage": {"completion_tokens": 8}})
    llm = LocalLLM(load_settings().model("qwen"), transport=httpx.MockTransport(respond))
    answer = llm.json_reply("Return JSON", "service?", {"type": "object"}, max_tokens=32)
    assert answer["answer"]["answer"] == "checkout"
    assert answer["family"] == "Qwen"
    assert answer["usage"]["completion_tokens"] == 8
    with pytest.raises(ValueError):
        llm.json_reply("", "", {}, max_tokens=100000)


@pytest.mark.parametrize("body", ["truncated", "[]"])
def test_invalid_model_output_does_not_pass_as_success(body):
    def respond(_):
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": body}}]})
    with pytest.raises(LLMError) as exc:
        LocalLLM(load_settings().model("qwen"), transport=httpx.MockTransport(respond)).json_reply("", "", {})
    assert exc.value.details["raw_output"] == body


def test_truncated_generation_rejected():
    def respond(_):
        return httpx.Response(200, json={"choices": [{"finish_reason": "length", "message": {"content": '{}'}}]})
    with pytest.raises(LLMError, match="budget"):
        LocalLLM(load_settings().model("qwen"), transport=httpx.MockTransport(respond)).json_reply("", "", {})


def test_health_reports_connected_scenario():
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["workflow_implemented"] is True
    assert response.json()["stage"] == "first-connected-scenario"


def test_models_route_exposes_configuration():
    data = TestClient(app).get("/models").json()
    assert len(data["models"]) >= 3
    assert data["roles"]["analyst"] != data["roles"]["validator"]
