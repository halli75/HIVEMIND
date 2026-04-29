from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hivemind_sdk import (
    HybridInferenceProvider,
    LocalAxlMessageBus,
    LocalInferenceProvider,
    Scenario,
    SwarmEngine,
    ZeroGComputeInferenceProvider,
)


class ScenarioRequest(BaseModel):
    scenario_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    volatility: float = Field(ge=0.0, le=1.0)
    liquidity_delta: float = Field(ge=-1.0, le=1.0)
    sentiment: float = Field(ge=-1.0, le=1.0)
    gas_pressure: float = Field(ge=0.0, le=1.0)
    signal_strength: float = Field(default=0.5, ge=0.0, le=1.0)

    def to_sdk(self) -> Scenario:
        return Scenario(
            scenario_id=self.scenario_id,
            label=self.label,
            volatility=self.volatility,
            liquidity_delta=self.liquidity_delta,
            sentiment=self.sentiment,
            gas_pressure=self.gas_pressure,
            signal_strength=self.signal_strength,
        )


class WebSocketHub:
    def __init__(self) -> None:
        self._connections: set[WebSocket] = set()

    async def connect(self, websocket: WebSocket) -> None:
        await websocket.accept()
        self._connections.add(websocket)

    def disconnect(self, websocket: WebSocket) -> None:
        self._connections.discard(websocket)

    async def broadcast(self, payload: dict[str, Any]) -> None:
        stale: list[WebSocket] = []
        for websocket in tuple(self._connections):
            try:
                await websocket.send_json(payload)
            except RuntimeError:
                stale.append(websocket)
        for websocket in stale:
            self.disconnect(websocket)


def _snapshot_event(engine: SwarmEngine) -> dict[str, Any]:
    return {"type": "snapshot", "snapshot": engine.latest_snapshot.to_dict()}


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[4]


