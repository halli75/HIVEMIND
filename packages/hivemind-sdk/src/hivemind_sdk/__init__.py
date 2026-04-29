"""Local-first SDK for deterministic HIVEMIND swarm simulations.

Note: ``CrystallizationPipeline`` requires the optional ``web3`` and
``cryptography`` packages. Install them with ``pip install hivemind-sdk[crystallize]``
or directly: ``pip install web3 cryptography``.
"""

from .archetypes import DEFAULT_ARCHETYPES, archetype_by_name
from .crystallization import (
    CrystallizationPipeline,
    LocalStorageUploadProvider,
    MockWeb3Provider,
    Storage0GProvider,
    Web3MintProvider,
    Web3Provider,
)
from .scoring import ScoringEngine
from .axl import (
    AXL_MESSAGE_TYPES,
    AxlMessage,
    AxlMessageType,
    AxlTranscriptStats,
    append_jsonl,
    payload_digest,
    parse_timestamp,
    read_transcript,
    transcript_stats,
    utc_now_iso,
)
from .axl_pool import AXLPoolManager
from .engine import SwarmEngine
from .models import (
    AgentArchetype,
    AgentState,
    IntegrationEnvelope,
    LeaderboardEntry,
    RunMode,
    Scenario,
    SwarmSnapshot,
    TierMetric,
)
from .providers import (
    ExecutionProvider,
    InferenceProvider,
    LocalAxlMessageBus,
    LocalExecutionProvider,
    MessageBus,
    MockInferenceProvider,
    SeedReplay,
    StorageProvider,
    UniswapExecutionProvider,
    use_mock_inference,
)

__all__ = [
    "AXL_MESSAGE_TYPES",
    "AXLPoolManager",
    "AgentArchetype",
    "AgentState",
    "AxlMessage",
    "AxlMessageType",
    "AxlTranscriptStats",
    "CrystallizationPipeline",
    "DEFAULT_ARCHETYPES",
    "ExecutionProvider",
    "InferenceProvider",
    "IntegrationEnvelope",
    "LeaderboardEntry",
    "LocalAxlMessageBus",
    "LocalExecutionProvider",
    "LocalStorageUploadProvider",
    "MessageBus",
    "MockInferenceProvider",
    "MockWeb3Provider",
    "RunMode",
    "Scenario",
    "ScoringEngine",
    "SeedReplay",
    "Storage0GProvider",
    "StorageProvider",
    "SwarmEngine",
    "SwarmSnapshot",
    "TierMetric",
    "UniswapExecutionProvider",
    "Web3MintProvider",
    "Web3Provider",
    "append_jsonl",
    "archetype_by_name",
    "payload_digest",
    "parse_timestamp",
    "read_transcript",
    "transcript_stats",
    "use_mock_inference",
    "utc_now_iso",
]
