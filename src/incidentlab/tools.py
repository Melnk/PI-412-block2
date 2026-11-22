"""Allowlisted fixture reads. Neither an LLM path nor executable tool exists."""
import json
import re
from pathlib import Path

from incidentlab.config import ROOT
from incidentlab.domain import EvidenceFile, Incident, ToolName

TOOLS = ("metrics", "logs", "deployments")


class ToolError(RuntimeError):
    pass


class IncidentStore:
    def __init__(self, folder: Path = ROOT / "fixtures/incidents"):
        self.folder = folder.resolve()

    def _path(self, incident_id: str, filename: str) -> Path:
        if not re.fullmatch(r"[a-z][a-z0-9-]{2,63}", incident_id):
            raise ToolError("Invalid incident identifier")
        path = (self.folder / incident_id / filename).resolve()
        if not path.is_relative_to(self.folder):
            raise ToolError("Source escapes the allowed fixture directory")
        return path

    def _read(self, path):
        if path.stat().st_size > 16384:
            raise ToolError("Evidence file exceeds the input size limit")
        return json.loads(path.read_text())

    def incident(self, incident_id: str) -> Incident:
        value = Incident.model_validate(self._read(self._path(incident_id, "incident.json")))
        if value.id != incident_id:
            raise ToolError("Incident id does not match its directory")
        return value

    def list_incidents(self) -> list[Incident]:
        return [self.incident(path.name) for path in sorted(self.folder.iterdir()) if path.is_dir()]

    def read_tool(self, incident_id: str, tool: ToolName) -> EvidenceFile:
        if tool not in TOOLS:
            raise ToolError("Tool is not allowlisted")
        try:
            incident = self.incident(incident_id)
            value = EvidenceFile.model_validate(self._read(self._path(incident_id, tool + ".json")))
            if not value.available:
                raise ToolError(value.error or "Source unavailable")
            identifiers = set()
            for record in value.records:
                if record.source != tool or record.id in identifiers:
                    raise ToolError("Invalid evidence provenance or duplicate id")
                if not record.timestamp.tzinfo or not incident.window_start <= record.timestamp <= incident.window_end:
                    raise ToolError("Evidence is outside the incident window")
                identifiers.add(record.id)
            return value
        except (OSError, ValueError) as error:
            raise ToolError(f"Source could not be read: {type(error).__name__}") from error
