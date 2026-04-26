from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SDK_SRC = ROOT / "packages" / "hivemind-sdk" / "src"
AXL_SRC = ROOT / "apps" / "axl-node" / "src"

for path in (SDK_SRC, AXL_SRC):
    sys.path.insert(0, str(path))