def _resolve_repo_path(root: Path, value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _env_bool(name: str, *, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.lower() in {"1", "true", "yes"}


def _env_int(name: str, *, default: int) -> int:
    value = os.environ.get(name)
    if value is None or value == "":
        return default
    return int(value)


def _use_mock_0g() -> bool:
    if "HIVEMIND_USE_MOCK_0G" in os.environ:
        return _env_bool("HIVEMIND_USE_MOCK_0G", default=True)
    if "HIVEMIND_MOCK_INFERENCE" in os.environ:
        return _env_bool("HIVEMIND_MOCK_INFERENCE", default=True)
    return True


def _compose_run_mode(*, local_axl: bool, live_0g: bool) -> str | None:
    if local_axl and live_0g:
        return "local_axl+live_0g"
    if local_axl:
        return "local_axl"
    if live_0g:
        return "live_0g"
    return None


def _default_engine(
    *,
    seed_snapshot_dir: str | Path | None = None,
    transcript_root: str | Path | None = None,
    axl_transcript_path: str | Path | None = None,
) -> SwarmEngine:
    root = _repo_root()
    seed_dir = _resolve_repo_path(
        root, seed_snapshot_dir or os.environ.get("HIVEMIND_SEED_DIR") or root / "data" / "snapshots"
    )
    runs_dir = _resolve_repo_path(root, transcript_root or os.environ.get("HIVEMIND_RUNS_DIR") or root / "runs")
    transcript_path_value = axl_transcript_path or os.environ.get("GENSYN_AXL_TRANSCRIPT_PATH")
    use_mock_gensyn = os.environ.get("HIVEMIND_USE_MOCK_GENSYN", "true").lower() in {"1", "true", "yes"}
    use_mock_0g = _use_mock_0g()
    message_bus = None
    local_axl_enabled = False
    if transcript_path_value and not use_mock_gensyn:
        transcript_path = _resolve_repo_path(root, transcript_path_value)
        if transcript_path.exists() and transcript_path.suffix == ".jsonl":
            message_bus = LocalAxlMessageBus(transcript_path=transcript_path)
            local_axl_enabled = True
    inference_provider: LocalInferenceProvider | HybridInferenceProvider
    if not use_mock_0g:
        api_base_url = os.environ.get("ZERO_G_COMPUTE_API_BASE_URL")
        bearer_token = os.environ.get("ZERO_G_COMPUTE_BEARER_TOKEN")
        if not api_base_url or not bearer_token:
            raise RuntimeError(
                "Live 0G Compute requires ZERO_G_COMPUTE_API_BASE_URL and ZERO_G_COMPUTE_BEARER_TOKEN"
            )
        zero_g = ZeroGComputeInferenceProvider(
            api_base_url=api_base_url,
            bearer_token=bearer_token,
            model=os.environ.get("ZERO_G_COMPUTE_MODEL", "qwen/qwen-2.5-7b-instruct"),
        )
        inference_provider = HybridInferenceProvider(
            real=zero_g,
            top_n=_env_int("ZERO_G_COMPUTE_TOP_N", default=10),
            max_workers=_env_int("ZERO_G_COMPUTE_MAX_WORKERS", default=2),
        )
    else:
        inference_provider = LocalInferenceProvider()
    return SwarmEngine(
        seed_snapshot_dir=seed_dir,
        transcript_root=runs_dir,
        message_bus=message_bus,
        run_mode=_compose_run_mode(local_axl=local_axl_enabled, live_0g=not use_mock_0g),
        inference_provider=inference_provider,
    )


def create_app(
    *,
    engine: SwarmEngine | None = None,
    seed_snapshot_dir: str | Path | None = None,
    transcript_root: str | Path | None = None,
    axl_transcript_path: str | Path | None = None,
) -> FastAPI:
    app = FastAPI(title="HIVEMIND API", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.engine = engine or _default_engine(
        seed_snapshot_dir=seed_snapshot_dir,
        transcript_root=transcript_root,
        axl_transcript_path=axl_transcript_path,
    )
    app.state.websocket_hub = WebSocketHub()

    @app.get("/health")
    async def health() -> dict[str, Any]:
        health_mode = "local-axl" if app.state.engine.run_mode == "local_axl" else f"local-{app.state.engine.run_mode}"
        return {
            "ok": True,
            "mode": health_mode,
            "run_mode": app.state.engine.run_mode,
            "sequence": app.state.engine.latest_snapshot.sequence,
        }

    @app.get("/state")
    async def state() -> dict[str, Any]:
        return app.state.engine.latest_snapshot.to_dict()

    @app.post("/scenario")
    async def inject_scenario(request: ScenarioRequest) -> dict[str, Any]:
        snapshot = app.state.engine.inject_scenario(request.to_sdk())
        event = {"type": "snapshot", "snapshot": snapshot.to_dict()}
        await app.state.websocket_hub.broadcast(event)
        return event

    @app.get("/leaderboard")
    async def leaderboard() -> dict[str, Any]:
        snapshot = app.state.engine.latest_snapshot
        return {
            "sequence": snapshot.sequence,
            "leaderboard": [entry.to_dict() for entry in snapshot.leaderboard],
        }

    @app.get("/metrics/tiers")
    async def tier_metrics() -> dict[str, Any]:
        snapshot = app.state.engine.latest_snapshot
        return {
            "sequence": snapshot.sequence,
            "tier_metrics": [metric.to_dict() for metric in snapshot.tier_metrics],
        }

    @app.websocket("/ws/state")
    async def websocket_state(websocket: WebSocket) -> None:
        hub: WebSocketHub = app.state.websocket_hub
        await hub.connect(websocket)
        try:
            await websocket.send_json(_snapshot_event(app.state.engine))
            while True:
                payload = await websocket.receive_json()
                event_type = payload.get("type")
                if event_type != "inject_scenario":
                    await websocket.send_json(
                        {
                            "type": "error",
                            "message": "unsupported websocket event",
                            "expected": "inject_scenario",
                        }
                    )
                    continue

                scenario_payload = payload.get("scenario", {})
                scenario = ScenarioRequest.model_validate(scenario_payload).to_sdk()
                snapshot = app.state.engine.inject_scenario(scenario)
                event = {"type": "snapshot", "snapshot": snapshot.to_dict()}
                await hub.broadcast(event)
        except WebSocketDisconnect:
            hub.disconnect(websocket)

    return app


app = create_app()
