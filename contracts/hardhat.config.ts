import hardhatEthers from "@nomicfoundation/hardhat-ethers";
import { defineConfig } from "hardhat/config";
import { config as dotenvConfig } from "dotenv";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

// Load root .env (one level up from contracts/)
const _dir = dirname(fileURLToPath(import.meta.url));
dotenvConfig({ path: resolve(_dir, "../.env") });

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
