"""Verify every code example quoted in the README actually works."""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "..", "src"))

from walmart_logistics import DispatchConfig, KaryHeap, SimulationRunner
from walmart_logistics.cli import main

# --- the data structure on its own ---
queue = KaryHeap[str](arity_exponent=3)  # 8-ary min-heap
queue.push("parcel")
queue.push("pallet")
assert queue.peek() == "pallet", queue.peek()
assert queue.pop() == "pallet"

# --- with an explicit priority (max-heap) ---
urgent = KaryHeap[str](arity_exponent=3, key=len, reverse=True)
urgent.push("a")
urgent.push("cccc")
assert urgent.pop() == "cccc"

# --- the dispatch simulation ---
config = DispatchConfig(packages=5_000, trucks=250, arity_exponent=3)
result = SimulationRunner(config).run()
print("on_time_ratio:", result.metrics.on_time_ratio)

# --- CLI invocation form used in the README ---
assert main(["--packages", "50", "--trucks", "5"]) == 0

print("README examples OK")
