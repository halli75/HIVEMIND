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
const STORAGE_MAX_ATTEMPTS = positiveIntFromEnv("MINT_STORAGE_MAX_ATTEMPTS", 4);
const STORAGE_RETRY_BASE_MS = positiveIntFromEnv("MINT_STORAGE_RETRY_BASE_MS", 1500);
// Comma-separated fallback node URLs used when the indexer HTTP API is unavailable.
// e.g. ZERO_G_STORAGE_NODE_URLS=http://34.83.53.209:5678,http://34.169.28.106:5678
const STORAGE_DIRECT_NODE_URLS: string[] = (process.env.ZERO_G_STORAGE_NODE_URLS ?? "")
  .split(",")
  .map((u) => u.trim())
  .filter(Boolean);
// Flow contract address reported by the storage nodes (fallback when indexer is down).
const STORAGE_FLOW_ADDRESS =
  process.env.ZERO_G_FLOW_ADDRESS || "0x22e03a6a89b950f1c82ec5e74f8eca321a105296";

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

function positiveIntFromEnv(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  return Number.isFinite(parsed) && parsed > 0 ? parsed : fallback;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolveSleep) => setTimeout(resolveSleep, ms));
}

function errorText(err: unknown): string {
  if (err instanceof Error) return `${err.name}: ${err.message}`;
  return String(err);
}

