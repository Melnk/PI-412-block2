"""Bounded evidence-driven LangGraph with a different-family validator."""
import json
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from opentelemetry.trace import Status, StatusCode
from pydantic import ValidationError

from incidentlab.config import ROOT, load_settings
from incidentlab.domain import Analysis, Limits, Plan, Review, cause_code
from incidentlab.llm import LLMError, LocalLLM
from incidentlab.persistence import RunStore
from incidentlab.telemetry import CALLS, LATENCY, RUNS, TOKENS, Telemetry
from incidentlab.tools import TOOLS, IncidentStore, ToolError

TITLES = {
    "database_pool_exhaustion": "Исчерпан пул соединений с базой данных",
    "deployment_regression": "Ошибки связаны с новым релизом",
    "application_error": "Обнаружена ошибка приложения",
    "unknown": "Недостаточно данных для подтверждённой гипотезы",
}
NEXT_STEPS = {
    "database_pool_exhaustion": "Проверить длительные запросы, удержание соединений и настройки пула.",
    "deployment_regression": "Сопоставить изменение версии и конфигурации; согласовать следующий шаг с инженером.",
    "application_error": "Проверить указанный обработчик и входные данные по приведённым логам.",
    "unknown": "Получить недостающие метрики, подробный лог и историю изменений.",
}


class State(TypedDict):
    incident: dict
    evidence: list[dict]
    attempted: list[str]
    tool_errors: dict[str, str]
    action: str
    proposal: dict
    review: dict
    guard_errors: list[str]
    analysis_rounds: int
    tools_at_analysis: int
    fatal_status: str
    error: str


class BudgetExceeded(RuntimeError):
    pass


class Gateway:
    def reply(self, model, system, prompt, schema, max_tokens, timeout):
        return LocalLLM(model, timeout=timeout).json_reply(system, prompt, schema, max_tokens=max_tokens)


@dataclass
class RunContext:
    run_id: str
    started: float
    calls: list[dict] = field(default_factory=list)
    trajectory: list[dict] = field(default_factory=list)
    reserved_output: int = 0


def verify_proposal(proposal: Analysis, evidence: list[dict]) -> list[str]:
    """Structural/provenance guard, not a claim to prove semantic truth."""
    by_id = {record["id"]: record for record in evidence}
    errors = []
    if len(set(proposal.evidence_ids)) != len(proposal.evidence_ids):
        errors.append("Duplicate evidence ids")
    if any(identifier not in by_id for identifier in proposal.evidence_ids):
        errors.append("Cited evidence was not obtained by the tools")
    if proposal.cause != "unknown":
        sources = {by_id[identifier]["source"] for identifier in proposal.evidence_ids if identifier in by_id}
        if len(sources) < 2:
            errors.append("A supported hypothesis requires at least two source types")
    return errors


def accepted(state):
    return bool(state["proposal"] and state["review"] and not state["guard_errors"]
                and state["proposal"]["cause"] != "unknown"
                and state["review"]["decision"] == "accept"
                and state["review"]["cause"] == state["proposal"]["cause"])


