import assert from "node:assert/strict";
import { describe, it } from "node:test";

import { network } from "hardhat";

const { ethers } = await network.create();

describe("HivemindINFT", function () {
  it("mints a winning agent with an intelligence reference and metadata URI", async function () {
    const [deployer, winner] = await ethers.getSigners();
    const inft = await ethers.deployContract("HivemindINFT", [deployer.address]);
    const deploymentBlock = await ethers.provider.getBlockNumber();

    const intelligenceRef = "0g://storage/hivemind/snapshots/agent-alpha.enc";
    const metadataURI = "ipfs://bafy.../agent-alpha.json";
    const royaltyBps = 500n;

    const tx = await inft.mintAgent(winner.address, intelligenceRef, metadataURI, royaltyBps);
    await tx.wait();

    const events = await inft.queryFilter(
      inft.filters.AgentMinted(),
      deploymentBlock,
      "latest",
    );
    assert.equal(events.length, 1);
    assert.equal(events[0].args[0], 1n);
    assert.equal(events[0].args[1], winner.address);
    assert.equal(events[0].args[2], intelligenceRef);

    assert.equal(await inft.ownerOf(1), winner.address);
    assert.equal(await inft.intelligenceRef(1), intelligenceRef);
    assert.equal(await inft.tokenURI(1), metadataURI);

    const [receiver, royaltyAmount] = await inft.royaltyInfo(1, 10_000n);
    assert.equal(receiver, winner.address);
    assert.equal(royaltyAmount, 500n);

    assert.equal(await inft.supportsInterface("0x2a55205a"), true);
    assert.equal(await inft.supportsInterface("0x80ac58cd"), true);
  });

  it("rejects mints from non-owners", async function () {
    const [deployer, attacker, victim] = await ethers.getSigners();
    const inft = await ethers.deployContract("HivemindINFT", [deployer.address]);

    await assert.rejects(
      inft.connect(attacker).mintAgent(victim.address, "0g://x", "ipfs://y", 100n),
    );
  });
});
