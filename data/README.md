# Data Seeds

These JSON files are deterministic local snapshots for simulation, tests, and UI wiring. They do not contain live API keys, wallet secrets, or production market data.

- `snapshots/agents.seed.json`: sample swarm agents, AIQ scores, risk fields, and iNFT storage references.
- `snapshots/gensyn-messages.seed.json`: mock typed AXL-style messages between two node processes.
- `snapshots/zerog-storage.seed.json`: testnet storage object references for 0G read/write simulation.
- `snapshots/uniswap-quote.seed.json`: mock Sepolia quote shape for the Uniswap API integration path.

Use these seeds until the live workers replace individual records with verified run artifacts.
