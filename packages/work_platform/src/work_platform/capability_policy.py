"""Fail-closed gate for Work external capabilities."""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import TypeVar

from work_platform.runtime_context import ExecutionContext

T = TypeVar("T")
_RETIRED = re.compile(r"(?<![a-z0-9])(feishu|lark|larksuite|pixelrag)(?![a-z0-9])")


class CapabilityDenied(PermissionError):
    pass


class PolicyUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class CapabilityPolicy:
    enabled: frozenset[str]
    billable: frozenset[str] = frozenset()
    available: bool = True

    def __post_init__(self) -> None:
        if not self.billable.issubset(self.enabled):
            raise ValueError("billable capabilities must also be enabled")

    def require_allowed(self, capability: str) -> None:
        if not self.available:
            raise PolicyUnavailable("capability policy unavailable")
        if _RETIRED.search(capability.lower()):
            raise CapabilityDenied("capability permanently disabled")
        if capability not in self.enabled:
            raise CapabilityDenied("capability is not approved")


def dispatch_external(
    context: ExecutionContext | None,
    capability: str,
    load_policy: Callable[[], CapabilityPolicy | None],
    operation: Callable[[], T],
    *,
    validate_context: Callable[[ExecutionContext], bool] | None = None,
    reserve_attempt: Callable[[ExecutionContext, str], bool] | None = None,
) -> T:
    """Check context and policy before an operation can reserve or send anything."""
    if context is None or not context.is_current():
        raise PolicyUnavailable("valid execution context unavailable")
    if validate_context is not None and not validate_context(context):
        raise CapabilityDenied("execution authorization is no longer active")
    try:
        policy = load_policy()
    except Exception as exc:
        raise PolicyUnavailable("capability policy unavailable") from exc
    if policy is None:
        raise PolicyUnavailable("capability policy unavailable")
    policy.require_allowed(capability)
    if capability in policy.billable and reserve_attempt is not None:
        if not reserve_attempt(context, capability):
            raise CapabilityDenied("execution budget exhausted")
    return operation()
