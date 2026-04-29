/**
 * mint-inft.ts - Encrypt winning agent strategy, upload to 0G Storage, mint ERC-7857 iNFT.
 *
 * Usage:
 *   npm run mint                     # reads winning agent from HIVEMIND_API_URL/state
 *   npm run mint:mock                # uses hardcoded demo agent (API call skipped; still mints on-chain)
 *
 * Required env vars (from .env):
 *   DEPLOYER_PRIVATE_KEY             wallet that is the contract minter
 *   INFT_CONTRACT_ADDRESS            deployed HivemindINFT address
 *   ZERO_G_RPC_URL                   0G Galileo RPC endpoint
 *   ZERO_G_STORAGE_INDEXER_URL       0G Storage indexer (default: testnet standard)
 *   HIVEMIND_API_URL                 running API (default: http://localhost:8000)
 *
 * Optional:
 *   MINT_MOCK=1                      Use hardcoded demo agent instead of live API
 *   MINT_MOCK_STORAGE=1              Allow minting even when 0G Storage upload fails
 *                                    (uses sha256 content-hash URI as fallback - for testing only)
 */

import { createHash, createCipheriv, randomBytes } from "node:crypto";
import { writeFileSync, unlinkSync, mkdirSync } from "node:fs";
import { join, resolve } from "node:path";
import { tmpdir } from "node:os";
import { network } from "hardhat";

const { ethers } = await network.create();

// ---------------------------------------------------------------------------
// Config
// ---------------------------------------------------------------------------
const INDEXER_URL =
  process.env.ZERO_G_STORAGE_INDEXER_URL ||
  "https://indexer-storage-testnet-standard.0g.ai";
const RPC_URL =
  process.env.ZERO_G_RPC_URL || "https://evmrpc-testnet.0g.ai";
const API_URL = process.env.HIVEMIND_API_URL || "http://localhost:8000";
const CONTRACT_ADDRESS = process.env.INFT_CONTRACT_ADDRESS;

const HIVEMIND_INFT_ABI = [
  "function mintAgent(address to, string calldata storageUri, bytes32 storageHash, string calldata model, string calldata strategyDigest, uint64 aiq) external returns (uint256)",
  "event AgentCrystallized(uint256 indexed tokenId, address indexed owner, string storageUri, bytes32 storageHash, string model, uint64 aiq)",
  "event MetadataUpdated(uint256 indexed tokenId, bytes32 newHash)",
];

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------
interface AgentWinner {
  agent_id: string;
  archetype: string;
  tier: number;
  action: string;
  confidence: number;
  pnl_bps: number;
  aiq: number;
  score: number;
  rationale: string;
  model: string;
  inference_source: string;
  scenario_id: string;
}

// ---------------------------------------------------------------------------
// Step 1: Fetch winning agent
// ---------------------------------------------------------------------------
async function fetchWinner(mock: boolean): Promise<AgentWinner> {
  if (mock) {
    return {
      agent_id: "agent-001",
      archetype: "momentum-scalper",
      tier: 1,
      action: "buy",
      confidence: 0.85,
      pnl_bps: 42.5,
      aiq: 9120,
      score: 0.91,
      rationale: "momentum-scalper selected buy with sentiment=0.70",
      model: "qwen/qwen-2.5-7b-instruct",
      inference_source: "0g_compute",
      scenario_id: "demo-bull-001",
    };
  }

  console.log(`  Fetching winning agent from ${API_URL}/state ...`);
  const res = await fetch(`${API_URL}/state`);
  if (!res.ok) throw new Error(`API responded ${res.status}: ${await res.text()}`);

  const state = (await res.json()) as {
    leaderboard: Array<{
      agent_id: string;
      archetype: string;
      tier: number;
      action: string;
      score: number;
      confidence: number;
      pnl_bps: number;
      aiq: number;
    }>;
    scenario: { scenario_id: string };
    agents: Array<{ agent_id: string; model: string; inference_source: string; rationale: string }>;
  };

  const top = state.leaderboard[0];
  const agentDetails = state.agents.find((a) => a.agent_id === top.agent_id);

  return {
    agent_id: top.agent_id,
    archetype: top.archetype,
    tier: top.tier,
    action: top.action,
    confidence: top.confidence,
    pnl_bps: top.pnl_bps,
    aiq: top.aiq,
    score: top.score,
    rationale: agentDetails?.rationale ?? "",
    model: agentDetails?.model ?? "local-deterministic",
    inference_source: agentDetails?.inference_source ?? "local",
    scenario_id: state.scenario?.scenario_id ?? "unknown",
  };
}

