import { network } from "hardhat";

const { ethers } = await network.create();

async function main() {
  const [deployer] = await ethers.getSigners();

  const inft = await ethers.deployContract("HivemindINFT", [deployer.address]);
  await inft.waitForDeployment();

  const address = await inft.getAddress();
  console.log(`HivemindINFT deployed to ${address}`);
  console.log(`Minter set to ${deployer.address}`);
}

main().catch((error) => {
  console.error(error);
  process.exitCode = 1;
});
