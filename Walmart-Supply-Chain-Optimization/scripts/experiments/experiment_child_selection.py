"""Micro-experiment: compare child-selection strategies in _sift_down."""
from __future__ import annotations

import random
import time

VALUES = [random.randrange(1 << 30) for _ in range(20000)]


def sift_down_loop(prio, store, index, size, shift, arity):
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


def sift_down_min_slice(prio, store, index, size, shift, arity):
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


def sift_down_min_key(prio, store, index, size, shift, arity):
    item = store[index]
    priority = prio[index]
    getter = prio.__getitem__
    while True:
        first_child = (index << shift) + 1
        if first_child >= size:
            break
        limit = first_child + arity
        if limit > size:
            limit = size
        best = min(range(first_child, limit), key=getter)
        best_priority = prio[best]
        if not (best_priority < priority):
            break
        prio[index] = best_priority
        store[index] = store[best]
        index = best
    prio[index] = priority
    store[index] = item


def run(fn, arity, shift, iterations=3):
    best = float("inf")
    for _ in range(iterations):
        prio = list(VALUES)
        store = list(VALUES)
        n = len(prio)
        # build a valid heap first
        for i in range(n // 2 - 1, -1, -1):
            sift_down_loop(prio, store, i, n, shift, arity)
        start = time.perf_counter()
        for i in range(n // 2 - 1, -1, -1):
            fn(prio, store, i, n, shift, arity)
        elapsed = time.perf_counter() - start
        best = min(best, elapsed)
    return best


for arity, shift in ((2, 1), (4, 2), (8, 3), (16, 4)):
    loop_t = run(sift_down_loop, arity, shift)
    slice_t = run(sift_down_min_slice, arity, shift)
    key_t = run(sift_down_min_key, arity, shift)
    print(
        f"arity={arity:>2}  loop={loop_t * 1000:8.2f}ms  "
        f"min_slice={slice_t * 1000:8.2f}ms  min_key={key_t * 1000:8.2f}ms"
    )
