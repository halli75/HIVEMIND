from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hivemind_sdk import (
    CrystallizationPipeline,
    LocalAxlMessageBus,
    LocalStorageUploadProvider,
    MockWeb3Provider,
    Scenario,
    ScoringEngine,
    SwarmEngine,
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


class CrystallizeRequest(BaseModel):
    simulation_run_id: str = Field(min_length=1)
    top_n: int = Field(default=1, ge=1, le=10)


_MOCK_OWNER_ADDRESS = "0x000000000000000000000000000000000000dEaD"


def _build_crystallization_pipeline() -> CrystallizationPipeline:
    use_mock = os.environ.get("HIVEMIND_USE_MOCK_0G", "true").lower() in {"1", "true", "yes"}
    owner_address = os.environ.get("HIVEMIND_INFT_OWNER_ADDRESS") or _MOCK_OWNER_ADDRESS
    if use_mock:
        return CrystallizationPipeline(
            storage_provider=LocalStorageUploadProvider(),
            web3_provider=MockWeb3Provider(),
            owner_address=owner_address,
        )
    raise RuntimeError(
        "Live 0G crystallization not configured. Set HIVEMIND_USE_MOCK_0G=true or wire a real Web3 provider."
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
    message_bus = None
    run_mode = None
    if transcript_path_value and not use_mock_gensyn:
        transcript_path = _resolve_repo_path(root, transcript_path_value)
        if transcript_path.exists() and transcript_path.suffix == ".jsonl":
            message_bus = LocalAxlMessageBus(transcript_path=transcript_path)
            run_mode = "local_axl"
    return SwarmEngine(
        seed_snapshot_dir=seed_dir,
        transcript_root=runs_dir,
        message_bus=message_bus,
        run_mode=run_mode,
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
    app.state.scoring_engine = ScoringEngine()
    app.state.crystallization_pipeline = _build_crystallization_pipeline()

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

    @app.post("/crystallize")
    async def crystallize(request: CrystallizeRequest) -> dict[str, Any]:
        snapshot = app.state.engine.latest_snapshot
        if not snapshot.leaderboard:
            raise HTTPException(status_code=409, detail="leaderboard is empty")

        scoring: ScoringEngine = app.state.scoring_engine
        pipeline: CrystallizationPipeline = app.state.crystallization_pipeline

        candidates = list(snapshot.leaderboard[: request.top_n])
        crystallized: list[dict[str, Any]] = []
        for entry in candidates:
            history = [{"pnl_bps": entry.pnl_bps, "run_id": 0}]
            metrics = scoring.score(history)
            winner = {
                "agent_id": entry.agent_id,
                "archetype": entry.archetype,
                "tier": entry.tier,
                "decision_weights": {
                    "confidence": entry.confidence,
                    "aiq": entry.aiq,
                },
                "archetype_params": {"action": entry.action},
                "sharpe_ratio": metrics["sharpe_ratio"],
                "max_drawdown": metrics["max_drawdown"],
                "consistency": metrics["consistency"],
                "composite_score": metrics["composite_score"],
            }
            result = await pipeline.crystallize(winner, request.simulation_run_id)
            crystallized.append(result)

        return {
            "crystallized": crystallized,
            "simulation_run_id": request.simulation_run_id,
            "sequence": snapshot.sequence,
        }

    @app.get("/metrics/tiers")
    async def tier_metrics() -> dict[str, Any]:
        engine = app.state.engine
        snapshot = engine.latest_snapshot
        bucket = engine.token_bucket
        rate_limited = engine.last_rate_limited_count
        return {
            "sequence": snapshot.sequence,
            "tier_metrics": [metric.to_dict() for metric in snapshot.tier_metrics],
            "token_bucket_remaining": bucket.remaining,
            "token_bucket_capacity": bucket.capacity,
            "token_bucket_refill_rate": bucket.refill_rate,
            "rate_limited_count": rate_limited,
            "rate_limited": rate_limited > 0,
            "rate_limited_agents": list(engine.last_rate_limited_agents),
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