function isRetryableStorageError(err: unknown): boolean {
  const text = errorText(err).toLowerCase();
  return (
    text.includes("503") ||
    text.includes("502") ||
    text.includes("504") ||
    text.includes("timeout") ||
    text.includes("timed out") ||
    text.includes("econnreset") ||
    text.includes("enetunreach") ||
    text.includes("fetch failed") ||
    text.includes("service unavailable")
  );
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
    let result: { txHash: string; rootHash: string } | null = null;
    try {
      const { Uploader, StorageNode, getFlowContract, defaultUploadOption } = await import("@0glabs/0g-ts-sdk");
      const indexer = new Indexer(INDEXER_URL);
      let lastErr: unknown = null;
      for (let attempt = 1; attempt <= STORAGE_MAX_ATTEMPTS; attempt += 1) {
        try {
          console.log(`  Storage upload attempt ${attempt}/${STORAGE_MAX_ATTEMPTS} ...`);
          // eslint-disable-next-line @typescript-eslint/no-explicit-any
          const [res, err] = await indexer.upload(zgFile, RPC_URL, signer as any);
          if (err) throw err;
          result = res;
          lastErr = null;
          break;
        } catch (err) {
          lastErr = err;
          const retryable = isRetryableStorageError(err);
          console.warn(`  Storage upload attempt ${attempt} failed: ${errorText(err)}`);
          if (!retryable || attempt === STORAGE_MAX_ATTEMPTS) break;
          const delayMs = STORAGE_RETRY_BASE_MS * 2 ** (attempt - 1);
          console.warn(`  Retrying 0G Storage upload in ${delayMs}ms ...`);
          await sleep(delayMs);
        }
      }
      // If the indexer is unreachable and we have direct node URLs, bypass it.
      if ((lastErr || !result) && isRetryableStorageError(lastErr) && STORAGE_DIRECT_NODE_URLS.length > 0) {
        console.warn(`  Indexer unavailable — falling back to direct node upload (${STORAGE_DIRECT_NODE_URLS.join(", ")})`);
        const nodes = STORAGE_DIRECT_NODE_URLS.map((url) => new StorageNode(url));

        // The testnet Flow contract was upgraded: submit() now wraps Submission with sender address.
        // New ABI: submit(((uint256,bytes,(bytes32,uint256)[]),address))
        // Old SDK calls submit(Submission) which reverts — use a direct ethers call instead.
        const { ethers: hreEthers } = await import("ethers");
        const MARKET_ABI = ["function pricePerSector() view returns (uint256)"];
        const NEW_FLOW_ABI = [
          "function market() view returns (address)",
          "function submit(((uint256,bytes,(bytes32,uint256)[]),address)) payable returns (uint256,bytes32,uint256,uint256)",
        ];
        const directProvider = new hreEthers.JsonRpcProvider(RPC_URL);
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const newFlow = new hreEthers.Contract(STORAGE_FLOW_ADDRESS, NEW_FLOW_ABI, signer as any);

        const [submission, subErr] = await zgFile.createSubmission("0x");
        if (subErr || !submission) throw new Error(`createSubmission failed: ${subErr}`);

        // Calculate fee
        const mktAddr = await newFlow.market();
        const mkt = new hreEthers.Contract(mktAddr, MARKET_ABI, directProvider);
        const pricePerSector = await mkt.pricePerSector();
        let fee = BigInt(0);
        for (const node of submission.nodes) {
          fee += BigInt(1 << Number(node.height)) * pricePerSector;
        }
        console.log(`  Submitting transaction with storage fee: ${fee}`);

        // Build new-style submission: [[length, tags, nodes], senderAddress]
        const signerAddr = await signer.getAddress();
        const wrappedSubmission = [
          [
            submission.length,
            submission.tags,
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            (submission.nodes as any[]).map((n) => [n.root, n.height]),
          ],
          signerAddr,
        ];
        const feeData = await directProvider.getFeeData();
        const gasPrice = feeData.gasPrice ?? BigInt(4_000_000_007);
        // 0G Galileo RPC underestimates gas for submit() — use 2× estimate with 800k floor.
        let gasLimit: bigint;
        try {
          const gasEst = await newFlow.submit.estimateGas(wrappedSubmission, { value: fee });
          gasLimit = gasEst * BigInt(2) > BigInt(800_000) ? gasEst * BigInt(2) : BigInt(800_000);
        } catch {
          gasLimit = BigInt(800_000);
        }
        console.log(`  Sending transaction with gas price ${gasPrice} gas limit ${gasLimit}`);
        const txResp = await newFlow.submit(wrappedSubmission, { value: fee, gasPrice, gasLimit });
        const txReceipt = await txResp.wait();
        if (!txReceipt) throw new Error("Transaction receipt timeout");
        const uploadTxHashDirect = txReceipt.hash as string;
        console.log("  Transaction hash:", uploadTxHashDirect);

        // Parse txSeq from the Submit event
        const submitEventTopic = hreEthers.id(
          "Submit(address,bytes32,uint256,uint256,uint256,(uint256,bytes,(bytes32,uint256)[]))"
        );
        let txSeq = -1;
        for (const log of txReceipt.logs) {
          if (log.topics[0] === submitEventTopic) {
            txSeq = Number(BigInt("0x" + log.data.slice(2, 66)));
            break;
          }
        }
        if (txSeq < 0) throw new Error("Failed to get txSeq from Submit event");
        console.log(`  Transaction sequence number: ${txSeq}`);

        // Wait for storage nodes to index the submission (up to 60s)
        console.log("  Wait for log entry on storage node");
        let nodeInfo = null;
        for (let i = 0; i < 30 && !nodeInfo; i++) {
          await sleep(2000);
          for (const node of nodes) {
            try {
              // eslint-disable-next-line @typescript-eslint/no-explicit-any
              const info = await (node as any).getFileInfoByTxSeq(txSeq);
              if (info) { nodeInfo = info; break; }
            } catch { /* not yet indexed */ }
          }
        }
        if (!nodeInfo) throw new Error("Log entry not found on storage nodes after 60s");

        // Upload segments using Uploader with skipTx (submission already on-chain)
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const dummyFlow = getFlowContract(STORAGE_FLOW_ADDRESS, signer as any);
        const segUploader = new Uploader(nodes, RPC_URL, dummyFlow);
        const [res, err] = await segUploader.uploadFile(zgFile, { ...defaultUploadOption, skipTx: true });
        if (err) throw err;
        if (!res) throw new Error("Direct node upload returned no result");
        result = { txHash: uploadTxHashDirect, rootHash: res.rootHash };
        lastErr = null;
        console.log("  Direct node upload succeeded.");
      }
      if (lastErr || !result) {
        const cause = lastErr ?? new Error("0G Storage SDK returned no upload result");
        const status = isRetryableStorageError(lastErr) ? "storage_unavailable" : "storage_upload_failed";
        throw new Error(`${status}: 0G Storage upload failed after ${STORAGE_MAX_ATTEMPTS} attempts: ${errorText(cause)}`);
      }
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
