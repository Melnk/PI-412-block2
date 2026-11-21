"""Small transport adapter; model output is parsed and validated by callers."""
import json
import time

import httpx

from incidentlab.config import LocalModel


class LLMError(RuntimeError):
    pass


class LocalLLM:
    def __init__(self, model: LocalModel, timeout: float = 180, transport=None):
        self.model = model
        self.timeout = timeout
        self.transport = transport

    def json_reply(self, system: str, prompt: str, schema: dict, max_tokens: int = 160) -> dict:
        if not 1 <= max_tokens <= 1024:
            raise ValueError("Token budget must be between 1 and 1024")
        payload = {
            "model": self.model.id,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": prompt}],
            "temperature": 0, "seed": 42, "max_tokens": max_tokens,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {"type": "json_schema", "json_schema": {
                "name": "answer", "strict": True, "schema": schema}},
        }
        started = time.perf_counter()
        try:
            with httpx.Client(timeout=self.timeout, transport=self.transport, trust_env=False) as client:
                response = client.post(self.model.base_url + "/v1/chat/completions", json=payload)
                response.raise_for_status()
                raw = response.json()
            choice = raw["choices"][0]
            if choice.get("finish_reason") == "length":
                raise LLMError("Model response exhausted its output budget")
            content = choice["message"]["content"]
            parsed = json.loads(content)
            if not isinstance(parsed, dict):
                raise LLMError("Expected a JSON object")
            return {"model": self.model.id, "family": self.model.family, "answer": parsed,
                    "raw_output": content, "usage": raw.get("usage", {}),
                    "latency_ms": round((time.perf_counter() - started) * 1000, 2)}
        except LLMError:
            raise
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as error:
            raise LLMError(f"Local model {self.model.id} failed: {type(error).__name__}") from error


def probe(model: LocalModel, timeout=2.0) -> dict:
    started = time.perf_counter()
    try:
        with httpx.Client(timeout=timeout, trust_env=False) as client:
            response = client.get(model.base_url + "/health")
            response.raise_for_status()
            body = response.json()
        return {"id": model.id, "ready": body.get("status") == "ok",
                "latency_ms": round((time.perf_counter() - started)*1000, 2)}
    except (httpx.HTTPError, ValueError):
        return {"id": model.id, "ready": False}
