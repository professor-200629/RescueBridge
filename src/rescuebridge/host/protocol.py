"""Fixed request schema for the Windows helper.

The helper accepts ONLY these operations. There is no generic command, shell, script, path, registry, or
URL field anywhere in this protocol. Every field is bounded and closed where possible.
"""

from __future__ import annotations

import math
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


ObserveKind = Literal["mouse", "audio", "windows", "workpad", "click_test"]
HelperAction = Literal["SET_MOUSE_PRIMARY", "SET_AUDIO_ENDPOINT", "PLAY_TEST_TONE", "MOVE_WINDOW", "SHOW_CLICK_TEST"]

ShortId = Annotated[str, Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_.\-]+$")]
EndpointId = Annotated[str, Field(min_length=1, max_length=200, pattern=r"^[A-Za-z0-9{}.\-_#\\:&]+$")]
Coord = Annotated[int, Field(ge=-100_000, le=100_000)]


class SetMouseParams(_Strict):
    swap: bool
    expect_swap: bool  # precondition: effective mapping observed when the proposal was made


class SetAudioParams(_Strict):
    endpoint_id: EndpointId
    mute: bool | None = None
    volume_scalar: float | None = None
    expect_muted: bool
    expect_volume_scalar: float

    @field_validator("volume_scalar", "expect_volume_scalar")
    @classmethod
    def _finite_unit(cls, v: float | None) -> float | None:
        if v is None:
            return v
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("volume must be a finite number in [0, 1]")
        return v


class PlayToneParams(_Strict):
    endpoint_id: EndpointId
    duration_ms: int = Field(ge=200, le=2000)
    frequency_hz: int = Field(ge=300, le=1200)
    # The approval covers this endpoint, unmuted, at this volume; the helper refuses to play otherwise.
    expect_muted: Literal[False]
    expect_volume_scalar: float

    @field_validator("expect_volume_scalar")
    @classmethod
    def _finite_unit(cls, v: float) -> float:
        if not math.isfinite(v) or not 0.0 <= v <= 1.0:
            raise ValueError("volume must be a finite number in [0, 1]")
        return v


class MoveWindowParams(_Strict):
    target_ref: ShortId
    rect: tuple[Coord, Coord, Coord, Coord]
    monitors_fingerprint: Annotated[str, Field(min_length=8, max_length=128)]

    @field_validator("rect")
    @classmethod
    def _valid_rect(cls, v: tuple[int, int, int, int]) -> tuple[int, int, int, int]:
        left, top, right, bottom = v
        if right - left < 100 or bottom - top < 80:
            raise ValueError("target rectangle too small")
        if right - left > 20_000 or bottom - top > 20_000:
            raise ValueError("target rectangle too large")
        return v


class ShowClickTestParams(_Strict):
    test_id: ShortId


ACTION_PARAMS: dict[str, type[_Strict]] = {
    "SET_MOUSE_PRIMARY": SetMouseParams,
    "SET_AUDIO_ENDPOINT": SetAudioParams,
    "PLAY_TEST_TONE": PlayToneParams,
    "MOVE_WINDOW": MoveWindowParams,
    "SHOW_CLICK_TEST": ShowClickTestParams,
}


class HealthRequest(_Strict):
    op: Literal["health"]


class ObserveRequest(_Strict):
    op: Literal["observe"]
    kind: ObserveKind
    test_id: ShortId | None = None


class FenceRequest(_Strict):
    op: Literal["fence"]
    revision: int = Field(ge=0, le=2**53)


class ExecuteRequest(_Strict):
    op: Literal["execute"]
    revision: int = Field(ge=0, le=2**53)
    operation_id: ShortId
    action: HelperAction
    params: dict[str, Any]

    def typed_params(self) -> _Strict:
        return ACTION_PARAMS[self.action].model_validate(self.params)


Request = HealthRequest | ObserveRequest | FenceRequest | ExecuteRequest


def parse_request(raw: dict[str, Any]) -> Request:
    op = raw.get("op") if isinstance(raw, dict) else None
    model: type[_Strict]
    if op == "health":
        model = HealthRequest
    elif op == "observe":
        model = ObserveRequest
    elif op == "fence":
        model = FenceRequest
    elif op == "execute":
        model = ExecuteRequest
    else:
        raise ValueError("unknown op")
    req = model.model_validate(raw)
    if isinstance(req, ExecuteRequest):
        req.typed_params()  # validate action-specific params eagerly
    return req  # type: ignore[return-value]


ErrorCode = Literal[
    "BAD_REQUEST",
    "FENCED",
    "PRECONDITION_FAILED",
    "TARGET_INVALID",
    "TARGET_CHANGED",
    "ENDPOINT_CHANGED",
    "MONITORS_CHANGED",
    "UNSUPPORTED",
    "OS_ERROR",
    "UNOBSERVABLE",
    "NOT_AUTHENTICATED",
]


def ok(mode: str, result: dict[str, Any]) -> dict[str, Any]:
    return {"ok": True, "mode": mode, "result": result}


def err(mode: str, code: ErrorCode, message: str, **extra: Any) -> dict[str, Any]:
    return {"ok": False, "mode": mode, "error": {"code": code, "message": message[:300], **extra}}
