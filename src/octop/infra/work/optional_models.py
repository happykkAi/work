"""Work first release excludes model calls outside its metered Harness path."""

import os

from octop.infra.errors import ErrorCode, OctopError
from octop.infra.work.routing import work_entry_mode_enabled


def assert_optional_model_allowed() -> None:
    if work_entry_mode_enabled() or any(
        os.environ.get(key, "").strip() for key in ("WORK_CONTROL_DATABASE_URL", "WORK_RUNTIME_ID")
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "Unmetered model calls are disabled in Work")
