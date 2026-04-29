from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from hivemind_sdk import (
    CrystallizationPipeline,
    ExecutionProvider,
    HybridInferenceProvider,
    LocalAxlMessageBus,
    LocalInferenceProvider,
    LocalStorageUploadProvider,
    MockWeb3Provider,
    Scenario,
    ScoringEngine,
    SwarmEngine,
    UniswapExecutionProvider,
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


class CrystallizeRequest(BaseModel):
    simulation_run_id: str = Field(min_length=1)
    top_n: int = Field(default=1, ge=1, le=10)


_MOCK_OWNER_ADDRESS = "0x000000000000000000000000000000000000dEaD"


def _build_crystallization_pipeline() -> CrystallizationPipeline:
    # Crystallization always defaults to mock; a separate HIVEMIND_USE_MOCK_CRYSTALLIZE
    # toggle or real provider wiring is needed for a live path. This keeps the
    # /crystallize endpoint functional even when HIVEMIND_USE_MOCK_0G=false (live compute).
    owner_address = os.environ.get("HIVEMIND_INFT_OWNER_ADDRESS") or _MOCK_OWNER_ADDRESS
    return CrystallizationPipeline(
        storage_provider=LocalStorageUploadProvider(),
        web3_provider=MockWeb3Provider(),
        owner_address=owner_address,
    )


def _build_execution_provider() -> ExecutionProvider | None:
    """Return a live UniswapExecutionProvider or None (falls back to LocalExecutionProvider)."""
    use_mock = os.environ.get("HIVEMIND_USE_MOCK_UNISWAP", "true").lower() in {"1", "true", "yes"}
    if use_mock:
        return None

    api_key = os.environ.get("UNISWAP_API_KEY", "").strip()
    base_url = os.environ.get("UNISWAP_API_BASE_URL", "https://trade-api.gateway.uniswap.org").strip()
    rpc_url = os.environ.get("SEPOLIA_RPC_URL", "https://ethereum-sepolia-rpc.publicnode.com").strip()
    private_key = os.environ.get("WALLET_PRIVATE_KEY", "").strip()

    if not api_key or not private_key:
        import warnings
        warnings.warn(
            "HIVEMIND_USE_MOCK_UNISWAP=false but UNISWAP_API_KEY or WALLET_PRIVATE_KEY "
            "is missing — falling back to mock execution provider",
            stacklevel=2,
        )
        return None

    import sys as _sys
    _exec_root = str(Path(__file__).resolve().parents[4] / "apps" / "execution")
    if _exec_root not in _sys.path:
        _sys.path.insert(0, _exec_root)

    from uniswap_client import UniswapClient, SEPOLIA_WETH, SEPOLIA_USDC  # type: ignore[import-not-found]
    from eth_account import Account  # type: ignore[import-not-found]

    token_in = os.environ.get("UNISWAP_TOKEN_IN_ADDRESS", SEPOLIA_WETH).strip() or SEPOLIA_WETH
    token_out = os.environ.get("UNISWAP_TOKEN_OUT_ADDRESS", SEPOLIA_USDC).strip() or SEPOLIA_USDC
    amount_in_wei = int(os.environ.get("UNISWAP_AMOUNT_IN_WEI", "1000000000000000"))
    swapper = Account.from_key(private_key).address

    client = UniswapClient(api_key=api_key, base_url=base_url, rpc_url=rpc_url)
    return UniswapExecutionProvider(
        client=client,
        swapper_address=swapper,
        token_in=token_in,
        token_out=token_out,
        amount_in_wei=amount_in_wei,
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


def _looks_like_storage_unavailable(output: str) -> bool:
    normalized = output.lower()
    return any(
        marker in normalized
        for marker in (
            "storage_unavailable",
            "service unavailable",
            "503",
            "502",
            "504",
        )
    )


def _looks_like_storage_upload_failed(output: str) -> bool:
    normalized = output.lower()
    return any(
        marker in normalized
        for marker in (
            "storage_upload_failed",
            "failed to submit transaction",
            "providererror: execution reverted",
        )
    )


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
    execution_provider: ExecutionProvider | None = None,
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
        execution_provider=execution_provider,
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
        execution_provider=_build_execution_provider(),
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

    @app.post("/mint")
    async def mint_inft() -> dict[str, Any]:
        """Trigger a real iNFT mint: encrypt → 0G Storage → mintAgent on 0G Galileo.

        Delegates to contracts/scripts/mint-inft.ts via npm run mint.
        Requires INFT_CONTRACT_ADDRESS, DEPLOYER_PRIVATE_KEY, ZERO_G_RPC_URL in env.
        """
        import asyncio as _asyncio
        import re as _re

        inft_address = os.environ.get("INFT_CONTRACT_ADDRESS", "").strip()
        if not inft_address:
            raise HTTPException(status_code=400, detail="INFT_CONTRACT_ADDRESS not set in environment")

        contracts_dir = _repo_root() / "contracts"
        if not contracts_dir.exists():
            raise HTTPException(status_code=500, detail="contracts/ directory not found")

        npm_cmd = "npm.cmd" if os.name == "nt" else "npm"
        env = {**os.environ}
        env.setdefault("HIVEMIND_API_URL", "http://localhost:8000")
        timeout_seconds = _env_int("MINT_SCRIPT_TIMEOUT_SECONDS", default=240)

        try:
            proc = await _asyncio.create_subprocess_exec(
                npm_cmd, "run", "mint",
                cwd=str(contracts_dir),
                env=env,
                stdout=_asyncio.subprocess.PIPE,
                stderr=_asyncio.subprocess.STDOUT,
            )
            stdout, _ = await _asyncio.wait_for(proc.communicate(), timeout=timeout_seconds)
        except _asyncio.TimeoutError:
            raise HTTPException(
                status_code=504,
                detail={
                    "status": "mint_timeout",
                    "message": f"Mint script timed out after {timeout_seconds}s",
                },
            )

        output = stdout.decode("utf-8", errors="replace")

        if proc.returncode != 0:
            if _looks_like_storage_unavailable(output):
                raise HTTPException(
                    status_code=503,
                    detail={
                        "status": "storage_unavailable",
                        "message": "0G Storage upload is unavailable; encryption succeeded but minting did not start.",
                        "retry": "Retry POST /mint after the 0G Storage testnet recovers.",
                        "output_tail": output[-3000:],
                    },
                )
            if _looks_like_storage_upload_failed(output):
                raise HTTPException(
                    status_code=502,
                    detail={
                        "status": "storage_upload_failed",
                        "message": "0G Storage upload reached the storage network, but the storage fee transaction failed before minting.",
                        "retry": "Verify the selected 0G Storage indexer/Flow contract and retry before minting.",
                        "output_tail": output[-3000:],
                    },
                )
            raise HTTPException(
                status_code=500,
                detail={
                    "status": "mint_failed",
                    "message": f"Mint script exited {proc.returncode}",
                    "output_tail": output[-3000:],
                },
            )

        token_id_match = _re.search(r"Token ID:\s*(\d+)", output)
        tx_match = _re.search(r"Tx:\s*(https?://\S+)", output)
        storage_match = _re.search(r"Storage:\s*(https?://\S+)", output)
        storage_uri_match = _re.search(r"Storage URI:\s*(\S+)", output)
        root_hash_match = _re.search(r"rootHash:\s*(\S+)", output)
        content_hash_match = _re.search(r"Content hash \(sha256\):\s*([0-9a-fA-F]+)", output)
        tx_hash_match = _re.search(r"/tx/(0x[a-fA-F0-9]+)", tx_match.group(1) if tx_match else "")

        token_id = int(token_id_match.group(1)) if token_id_match else None
        tx_hash = tx_hash_match.group(1) if tx_hash_match else None
        storage_uri = storage_uri_match.group(1) if storage_uri_match else None
        storage_hash = root_hash_match.group(1) if root_hash_match else None
        content_hash = content_hash_match.group(1) if content_hash_match else None

        snapshot = app.state.engine.record_inft_mint(
            token_id=token_id,
            tx_hash=tx_hash,
            contract_address=inft_address,
            storage_uri=storage_uri,
            storage_hash=storage_hash,
            content_hash=content_hash,
        )
        await app.state.websocket_hub.broadcast({"type": "snapshot", "snapshot": snapshot.to_dict()})

        return {
            "status": "minted",
            "token_id": token_id,
            "tx_hash": tx_hash,
            "tx_url": tx_match.group(1) if tx_match else None,
            "storage_url": storage_match.group(1) if storage_match else None,
            "storage_uri": storage_uri,
            "storage_hash": storage_hash,
            "content_hash": content_hash,
            "contract": inft_address,
            "proof": snapshot.proof["inft"],
            "output": output[-3000:],
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
