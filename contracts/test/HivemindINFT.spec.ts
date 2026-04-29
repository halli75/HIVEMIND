import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { EventLog } from "ethers";

import { network } from "hardhat";

const { ethers } = await network.create();

async function deploy() {
  const [deployer, winner, other] = await ethers.getSigners();
  const inft = await ethers.deployContract("HivemindINFT", [deployer.address]);
  return { inft, deployer, winner, other };
}

const STORAGE_HASH =
  "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

describe("HivemindINFT", function () {
  it("mints a winning agent with a storage and intelligence reference", async function () {
    const { inft, deployer, winner } = await deploy();
    const deploymentBlock = await ethers.provider.getBlockNumber();

    const tx = await inft.mintAgent(
      winner.address,
      "0g://storage/hivemind/snapshots/agent-alpha.json",
      STORAGE_HASH,
      "0g-compute:qwen-2.5-7b-instruct",
      "sha256:strategy-alpha-v0",
      9120
    );
    await tx.wait();

    const events = (await inft.queryFilter(
      inft.filters.AgentCrystallized(),
      deploymentBlock,
      "latest"
    )) as unknown as EventLog[];
    assert.equal(events.length, 1);
    assert.equal(events[0].args[0], 1n);
    assert.equal(events[0].args[1], winner.address);
    assert.equal(
      events[0].args[2],
      "0g://storage/hivemind/snapshots/agent-alpha.json"
    );
    assert.equal(events[0].args[3], STORAGE_HASH);
    assert.equal(events[0].args[4], "0g-compute:qwen-2.5-7b-instruct");
    assert.equal(events[0].args[5], 9120n);

    assert.equal(await inft.ownerOf(1), winner.address);

    const ref = await inft.intelligenceRef(1);
    assert.equal(
      ref.storageUri,
      "0g://storage/hivemind/snapshots/agent-alpha.json"
    );
    assert.equal(ref.storageHash, STORAGE_HASH);
    assert.equal(ref.strategyDigest, "sha256:strategy-alpha-v0");
    assert.equal(ref.aiq, 9120n);
  });

  it("ERC-7857: transfer moves ownership and emits PublishedSealedKey", async function () {
    const { inft, deployer, winner, other } = await deploy();
    const deploymentBlock = await ethers.provider.getBlockNumber();

    // Mint token 1 to winner
    await (await inft.mintAgent(
      winner.address,
      "0g://storage/hivemind/test-agent.json",
      STORAGE_HASH,
      "test-model",
      "sha256:test-digest",
      5000
    )).wait();

    assert.equal(await inft.ownerOf(1), winner.address);

    // winner transfers to other
    const sealedKey = ethers.hexlify(ethers.randomBytes(32));
    const proof = ethers.hexlify(ethers.randomBytes(16));
    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    const tx = await (inftAsWinner as any).transfer(winner.address, other.address, 1, sealedKey, proof);
    await tx.wait();

    assert.equal(await inft.ownerOf(1), other.address);
    assert.equal(await inft.balanceOf(winner.address), 0n);
    assert.equal(await inft.balanceOf(other.address), 1n);

    // Check PublishedSealedKey event
    const sealedEvents = (await inft.queryFilter(
      inft.filters.PublishedSealedKey(),
      deploymentBlock,
      "latest"
    )) as unknown as EventLog[];
    assert.equal(sealedEvents.length, 1);
    assert.equal(sealedEvents[0].args[0], 1n); // tokenId
  });

  it("ERC-7857: clone creates new token with same metadata and emits MetadataUpdated", async function () {
    const { inft, deployer, winner, other } = await deploy();
    const deploymentBlock = await ethers.provider.getBlockNumber();

    await (await inft.mintAgent(
      winner.address,
      "0g://storage/hivemind/test-agent.json",
      STORAGE_HASH,
      "test-model",
      "sha256:test-digest",
      5000
    )).wait();

    const sealedKey = ethers.hexlify(ethers.randomBytes(32));
    const proof = ethers.hexlify(ethers.randomBytes(16));
    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    const tx = await (inftAsWinner as any).clone(other.address, 1, sealedKey, proof);
    await tx.wait();

    // Token 2 was cloned; winner still owns token 1
    assert.equal(await inft.ownerOf(1), winner.address);
    assert.equal(await inft.ownerOf(2), other.address);

    const ref1 = await inft.intelligenceRef(1);
    const ref2 = await inft.intelligenceRef(2);
    assert.equal(ref1.storageHash, ref2.storageHash);
    assert.equal(ref1.strategyDigest, ref2.strategyDigest);

    // MetadataUpdated emitted for cloned token (and original mint)
    const metaEvents = (await inft.queryFilter(
      inft.filters.MetadataUpdated(),
      deploymentBlock,
      "latest"
    )) as unknown as EventLog[];
    const cloneMetaEvent = metaEvents.find((e) => e.args[0] === 2n);
    assert.ok(cloneMetaEvent, "MetadataUpdated for token 2 not emitted");
  });

  it("ERC-7857: authorizeUsage sets authorization and emits UsageAuthorized", async function () {
    const { inft, deployer, winner, other } = await deploy();

    await (await inft.mintAgent(
      winner.address,
      "0g://storage/hivemind/test-agent.json",
      STORAGE_HASH,
      "test-model",
      "sha256:test-digest",
      5000
    )).wait();

    assert.equal(await inft.isAuthorized(1, other.address), false);

    const permissions = ethers.hexlify(ethers.toUtf8Bytes("read"));
    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    const deploymentBlock = await ethers.provider.getBlockNumber();
    const tx = await (inftAsWinner as any).authorizeUsage(1, other.address, permissions);
    await tx.wait();

    assert.equal(await inft.isAuthorized(1, other.address), true);

    const authEvents = (await inft.queryFilter(
      inft.filters.UsageAuthorized(),
      deploymentBlock,
      "latest"
    )) as unknown as EventLog[];
    assert.equal(authEvents.length, 1);
    assert.equal(authEvents[0].args[0], 1n);         // tokenId
    assert.equal(authEvents[0].args[1], other.address); // executor
  });
});
