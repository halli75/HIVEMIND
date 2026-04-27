import hivemind
import os
import signal

PORT = int(os.environ.get("BOOTNODE_PORT", "30021"))
SERVICE_NAME = os.environ.get("BOOTNODE_SERVICE_NAME", "hivemind-bootnode")
ADDR_FILE = os.environ.get("BOOTNODE_ADDR_FILE", "")

dht = hivemind.DHT(start=True, host_maddrs=[f"/ip4/0.0.0.0/tcp/{PORT}"])
maddrs = dht.get_visible_maddrs(latest=True)
peer_id = str(maddrs[0]).split("/p2p/")[-1]
canonical = f"/dns4/{SERVICE_NAME}/tcp/{PORT}/p2p/{peer_id}"

print(f"BOOTNODE_PEER_ID={peer_id}", flush=True)
print(f"BOOTNODE_ADDR={canonical}", flush=True)

if ADDR_FILE:
    os.makedirs(os.path.dirname(ADDR_FILE) or ".", exist_ok=True)
    with open(ADDR_FILE, "w") as f:
        f.write(canonical)

signal.pause()
