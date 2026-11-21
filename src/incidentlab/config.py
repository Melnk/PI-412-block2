import json
from pathlib import Path
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

ROOT = Path(__file__).resolve().parents[2]


class LocalModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    id: str = Field(pattern=r"^[a-z][a-z0-9_-]*$")
    family: str = Field(min_length=1)
    display_name: str
    filename: str
    base_url: str

    @field_validator("filename")
    @classmethod
    def filename_only(cls, value):
        if "/" in value or "\\" in value or not value.endswith(".gguf"):
            raise ValueError("Use a GGUF filename without directory components")
        return value

    @field_validator("base_url")
    @classmethod
    def loopback_only(cls, value):
        url = urlsplit(value)
        if (url.scheme != "http" or url.hostname not in {"127.0.0.1", "localhost", "::1"}
                or url.username or url.password or url.path or url.query or url.fragment or not url.port):
            raise ValueError("Model endpoint must be a loopback HTTP origin with an explicit port")
        return value


class Settings(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    engine: str
    context_tokens: int = Field(ge=512, le=32768)
    threads: int = Field(ge=1, le=12)
    models: tuple[LocalModel, ...] = Field(min_length=3)
    roles: dict[str, str]

    @model_validator(mode="after")
    def validate_roles(self):
        by_id = {m.id: m for m in self.models}
        if len(by_id) != len(self.models):
            raise ValueError("Model ids must be unique")
        if len({m.base_url for m in self.models}) != len(self.models):
            raise ValueError("Each model needs its own endpoint")
        if set(self.roles) != {"planner", "analyst", "validator"}:
            raise ValueError("Configure planner, analyst and validator roles")
        if not set(self.roles.values()).issubset(by_id):
            raise ValueError("Every role must reference a configured model")
        if by_id[self.roles['analyst']].family == by_id[self.roles['validator']].family:
            raise ValueError("Analyst and validator must use different model families")
        return self

    def model(self, identifier: str) -> LocalModel:
        for model in self.models:
            if model.id == identifier:
                return model
        raise KeyError(identifier)


def load_settings(path: Path = ROOT / "config/models.json") -> Settings:
    return Settings.model_validate(json.loads(path.read_text()))
