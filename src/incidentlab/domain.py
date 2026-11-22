"""Contracts for the first connected, read-only incident investigation."""
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ToolName = Literal["metrics", "logs", "deployments"]
Cause = Literal["database_pool_exhaustion", "deployment_regression", "application_error", "unknown"]
CAUSE_CODES = {"database": "database_pool_exhaustion", "release": "deployment_regression",
               "application": "application_error", "unknown": "unknown"}
RunStatus = Literal["supported", "insufficient_evidence", "budget_exceeded", "error"]


class Contract(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Incident(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")
    title: str = Field(max_length=120)
    service: str = Field(max_length=80)
    description: str = Field(max_length=500)
    window_start: datetime
    window_end: datetime
    synthetic: Literal[True]

    @model_validator(mode="after")
    def valid_window(self):
        if not self.window_start.tzinfo or not self.window_end.tzinfo or self.window_start >= self.window_end:
            raise ValueError("Incident requires an ordered, timezone-aware window")
        return self


class Evidence(Contract):
    id: str = Field(pattern=r"^[a-z][a-z0-9-]{1,31}$")
    source: ToolName
    timestamp: datetime
    text: str = Field(min_length=1, max_length=500)


class EvidenceFile(Contract):
    available: bool
    records: list[Evidence] = Field(max_length=4)
    error: str | None = Field(default=None, max_length=150)


class Plan(Contract):
    action: Literal["metrics", "logs", "deployments", "analyze"]
    reason: str = Field(min_length=1, max_length=240)


class Assessment(Contract):
    cause: Cause

    @field_validator("cause", mode="before")
    @classmethod
    def normalize_code(cls, value):
        return CAUSE_CODES.get(value, value) if isinstance(value, str) else value

    @classmethod
    def llm_schema(cls):
        schema = cls.model_json_schema()
        schema["properties"]["cause"]["enum"] = list(CAUSE_CODES)
        return schema


def cause_code(cause):
    return next(code for code, value in CAUSE_CODES.items() if value == cause)


class Analysis(Assessment):
    evidence_ids: list[str] = Field(max_length=6)
    reason: str = Field(min_length=1, max_length=280)


class Review(Assessment):
    decision: Literal["accept", "revise", "insufficient"]
    reason: str = Field(min_length=1, max_length=280)


class InvestigationRequest(Contract):
    incident_id: str = Field(pattern=r"^[a-z][a-z0-9-]{2,63}$")


class Limits(Contract):
    max_tools: int = Field(default=3, ge=1, le=3)
    max_calls: int = Field(default=8, ge=1, le=12)
    max_analysis_rounds: int = Field(default=2, ge=1, le=2)
    max_reserved_output_tokens: int = Field(default=1600, ge=64, le=4096)
    timeout_seconds: float = Field(default=180, gt=0, le=600)