// ---------------------------------------------------------------------------
// Step 2: Encrypt strategy payload with AES-256-GCM
// ---------------------------------------------------------------------------
interface EncryptResult {
  encryptedBuffer: Buffer;
  contentHash: string;   // hex sha256 of encrypted buffer -> on-chain bytes32
  key: string;           // hex AES key (saved locally for demo decryption)
  iv: string;            // hex IV
  authTag: string;       // hex GCM auth tag
}

function encryptStrategy(winner: AgentWinner): EncryptResult {
  const payload = JSON.stringify({
    agent_id: winner.agent_id,
    archetype: winner.archetype,
    tier: winner.tier,
    action: winner.action,
    confidence: winner.confidence,
    pnl_bps: winner.pnl_bps,
    aiq: winner.aiq,
    score: winner.score,
    rationale: winner.rationale,
    model: winner.model,
    inference_source: winner.inference_source,
    scenario_id: winner.scenario_id,
    encrypted_at: new Date().toISOString(),
  });

  const key = randomBytes(32);
  const iv = randomBytes(12);
  const cipher = createCipheriv("aes-256-gcm", key, iv);

  const ciphertext = Buffer.concat([cipher.update(payload, "utf8"), cipher.final()]);
  const authTag = cipher.getAuthTag();
  const encryptedBuffer = Buffer.concat([ciphertext, authTag]);

  const contentHash = createHash("sha256").update(encryptedBuffer).digest("hex");

  return {
    encryptedBuffer,
    contentHash,
    key: key.toString("hex"),
    iv: iv.toString("hex"),
    authTag: authTag.toString("hex"),
  };
}

// ---------------------------------------------------------------------------
// Step 3: Upload to 0G Storage
// Returns { storageUri, uploadTxHash, rootHash }
// ---------------------------------------------------------------------------
async function uploadToZeroGStorage(
  encryptedBuffer: Buffer,
  contentHash: string,
  signer: Awaited<ReturnType<typeof ethers.getSigner>>,
  mockStorage: boolean
): Promise<{ storageUri: string; uploadTxHash: string | null; rootHash: string }> {
  let tempFile: string | null = null;
  try {
    const { ZgFile, Indexer } = await import("@0glabs/0g-ts-sdk");

    // ZgFile requires a file path - write temp file
    tempFile = join(tmpdir(), `hivemind-${contentHash}.enc`);
    writeFileSync(tempFile, encryptedBuffer);

    console.log("  Uploading to 0G Storage via SDK ...");
    const zgFile = await ZgFile.fromFilePath(tempFile);
    let result: { txHash: string; rootHash: string };
    try {
      const indexer = new Indexer(INDEXER_URL);
      // upload returns [{txHash, rootHash}, Error | null]
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const [res, err] = await indexer.upload(zgFile, RPC_URL, signer as any);
      if (err) throw err;
      result = res;
    } finally {
      await zgFile.close();
    }

    const { txHash: uploadTxHash, rootHash } = result;
    const storageUri = `0g://storage/hivemind/${rootHash}`;
    console.log(`  rootHash:  ${rootHash}`);
    console.log(`  upload tx: ${uploadTxHash}`);
    return { storageUri, uploadTxHash, rootHash };
  } catch (sdkErr) {
    if (!mockStorage) {
      throw new Error(
        `0G Storage upload failed: ${sdkErr}\n\n` +
        `Encrypted strategy must be stored on 0G before minting.\n` +
        `Fix the upload error, or set MINT_MOCK_STORAGE=1 to bypass (testing only).`
      );
    }
    // Mock-storage mode: fall back to content-hash URI for local testing
    console.warn(`  [MOCK_STORAGE] Upload failed: ${sdkErr}`);
    console.warn(`  [MOCK_STORAGE] Using sha256 fallback URI - not a real 0G Storage upload.`);
    const storageUri = `0g://storage/hivemind/${contentHash}`;
    return { storageUri, uploadTxHash: null, rootHash: contentHash };
  } finally {
    if (tempFile) {
      try { unlinkSync(tempFile); } catch { /* ignore */ }
    }
  }
}

