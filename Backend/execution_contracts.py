from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class ActionResult:
    ok: bool
    status: str
    source: str
    tool_name: str = ""
    engine: str = ""
    run_id: str = ""
    step_id: str = ""
    session_id: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    error: str | None = None
    error_class: str = ""
    legacy_fields: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status,
            "source": self.source,
        }
        if self.tool_name:
            payload["tool_name"] = self.tool_name
        if self.engine:
            payload["engine"] = self.engine
        if self.run_id:
            payload["run_id"] = self.run_id
        if self.step_id:
            payload["step_id"] = self.step_id
        if self.session_id:
            payload["session_id"] = self.session_id
        if self.data:
            payload["data"] = deepcopy(self.data)
        if self.artifacts:
            payload["artifacts"] = deepcopy(self.artifacts)
        if self.error is not None:
            payload["error"] = self.error
        if self.error_class:
            payload["error_class"] = self.error_class
        for key, value in self.legacy_fields.items():
            if key not in payload and value is not None:
                payload[key] = value
        return payload


def success_result(
    *,
    source: str,
    tool_name: str,
    status: str = "ok",
    engine: str = "",
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
    data: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    legacy_fields: dict[str, Any] | None = None,
) -> ActionResult:
    return ActionResult(
        ok=True,
        status=status,
        source=source,
        tool_name=tool_name,
        engine=engine,
        run_id=run_id,
        step_id=step_id,
        session_id=session_id,
        data=dict(data or {}),
        artifacts=list(artifacts or []),
        legacy_fields=dict(legacy_fields or {}),
    )


def error_result(
    *,
    source: str,
    tool_name: str,
    error: str,
    status: str = "error",
    engine: str = "",
    run_id: str = "",
    step_id: str = "",
    session_id: str = "",
    data: dict[str, Any] | None = None,
    artifacts: list[dict[str, Any]] | None = None,
    error_class: str = "",
    legacy_fields: dict[str, Any] | None = None,
) -> ActionResult:
    return ActionResult(
        ok=False,
        status=status,
        source=source,
        tool_name=tool_name,
        engine=engine,
        run_id=run_id,
        step_id=step_id,
        session_id=session_id,
        data=dict(data or {}),
        artifacts=list(artifacts or []),
        error=error,
        error_class=error_class,
        legacy_fields=dict(legacy_fields or {}),
    )