class Workflow:
    def __init__(self, gateway=None, incidents=None, output: Path = ROOT / "results/live", settings=None,
                 limits: Limits | None = None):
        self.gateway = gateway if gateway is not None else Gateway()
        self.incidents = incidents if incidents is not None else IncidentStore()
        self.settings = settings if settings is not None else load_settings()
        self.limits = limits if limits is not None else Limits()
        self.runs = RunStore(Path(output) / "runs")
        self.telemetry = Telemetry(output)
        self.prompts = {role: (ROOT / "prompts" / (role + ".md")).read_text()
                        for role in ("planner", "analyst", "validator")}
        soul = (ROOT / "SOUL.md").read_text()
        self.prompts = {role: soul + "\n\n" + prompt for role, prompt in self.prompts.items()}
        self.prompts["planner"] += "\n" + (ROOT / "skills/investigate/SKILL.md").read_text()
        self.prompts["validator"] += "\n" + (ROOT / "skills/validate/SKILL.md").read_text()
        taxonomy = (ROOT / "runbooks/failure-modes.md").read_text()
        self.prompts["analyst"] += "\n\n" + taxonomy
        self.prompts["validator"] += "\n\n" + taxonomy

    def _event(self, ctx, kind, **fields):
        ctx.trajectory.append({"step": len(ctx.trajectory) + 1,
                               "elapsed_ms": round((time.monotonic() - ctx.started) * 1000, 2),
                               "kind": kind, **fields})

    def _remaining(self, state):
        if len(state["attempted"]) >= self.limits.max_tools:
            return []
        return [tool for tool in TOOLS if tool not in state["attempted"]]

    def _ask(self, ctx, role, data, schema, max_tokens):
        remaining_time = self.limits.timeout_seconds - (time.monotonic() - ctx.started)
        if remaining_time <= 0 or len(ctx.calls) >= self.limits.max_calls:
            raise BudgetExceeded("Run time or model-call budget exhausted")
        if ctx.reserved_output + max_tokens > self.limits.max_reserved_output_tokens:
            raise BudgetExceeded("Output-token reservation budget exhausted")
        prompt = json.dumps(data, ensure_ascii=False)
        if len(prompt) > 10000:
            raise BudgetExceeded("Input evidence exceeds the context budget")
        model = self.settings.model(self.settings.roles[role])
        call = {"role": role, "model": model.id, "family": model.family,
                "display_name": model.display_name, "weight_file": model.filename,
                "system_prompt": self.prompts[role], "input": data,
                "max_output_tokens": max_tokens}
        ctx.calls.append(call)
        ctx.reserved_output += max_tokens
        CALLS.labels(model.id, role).inc()
        with self.telemetry.span("llm." + role, **{"run.id": ctx.run_id,
                                 "gen_ai.request.model": model.id, "agent.family": model.family}) as span:
            try:
                result = self.gateway.reply(model, self.prompts[role], prompt, schema, max_tokens,
                                            min(60, remaining_time))
                call.update(result)
                return result["answer"]
            except LLMError as error:
                call["error"] = str(error)
                if getattr(error, "details", None):
                    call["failure_details"] = error.details
                    if "usage" in error.details:
                        call["usage"] = error.details["usage"]
                raise
            finally:
                for key, direction in [("prompt_tokens", "input"), ("completion_tokens", "output")]:
                    count = call.get("usage", {}).get(key)
                    if isinstance(count, int) and count >= 0:
                        span.set_attribute("gen_ai.usage." + direction + "_tokens", count)
                        TOKENS.labels(model.id, direction).inc(count)

    def _node(self, ctx, name, function):
        def wrapped(state):
            with self.telemetry.span("agent." + name, **{"run.id": ctx.run_id}) as span:
                try:
                    if time.monotonic() - ctx.started >= self.limits.timeout_seconds:
                        raise BudgetExceeded("Run deadline reached between steps")
                    update = function(state)
                    self._event(ctx, "node", node=name)
                    return update
                except (BudgetExceeded, LLMError, ValidationError) as error:
                    status = "budget_exceeded" if isinstance(error, BudgetExceeded) else "error"
                    span.set_status(Status(StatusCode.ERROR))
                    self._event(ctx, "failure", node=name, error=str(error), status=status)
                    return {"fatal_status": status, "error": str(error)}
        return wrapped

    def _build_graph(self, ctx):
        def plan(state):
            remaining = self._remaining(state)
            if not remaining:
                self._event(ctx, "plan", action="analyze", reason="All allowed sources attempted")
                return {"action": "analyze"}
            can_analyze = len(state["attempted"]) >= 2
            if state["review"] and len(state["attempted"]) == state["tools_at_analysis"]:
                can_analyze = False  # A review retry must obtain another source first.
            actions = remaining + (["analyze"] if can_analyze else [])
            schema = Plan.model_json_schema()
            schema["properties"]["action"]["enum"] = actions
            answer = Plan.model_validate(self._ask(ctx, "planner", {
                "incident": state["incident"], "untrusted_evidence": state["evidence"],
                "unavailable_tools": state["tool_errors"], "review_feedback": state["review"],
                "allowed_actions": actions,
            }, schema, 96))
            if answer.action not in actions:
                raise LLMError("Planner selected an unavailable action")
            self._event(ctx, "plan", **answer.model_dump())
            return {"action": answer.action}

        def tool(state):
            name = state["action"]
            if name not in self._remaining(state):
                raise LLMError("Tool selection violated the allowlist or call budget")
            with self.telemetry.span("tool." + name, **{"run.id": ctx.run_id}):
                try:
                    value = self.incidents.read_tool(state["incident"]["id"], name)
                    records = [record.model_dump(mode="json") for record in value.records]
                    if {r["id"] for r in records} & {r["id"] for r in state["evidence"]}:
                        raise ToolError("Evidence id collision across sources")
                    self._event(ctx, "tool", tool=name, records=len(records), available=True)
                    return {"attempted": [*state["attempted"], name],
                            "evidence": [*state["evidence"], *records]}
                except ToolError as error:
                    self._event(ctx, "tool", tool=name, available=False, error=str(error))
                    return {"attempted": [*state["attempted"], name],
                            "tool_errors": {**state["tool_errors"], name: str(error)}}

        def analyze(state):
            answer = Analysis.model_validate(self._ask(ctx, "analyst", {
                "incident": state["incident"], "untrusted_evidence": state["evidence"],
                "observed_source_types": sorted({e["source"] for e in state["evidence"]}),
                "unavailable_tools": state["tool_errors"], "previous_review": state["review"],
                "previous_guard_errors": state["guard_errors"],
            }, Analysis.llm_schema(), 224))
            self._event(ctx, "proposal", **answer.model_dump())
            return {"proposal": answer.model_dump(), "review": {},
                    "analysis_rounds": state["analysis_rounds"] + 1,
                    "tools_at_analysis": len(state["attempted"])}

        def verify(state):
            errors = verify_proposal(Analysis.model_validate(state["proposal"]), state["evidence"])
            self._event(ctx, "verification", errors=errors)
            return {"guard_errors": errors}

        def validate(state):
            answer = Review.model_validate(self._ask(ctx, "validator", {
                "incident": state["incident"], "untrusted_evidence": state["evidence"],
                "observed_source_types": sorted({e["source"] for e in state["evidence"]}),
                "proposal_to_check": {"cause": cause_code(state["proposal"]["cause"]),
                                      "evidence_ids": state["proposal"]["evidence_ids"]},
                "programmatic_guard_errors": state["guard_errors"],
                "missing_sources": self._remaining(state), "unavailable_tools": state["tool_errors"],
            }, Review.llm_schema(), 224))
            self._event(ctx, "review", **answer.model_dump())
            return {"review": answer.model_dump()}

        def after_validation(state):
            if state["fatal_status"] or accepted(state):
                return "finish"
            if state["analysis_rounds"] < self.limits.max_analysis_rounds:
                if self._remaining(state):
                    return "planner"
                if state["guard_errors"]:
                    return "analyst"
            return "finish"

        graph = StateGraph(State)
        for name, fn in [("planner", plan), ("tool", tool), ("analyst", analyze),
                         ("verify", verify), ("validator", validate)]:
            graph.add_node(name, self._node(ctx, name, fn))
        graph.add_node("finish", lambda state: {})
        graph.add_edge(START, "planner")
        graph.add_conditional_edges("planner", lambda s: "finish" if s["fatal_status"] else
                                    ("analyst" if s["action"] == "analyze" else "tool"), ["finish", "analyst", "tool"])
        graph.add_conditional_edges("tool", lambda s: "finish" if s["fatal_status"] else "planner", ["finish", "planner"])
        graph.add_conditional_edges("analyst", lambda s: "finish" if s["fatal_status"] else "verify", ["finish", "verify"])
        graph.add_conditional_edges("verify", lambda s: "finish" if s["fatal_status"] else "validator", ["finish", "validator"])
        graph.add_conditional_edges("validator", after_validation, ["finish", "planner", "analyst"])
        graph.add_edge("finish", END)
        return graph.compile()

    def run(self, incident_id):
        incident = self.incidents.incident(incident_id)
        ctx = RunContext(uuid4().hex, time.monotonic())
        initial: State = {
            "incident": incident.model_dump(mode="json"), "evidence": [], "attempted": [],
            "tool_errors": {}, "action": "", "proposal": {}, "review": {}, "guard_errors": [],
            "analysis_rounds": 0, "tools_at_analysis": 0, "fatal_status": "", "error": "",
        }
        with self.telemetry.span("investigation", **{"run.id": ctx.run_id, "incident.id": incident_id}) as root:
            trace_id = f"{root.get_span_context().trace_id:032x}"
            state = self._build_graph(ctx).invoke(initial, {"recursion_limit": 40})
            status = state["fatal_status"] or ("supported" if accepted(state) else "insufficient_evidence")
            cause = state["proposal"]["cause"] if status == "supported" else "unknown"
            summary = TITLES[cause]
            if status == "error":
                summary = "Расследование прервано из-за ошибки модели или её ответа"
            elif status == "budget_exceeded":
                summary = "Исследование остановлено по ограничению времени или запросов"
            next_step = NEXT_STEPS[cause]
            if status == "error":
                next_step = "Проверить доступность локальных моделей и исходный ответ в trace, затем повторить запуск."
            elif status == "budget_exceeded":
                next_step = "Проверить расход бюджета; сузить задачу или обоснованно изменить лимит."
            elapsed = round(time.monotonic() - ctx.started, 3)
            result = {
                "run_id": ctx.run_id, "trace_id": trace_id,
                "created_at": datetime.now(timezone.utc).isoformat(), "incident": initial["incident"],
                "engine": self.settings.engine, "roles": self.settings.roles,
                "status": status, "cause": cause, "summary": summary, "next_step": next_step,
                "citations": [e for e in state["evidence"]
                              if status == "supported" and e["id"] in state["proposal"]["evidence_ids"]],
                "evidence": state["evidence"], "source_failures": state["tool_errors"],
                "proposal": state["proposal"], "review": state["review"], "guard_errors": state["guard_errors"],
                "error": state["error"], "trajectory": ctx.trajectory, "model_calls": ctx.calls,
                "limits": self.limits.model_dump(), "stats": {
                    "elapsed_seconds": elapsed, "tool_calls": len(state["attempted"]),
                    "llm_calls": len(ctx.calls), "analysis_rounds": state["analysis_rounds"],
                    "reserved_output_tokens": ctx.reserved_output,
                    "input_tokens": sum(c.get("usage", {}).get("prompt_tokens", 0) for c in ctx.calls),
                    "output_tokens": sum(c.get("usage", {}).get("completion_tokens", 0) for c in ctx.calls),
                    "token_usage_complete": all("usage" in c for c in ctx.calls),
                },
            }
            root.set_attribute("investigation.status", status)
            if state["fatal_status"]:
                root.set_status(Status(StatusCode.ERROR))
            RUNS.labels(status).inc()
            LATENCY.observe(elapsed)
        result["spans"] = self.telemetry.spans(trace_id)
        self.runs.save(result)
        return result
