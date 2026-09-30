from __future__ import annotations

from pathlib import Path

import yaml


def test_runtime_template_keeps_organization_resources_separate() -> None:
    template_path = Path(__file__).parents[2] / "deploy/work/runtime-template.yml"
    template = yaml.safe_load(template_path.read_text(encoding="utf-8"))
    services = template["services"]

    for organization in ("org-a", "org-b"):
        runtime = services[f"octop-{organization}"]
        database = services[f"postgres-{organization}"]
        private_network = f"{organization}-private"

        assert runtime["environment"]["WORK_ORGANIZATION_ID"] == organization
        assert runtime["environment"]["WORK_RUNTIME_ID"] == organization
        assert runtime["environment"]["WORK_VOLUME_ID"] == f"{organization}-data"
        assert runtime["environment"]["WORK_SECRET_REF"] == (f"{organization}-octop-database-url")
        assert runtime["environment"]["WORK_RUNTIME_ENDPOINT"] == (
            f"https://octop-{organization}:8088"
        )
        assert runtime["environment"]["WORK_HANDOFF_SECRET_REF"] == (f"{organization}-handoff")
        assert runtime["environment"]["WORK_RUNTIME_SECRETS_DIR"] == "/run/secrets"
        assert runtime["environment"]["WORK_RUNTIME_MTLS_CA_FILE"] == (
            "/run/secrets/work-runtime-ca"
        )
        assert runtime["environment"]["WORK_RUNTIME_MTLS_CERT_FILE"] == (
            f"/run/secrets/{organization}-server-cert"
        )
        assert runtime["environment"]["WORK_RUNTIME_MTLS_KEY_FILE"] == (
            f"/run/secrets/{organization}-server-key"
        )
        secret_sources = {item["source"] for item in runtime["secrets"]}
        assert {
            f"{organization}-handoff",
            "work-runtime-ca",
            f"{organization}-server-cert",
            f"{organization}-server-key",
        } <= secret_sources
        assert "ports" not in runtime
        healthcheck = " ".join(runtime["healthcheck"]["test"])
        assert "socket.create_connection" in healthcheck
        assert "http://" not in healthcheck
        assert "https://" not in healthcheck
        assert f"{organization}-data:/data/.octop" in runtime["volumes"]
        assert f"{organization}-postgres-data:/var/lib/postgresql/data" in database["volumes"]
        assert runtime["networks"] == [private_network]
        assert database["networks"] == [private_network]
        assert template["networks"][private_network]["internal"] is True

    assert services["octop-org-a"]["volumes"] != services["octop-org-b"]["volumes"]
    assert services["postgres-org-a"]["volumes"] != services["postgres-org-b"]["volumes"]
