from pathlib import Path


def test_agent_prompts_do_not_recommend_feishu_connections() -> None:
    root = Path(__file__).resolve().parents[3]
    paths = (
        root
        / "src/octop/infra/agents/experts/library/general-assistant/skills/octop-assistant/SKILL.md",
        root
        / "src/octop/infra/agents/subagents/library/en/engineering/engineering-feishu-integration-developer.md",
        root
        / "src/octop/infra/agents/subagents/library/zh/engineering/engineering-feishu-integration-developer.md",
    )
    combined = "\n".join(path.read_text(encoding="utf-8").casefold() for path in paths)

    assert "飞书相关功能已停用，历史记录保留" in combined
    for retired_entrypoint in ("feishu-setup", "lark-cli", "register_app", "authen/v1/authorize"):
        assert retired_entrypoint.casefold() not in combined
