import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { network } from "hardhat";

const { ethers } = await network.create();

describe("HivemindINFT", function () {
  it("mints a winning agent with a storage and intelligence reference", async function () {
    const [deployer, winner] = await ethers.getSigners();
    const inft = await ethers.deployContract("HivemindINFT", [
      deployer.address
    ]);
    const deploymentBlock = await ethers.provider.getBlockNumber();

    const storageHash =
      "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";

    const tx = await inft.mintAgent(
      winner.address,
      "0g://storage/hivemind/snapshots/agent-alpha.json",
      storageHash,
      "0g-compute:qwen-2.5-7b-instruct",
      "sha256:strategy-alpha-v0",
      9120
    );
    await tx.wait();

    const events = await inft.queryFilter(
      inft.filters.AgentCrystallized(),
      deploymentBlock,
      "latest"
    );
    assert.equal(events.length, 1);
    assert.equal(events[0].args[0], 1n);
    assert.equal(events[0].args[1], winner.address);
    assert.equal(
      events[0].args[2],
      "0g://storage/hivemind/snapshots/agent-alpha.json"
    );
    assert.equal(events[0].args[3], storageHash);
    assert.equal(events[0].args[4], "0g-compute:qwen-2.5-7b-instruct");
    assert.equal(events[0].args[5], 9120n);

    assert.equal(await inft.ownerOf(1), winner.address);

    const ref = await inft.intelligenceRef(1);
    assert.equal(
      ref.storageUri,
      "0g://storage/hivemind/snapshots/agent-alpha.json"
    );
    assert.equal(ref.storageHash, storageHash);
    assert.equal(ref.strategyDigest, "sha256:strategy-alpha-v0");
    assert.equal(ref.aiq, 9120n);
  });
});
