# HIVEMIND Agent Instructions

## Project Context

HIVEMIND is an ETHGlobal OpenAgents hackathon project.

Core thesis: simulate a DeFi market with a swarm of AI agents on 0G, rank the strongest strategies, crystallize winners into iNFT-backed agents, and execute real Sepolia trades through the Uniswap API. Gensyn AXL is the communication layer between real separate node processes.

## Prize Strategy

Target exactly three partner selections:

1. 0G
   - Best Autonomous Agents, Swarms & iNFT Innovations
   - Best Agent Framework, Tooling & Core Extensions
2. Gensyn AXL
   - Best Application of Agent eXchange Layer
3. Uniswap Foundation
   - Best Uniswap API Integration

Do not let non-target integrations consume critical-path time.

## Critical Path

Every core build decision should support this sentence:

"HIVEMIND simulates a DeFi swarm, crystallizes the winning strategy into an iNFT-backed agent, and executes a real Uniswap trade."

Required MVD:

- 100+ visual agents in the frontend.
- 2+ real Gensyn AXL node processes exchanging typed messages.
- Three-tier inference architecture with visible Tier 1 metrics.
- 0G Compute used for active inference.
- 0G Storage used for agent state or logs.
- Minimal iNFT minted on 0G Chain with an intelligence or memory reference visible in metadata.
- Uniswap Sepolia quote and swap flow with transaction receipt.
- `hivemind-sdk` quickstart with one working custom archetype.
- `FEEDBACK.md` with real Uniswap integration notes.
- README with setup instructions, architecture diagram, and demo narrative.

## Scope Rules

Core:

- 0G Compute, Storage, Chain, and iNFT proof.
- Gensyn AXL with real separate node processes.
- Uniswap API quote, price impact display, and one Sepolia swap.
- Tiered inference, heuristic fallback, scoring, scenario injection, and dashboard metrics.
- Python SDK surface only as far as needed for the 0G framework track.

Stretch only:

- ENS identity.
- KeeperHub relay.
- Breeding contract.
- Marketplace.
- LP position management.
- Live GraphRAG from external APIs.
- 1,000+ real agent execution.

Cut entirely unless explicitly re-approved:

- ENS CCIP-Read gateways.
- HA resolver infrastructure.
- x402 / MPP.
- Any autonomous mainnet execution.

## Engineering Defaults

- For heavy tasks, the lead agent should act as project manager: split work into disjoint engineering slices, delegate implementation to subagents, keep integration/verification in the main thread, and avoid duplicate work across agents.
- Build smallest working vertical slice before adding breadth.
- Prefer real integrations over mock-only demos, but keep mock fallbacks for development and demo resilience.
- Avoid claims the implementation cannot prove in the demo or README.
- Use clear metrics panels to make hidden infrastructure visible: AXL messages, 0G inference calls, AIQ size, fallback count, and latest swap receipt.
- Keep sponsor artifacts current as work happens, not at the end.

## Verification Requirements

Do not mark work complete without proof.

For core milestones, verify with one or more of:

- Passing unit or integration tests.
- Local demo run.
- Explorer link or transaction hash.
- AXL node logs showing cross-process messages.
- 0G Storage readback.
- Screenshot or recording for visual demo work.
- README command run from a clean environment where practical.

## Task Management

- Maintain `tasks/todo.md` for active project tasks.
- Maintain `tasks/lessons.md` for corrections and lessons learned.
- After any user correction, add a concise lesson that prevents repeat mistakes.
- If an approach starts failing repeatedly, stop and re-plan before continuing.

## Demo Constraints

- Demo video target: 2:55, hard maximum 3:00 for 0G.
- The scenario-injection swarm scene should be pre-recorded from a real run.
- The final story should be legible without deep DeFi expertise:
  1. scenario injected,
  2. swarm reacts,
  3. winner selected,
  4. iNFT minted,
  5. Uniswap trade executed.
