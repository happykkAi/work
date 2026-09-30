from __future__ import annotations

from pathlib import Path

import yaml


def test_fixed_runtime_routing_template_keeps_handoff_and_networks_separate() -> None:
    path = Path(__file__).parents[2] / "deploy/work/runtime-routing-template.yml"
    template = yaml.safe_load(path.read_text(encoding="utf-8"))
    services = template["services"]
    entry = services["work-entry"]

    assert entry["environment"]["WORK_ENTRY_MODE"] == "1"
    assert entry["environment"]["WORK_RUNTIME_ID"] == "work-entry"
    assert set(entry["networks"]) == {"entry-org-a-private", "entry-org-b-private"}
    assert all("docker.sock" not in volume for volume in entry.get("volumes", []))
    assert entry["environment"]["WORK_RUNTIME_MTLS_CA_FILE"]
    assert entry["environment"]["WORK_RUNTIME_MTLS_CERT_FILE"]
    assert entry["environment"]["WORK_RUNTIME_MTLS_KEY_FILE"]

    for organization in ("org-a", "org-b"):
        runtime = services[f"octop-{organization}"]
        other = "org-b" if organization == "org-a" else "org-a"
        assert runtime["environment"]["WORK_RUNTIME_ID"] == organization
        assert runtime["environment"]["WORK_ORGANIZATION_ID"] == organization
        assert runtime["environment"]["WORK_RUNTIME_ENDPOINT"] == (
            f"https://octop-{organization}:8088"
        )
        assert runtime["environment"]["WORK_RUNTIME_MTLS_CA_FILE"]
        assert runtime["environment"]["WORK_RUNTIME_MTLS_CERT_FILE"]
        assert runtime["environment"]["WORK_RUNTIME_MTLS_KEY_FILE"]
        assert runtime["environment"]["WORK_HANDOFF_SECRET_REF"] == (f"{organization}-handoff")
        assert "ports" not in runtime
        healthcheck = " ".join(runtime["healthcheck"]["test"])
        assert "socket.create_connection" in healthcheck
        assert "http://" not in healthcheck
        assert "https://" not in healthcheck
        assert runtime["networks"] == [f"entry-{organization}-private"]
        assert f"entry-{other}-private" not in runtime["networks"]
        assert f"{organization}-data:/data/.octop" in runtime["volumes"]

    assert template["networks"]["entry-org-a-private"]["internal"] is True
    assert template["networks"]["entry-org-b-private"]["internal"] is True
    assert services["octop-org-a"]["secrets"] != services["octop-org-b"]["secrets"]
