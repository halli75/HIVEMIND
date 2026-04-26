import hardhatEthers from "@nomicfoundation/hardhat-ethers";
import { defineConfig } from "hardhat/config";
import "dotenv/config";

const zerogGalileoRpcUrl =
  process.env.ZERO_G_RPC_URL || "https://evmrpc-testnet.0g.ai";

const deployerPrivateKey = process.env.DEPLOYER_PRIVATE_KEY;
const accounts = deployerPrivateKey ? [deployerPrivateKey] : [];

export default defineConfig({
  plugins: [hardhatEthers],
  solidity: {
    profiles: {
      default: {
        version: "0.8.24",
        settings: {
          optimizer: {
            enabled: true,
            runs: 200
          }
        }
      }
    }
  },
  networks: {
    hardhat: {
      type: "edr-simulated",
      chainType: "l1",
      chainId: 31337
    },
    zerogGalileo: {
      type: "http",
      chainType: "l1",
      url: zerogGalileoRpcUrl,
      chainId: 16602,
      accounts
    }
  }
});
