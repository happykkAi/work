"""Capabilities permanently retired from the Work replacement."""

from __future__ import annotations

import re

from octop.infra.errors import ErrorCode, OctopError

FEISHU_DISABLED_MESSAGE = "飞书相关功能已停用，历史记录保留"
_RETIRED = frozenset({"feishu", "lark", "larksuite", "pixelrag"})


def is_retired_integration(value: str | None) -> bool:
    if not value:
        return False
    tokens = re.split(r"[^a-z0-9]+", value.casefold())
    return not _RETIRED.isdisjoint(tokens)


def ensure_integration_available(value: str | None) -> None:
    if not is_retired_integration(value):
        return
    integration = "pixelrag" if "pixelrag" in (value or "").casefold() else "feishu"
    message = "PixelRAG 已永久停用" if integration == "pixelrag" else FEISHU_DISABLED_MESSAGE
    raise OctopError(
        ErrorCode.FEATURE_DISABLED,
        message,
        status=410,
        details={"integration": integration, "state": "disabled"},
    )