// ---------------------------------------------------------------------------
// Step 4: Mint the iNFT on-chain
// ---------------------------------------------------------------------------
async function mintINFT(
  winner: AgentWinner,
  storageUri: string,
  contentHash: string,
  signer: Awaited<ReturnType<typeof ethers.getSigner>>
): Promise<{ tokenId: bigint; txHash: string }> {
  if (!CONTRACT_ADDRESS) {
    throw new Error(
      "INFT_CONTRACT_ADDRESS is not set in .env.\n" +
      "Deploy the contract first:\n" +
      "  cd contracts && npm run deploy:0g:galileo\n" +
      "Then add the printed address to .env as INFT_CONTRACT_ADDRESS=<address>"
    );
  }

  const contract = new ethers.Contract(CONTRACT_ADDRESS, HIVEMIND_INFT_ABI, signer);

  // Pad sha256 hash to 32 bytes for bytes32 param (sha256 is already 32 bytes / 64 hex chars)
  const storageHashBytes32 = `0x${contentHash}` as `0x${string}`;
  const model = winner.model || "local-deterministic";
  const strategyDigest = `sha256:${contentHash.slice(0, 16)}`;
  const aiq = Math.round(winner.aiq);

  console.log(`  Minting iNFT on 0G Galileo ...`);
  console.log(`    to:             ${await signer.getAddress()}`);
  console.log(`    storageUri:     ${storageUri}`);
  console.log(`    storageHash:    ${storageHashBytes32}`);
  console.log(`    model:          ${model}`);
  console.log(`    strategyDigest: ${strategyDigest}`);
  console.log(`    aiq:            ${aiq}`);

  const tx = await contract.mintAgent(
    await signer.getAddress(),
    storageUri,
    storageHashBytes32,
    model,
    strategyDigest,
    aiq
  );

  const receipt = await tx.wait();
  const txHash = receipt.hash as string;

  // Extract tokenId from AgentCrystallized event
  let tokenId = 1n;
  for (const log of receipt.logs) {
    try {
      const parsed = contract.interface.parseLog({
        topics: log.topics as string[],
        data: log.data,
      });
      if (parsed?.name === "AgentCrystallized") {
        tokenId = parsed.args[0] as bigint;
        break;
      }
    } catch {
      // skip unrelated logs
    }
  }

  return { tokenId, txHash };
}

// ---------------------------------------------------------------------------
// Main
// ---------------------------------------------------------------------------
async function main() {
  const isMock = process.env.MINT_MOCK === "1" || process.argv.includes("--mock");
  const isMockStorage = process.env.MINT_MOCK_STORAGE === "1";

  console.log("\n=== HIVEMIND iNFT Mint ===");
  console.log(`  Mode:    ${isMock ? "mock (demo agent)" : "live (from API)"}`);
  console.log(`  Storage: ${isMockStorage ? "MOCK (sha256 fallback - not a real upload)" : "live (0G Storage)"}`);
  console.log(`  Network: 0G Galileo (chainId 16602)`);
  console.log();

  const [signer] = await ethers.getSigners();
  console.log(`  Deployer: ${await signer.getAddress()}`);

  // 1. Get winner
  console.log("\n[1/4] Fetching winning agent ...");
  const winner = await fetchWinner(isMock);
  console.log(`  Winner: ${winner.agent_id} (${winner.archetype}, tier ${winner.tier})`);
  console.log(`  Action: ${winner.action}  conf=${winner.confidence.toFixed(2)}  aiq=${winner.aiq}`);

  // 2. Encrypt strategy
  console.log("\n[2/4] Encrypting strategy with AES-256-GCM ...");
  const { encryptedBuffer, contentHash, key, iv, authTag } = encryptStrategy(winner);
  console.log(`  Content hash (sha256): ${contentHash}`);
  console.log(`  Encrypted size: ${encryptedBuffer.length} bytes`);

  // Save decryption key locally for demo verification
  const keysDir = resolve(process.cwd(), "runs", "inft-keys");
  mkdirSync(keysDir, { recursive: true });
  const keyFile = join(keysDir, `${winner.agent_id}-${Date.now()}.json`);
  writeFileSync(
    keyFile,
    JSON.stringify({ agent_id: winner.agent_id, key, iv, authTag, contentHash }, null, 2)
  );
  console.log(`  Key saved to: ${keyFile}`);

  // 3. Upload to 0G Storage
  console.log("\n[3/4] Uploading to 0G Storage ...");
  const { storageUri, uploadTxHash, rootHash } = await uploadToZeroGStorage(
    encryptedBuffer,
    contentHash,
    signer,
    isMockStorage
  );
  console.log(`  Storage URI: ${storageUri}`);

  // 4. Mint iNFT
  console.log("\n[4/4] Minting ERC-7857 iNFT on 0G Galileo ...");
  const { tokenId, txHash } = await mintINFT(winner, storageUri, contentHash, signer);

  // Results
  console.log("\n=== MINT COMPLETE ===");
  console.log(`  Token ID:  ${tokenId}`);
  console.log(`  Agent:     ${winner.agent_id} (${winner.archetype})`);
  console.log(`  Action:    ${winner.action}  |  AIQ: ${winner.aiq}`);
  console.log(`  Tx:        https://chainscan-galileo.0g.ai/tx/${txHash}`);
  if (uploadTxHash) {
    console.log(`  Storage:   https://storagescan-galileo.0g.ai/tx/${uploadTxHash}`);
  }
  console.log(`  Contract:  https://chainscan-galileo.0g.ai/address/${CONTRACT_ADDRESS}`);
  console.log();
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
