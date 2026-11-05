"""Micro-experiment: specialised child selection for small arities."""
from __future__ import annotations

import random
import time

VALUES = [random.randrange(1 << 30) for _ in range(20000)]


def baseline_loop(prio, store, index, size, shift, arity):
    item = store[index]
    priority = prio[index]
    while True:
        first_child = (index << shift) + 1
        if first_child >= size:
            break
        limit = first_child + arity
        if limit > size:
            limit = size
        best = first_child
        best_priority = prio[first_child]
        for candidate in range(first_child + 1, limit):
            candidate_priority = prio[candidate]
            if candidate_priority < best_priority:
                best = candidate
                best_priority = candidate_priority
        if not (best_priority < priority):
            break
        prio[index] = best_priority
        store[index] = store[best]
        index = best
    prio[index] = priority
    store[index] = item


def slice_variant(prio, store, index, size, shift, arity):
    item = store[index]
    priority = prio[index]
    while True:
        first_child = (index << shift) + 1
        if first_child >= size:
            break
        limit = first_child + arity
        if limit > size:
            limit = size
        window = prio[first_child:limit]
        best_priority = min(window)
        if not (best_priority < priority):
            break
        best = first_child + window.index(best_priority)
        prio[index] = best_priority
        store[index] = store[best]
        index = best
    prio[index] = priority
    store[index] = item


def binary_specialised(prio, store, index, size):
    """Hand-unrolled binary heap sift-down (arity 2)."""
    item = store[index]
    priority = prio[index]
    while True:
        child = (index << 1) + 1
        if child >= size:
            break
        right = child + 1
        if right < size and prio[right] < prio[child]:
            child = right
        best_priority = prio[child]
        if not (best_priority < priority):
            break
        prio[index] = best_priority
        store[index] = store[child]
        index = child
    prio[index] = priority
    store[index] = item


def run(fn, arity, shift, iterations=5, specialised=False):
    best = float("inf")
    for _ in range(iterations):
        prio = list(VALUES)
        store = list(VALUES)
        n = len(prio)
        for i in range(n // 2 - 1, -1, -1):
            baseline_loop(prio, store, i, n, shift, arity)
        start = time.perf_counter()
        for i in range(n // 2 - 1, -1, -1):
            if specialised:
                fn(prio, store, i, n)
            else:
                fn(prio, store, i, n, shift, arity)
        best = min(best, time.perf_counter() - start)
    return best


for arity, shift in ((2, 1), (4, 2), (8, 3), (16, 4)):
    base = run(baseline_loop, arity, shift)
    slc = run(slice_variant, arity, shift)
    line = f"arity={arity:>2}  loop={base * 1000:7.2f}ms  slice={slc * 1000:7.2f}ms"
    if arity == 2:
        spec = run(binary_specialised, arity, shift, specialised=True)
        line += f"  binary_specialised={spec * 1000:7.2f}ms"
    print(line)
