import assert from "node:assert/strict";
import { describe, it } from "node:test";
import type { EventLog } from "ethers";

import { network } from "hardhat";

const { ethers } = await network.create();

async function deploy() {
  const [deployer, winner, other, operator] = await ethers.getSigners();
  const inft = await ethers.deployContract("HivemindINFT", [deployer.address]);
  return { inft, deployer, winner, other, operator };
}

const STORAGE_HASH =
  "0xaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa";
const ERC165_INTERFACE_ID = "0x01ffc9a7";
const ERC721_INTERFACE_ID = "0x80ac58cd";
const ERC721_METADATA_INTERFACE_ID = "0x5b5e139f";

async function mintTestAgent(inft: any, to: string) {
  await (await inft.mintAgent(
    to,
    "0g://storage/hivemind/test-agent.json",
    STORAGE_HASH,
    "test-model",
    "sha256:test-digest",
    5000
  )).wait();
}

describe("HivemindINFT", function () {
  it("mints a winning agent with a storage and intelligence reference", async function () {
    const { inft, winner } = await deploy();
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

  it("supports ERC-165, ERC-721, and ERC-721 metadata interfaces", async function () {
    const { inft } = await deploy();

    assert.equal(await inft.supportsInterface(ERC165_INTERFACE_ID), true);
    assert.equal(await inft.supportsInterface(ERC721_INTERFACE_ID), true);
    assert.equal(await inft.supportsInterface(ERC721_METADATA_INTERFACE_ID), true);
    assert.equal(await inft.supportsInterface("0xffffffff"), false);
    assert.equal(await inft.name(), "HIVEMIND iNFT");
    assert.equal(await inft.symbol(), "HIVEAI");
  });

  it("returns token metadata URIs and rejects nonexistent token metadata", async function () {
    const { inft, winner } = await deploy();
    await mintTestAgent(inft, winner.address);

    assert.equal(await inft.tokenURI(1), "hivemind://inft/1");
    await assert.rejects(
      () => inft.tokenURI(99),
      /TokenDoesNotExist/
    );
  });

  it("approves a token spender and clears approval after transferFrom", async function () {
    const { inft, winner, other, operator } = await deploy();
    await mintTestAgent(inft, winner.address);

    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    await (await (inftAsWinner as any).approve(operator.address, 1)).wait();
    assert.equal(await inft.getApproved(1), operator.address);

    const inftAsOperator = inft.connect(operator) as unknown as typeof inft;
    await (await (inftAsOperator as any).transferFrom(winner.address, other.address, 1)).wait();

    assert.equal(await inft.ownerOf(1), other.address);
    assert.equal(await inft.balanceOf(winner.address), 0n);
    assert.equal(await inft.balanceOf(other.address), 1n);
    assert.equal(await inft.getApproved(1), ethers.ZeroAddress);
  });

  it("lets an approved operator transfer with ERC-721 and ERC-7857-style APIs", async function () {
    const { inft, winner, other, operator } = await deploy();
    await mintTestAgent(inft, winner.address);

    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    await (await (inftAsWinner as any).setApprovalForAll(operator.address, true)).wait();
    assert.equal(await inft.isApprovedForAll(winner.address, operator.address), true);

    const inftAsOperator = inft.connect(operator) as unknown as typeof inft;
    const sealedKey = ethers.hexlify(ethers.randomBytes(32));
    const proof = ethers.hexlify(ethers.randomBytes(16));
    await (await (inftAsOperator as any).transfer(
      winner.address,
      other.address,
      1,
      sealedKey,
      proof
    )).wait();

    assert.equal(await inft.ownerOf(1), other.address);
    assert.equal(await inft.balanceOf(winner.address), 0n);
    assert.equal(await inft.balanceOf(other.address), 1n);
  });

  it("supports both safeTransferFrom overloads", async function () {
    const { inft, winner, other } = await deploy();
    await mintTestAgent(inft, winner.address);

    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    await (await (inftAsWinner as any)["safeTransferFrom(address,address,uint256)"](
      winner.address,
      other.address,
      1
    )).wait();

    assert.equal(await inft.ownerOf(1), other.address);

    const receiver = await ethers.deployContract("ERC721ReceiverMock");
    const receiverAddress = await receiver.getAddress();
    const inftAsOther = inft.connect(other) as unknown as typeof inft;
    const data = ethers.hexlify(ethers.toUtf8Bytes("sealed-transfer"));
    await (await (inftAsOther as any)["safeTransferFrom(address,address,uint256,bytes)"](
      other.address,
      receiverAddress,
      1,
      data
    )).wait();

    assert.equal(await inft.ownerOf(1), receiverAddress);
  });

  it("ERC-7857: transfer moves ownership and emits PublishedSealedKey", async function () {
    const { inft, winner, other } = await deploy();
    const deploymentBlock = await ethers.provider.getBlockNumber();

    await mintTestAgent(inft, winner.address);

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

  it("ERC-7857: transfer rejects non-owner callers", async function () {
    const { inft, winner, other } = await deploy();

    await mintTestAgent(inft, winner.address);

    const sealedKey = ethers.hexlify(ethers.randomBytes(32));
    const proof = ethers.hexlify(ethers.randomBytes(16));
    const inftAsOther = inft.connect(other) as unknown as typeof inft;

    await assert.rejects(
      () => (inftAsOther as any).transfer(winner.address, other.address, 1, sealedKey, proof),
      /NotApprovedOrOwner/
    );
    assert.equal(await inft.ownerOf(1), winner.address);
  });

  it("rejects unauthorized, zero-address, nonexistent, and unsafe receiver transfers", async function () {
    const { inft, winner, other } = await deploy();
    await mintTestAgent(inft, winner.address);

    const inftAsOther = inft.connect(other) as unknown as typeof inft;
    await assert.rejects(
      () => (inftAsOther as any).transferFrom(winner.address, other.address, 1),
      /NotApprovedOrOwner/
    );

    const inftAsWinner = inft.connect(winner) as unknown as typeof inft;
    await assert.rejects(
      () => (inftAsWinner as any).transferFrom(winner.address, ethers.ZeroAddress, 1),
      /InvalidRecipient/
    );

    await assert.rejects(
      () => (inftAsWinner as any).transferFrom(winner.address, other.address, 99),
      /TokenDoesNotExist/
    );

    await assert.rejects(
      () => (inftAsWinner as any).transferFrom(other.address, winner.address, 1),
      /NotTokenOwner/
    );

    const unsafeAddress = await inft.getAddress();
    await assert.rejects(
      () => (inftAsWinner as any)["safeTransferFrom(address,address,uint256)"](
        winner.address,
        unsafeAddress,
        1
      ),
      /UnsafeRecipient/
    );
    assert.equal(await inft.ownerOf(1), winner.address);
  });

  it("ERC-7857: clone creates new token with same metadata and emits MetadataUpdated", async function () {
    const { inft, winner, other } = await deploy();
    const deploymentBlock = await ethers.provider.getBlockNumber();

    await mintTestAgent(inft, winner.address);

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
    const { inft, winner, other } = await deploy();

    await mintTestAgent(inft, winner.address);

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
