import json

from incidentlab.config import ROOT, load_settings


def test_asset_manifests_match_configured_filenames():
    manifest = json.loads((ROOT / "config/model-manifest.json").read_text())
    assert {m['filename'] for m in manifest} == {m.filename for m in load_settings().models}
    for model in manifest:
        assert len(model['sha256']) == 64
        assert len(model['revision']) == 40
        assert model['repository'].startswith(('ggml-org/', 'LiquidAI/'))


def test_metrics_exposes_real_process_memory():
    from fastapi.testclient import TestClient

    from incidentlab.app import app
    response = TestClient(app).get('/metrics')
    assert response.status_code == 200
    line = next(line for line in response.text.splitlines() if line.startswith('incidentlab_process_memory_bytes '))
    assert float(line.split()[-1]) > 0
