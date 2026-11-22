import json
import re
from pathlib import Path


class RunStore:
    def __init__(self, folder):
        self.folder = Path(folder)
        self.folder.mkdir(parents=True, exist_ok=True)

    def save(self, result):
        path = self._path(result["run_id"])
        temporary = path.with_suffix(".tmp")
        temporary.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
        temporary.replace(path)

    def _path(self, run_id):
        if not re.fullmatch(r"[a-f0-9]{32}", run_id):
            raise ValueError("Invalid run identifier")
        return self.folder / (run_id + ".json")

    def read(self, run_id):
        return json.loads(self._path(run_id).read_text())
