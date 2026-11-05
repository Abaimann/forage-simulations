"""Probe heapq.heappushpop semantics."""
import heapq

ref = []
for v in [5, 3, 9, 1]:
    out = heapq.heappushpop(ref, v)
    print(f"pushpop({v}) -> {out}, heap={ref}")

print("---")
empty = []
print("empty pushpop ->", heapq.heappushpop(empty, 42), "heap:", empty)

print("---")
h = [1, 2, 3]
print("pushpop(0) ->", heapq.heappushpop(h, 0), "heap:", h)
print("pushpop(99) ->", heapq.heappushpop(h, 99), "heap:", h)
