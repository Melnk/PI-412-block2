"""Actual OpenTelemetry spans exported locally, without an external account."""
import json
import threading
from contextlib import contextmanager
from pathlib import Path

from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor, SpanExporter, SpanExportResult
from opentelemetry.trace import Status, StatusCode
from prometheus_client import Counter, Histogram

RUNS = Counter("incidentlab_investigations_total", "Completed investigations", ["status"])
LATENCY = Histogram("incidentlab_investigation_seconds", "Investigation wall time",
                    buckets=(1, 5, 10, 20, 40, 60, 120, 180, 300))
CALLS = Counter("incidentlab_llm_calls_total", "Attempted LLM calls", ["model", "role"])
TOKENS = Counter("incidentlab_llm_tokens_total", "Reported LLM tokens", ["model", "direction"])


class JSONLExporter(SpanExporter):
    def __init__(self, path):
        self.path = Path(path)
        self.lock = threading.Lock()

    def export(self, spans):
        with self.lock, self.path.open("a") as output:
            for span in spans:
                ctx = span.get_span_context()
                output.write(json.dumps({
                    "trace_id": f"{ctx.trace_id:032x}", "span_id": f"{ctx.span_id:016x}",
                    "parent_id": f"{span.parent.span_id:016x}" if span.parent else None,
                    "name": span.name, "start_ns": span.start_time,
                    "duration_ms": round((span.end_time - span.start_time) / 1e6, 2),
                    "status": span.status.status_code.name, "attributes": dict(span.attributes),
                }) + "\n")
        return SpanExportResult.SUCCESS


class Telemetry:
    def __init__(self, directory):
        directory = Path(directory)
        directory.mkdir(parents=True, exist_ok=True)
        self.path = directory / "spans.jsonl"
        # Keep a private provider; do not replace another app's global tracer.
        self.provider = TracerProvider(resource=Resource.create({"service.name": "incidentlab"}))
        self.provider.add_span_processor(SimpleSpanProcessor(JSONLExporter(self.path)))
        self.tracer = self.provider.get_tracer("incidentlab.workflow", "0.2.0")

    @contextmanager
    def span(self, name, **attributes):
        with self.tracer.start_as_current_span(name, attributes=attributes) as span:
            try:
                yield span
            except Exception:
                span.set_status(Status(StatusCode.ERROR))
                raise

    def spans(self, trace_id):
        if not self.path.exists():
            return []
        return [row for line in self.path.read_text().splitlines()
                if (row := json.loads(line))["trace_id"] == trace_id]
