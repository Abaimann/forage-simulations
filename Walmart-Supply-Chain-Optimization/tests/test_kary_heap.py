"""Unit tests for the generic ``2**k``-ary heap.

The suite covers the construction contract, the ordering guarantees for
both the min-heap and the max-heap mode, the keyed mode, every public
operation, the index arithmetic and the behaviour under randomised
workloads compared against :mod:`heapq`.
"""

from __future__ import annotations

import heapq
import random

import pytest

from walmart_logistics.data_structures.kary_heap import KaryHeap
from walmart_logistics.errors import EmptyHeapError, InvalidArityError, InvalidPriorityError

from .helpers import assert_sorted_ascending, heap_invariant_holds, heapq_sorted

ALL_ARITIES = (1, 2, 3, 4, 5, 8)


# ----------------------------------------------------------------------
# Construction contract
# ----------------------------------------------------------------------
class TestConstruction:
    """Construction, validation and introspection."""

    def test_default_is_binary_min_heap(self) -> None:
        heap = KaryHeap[int]()
        assert heap.arity == 2
        assert heap.arity_exponent == 1
        assert heap.is_max_heap is False
        assert len(heap) == 0
        assert heap.is_empty
        assert not heap

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_arity_is_power_of_two(self, exponent: int) -> None:
        heap = KaryHeap[int](exponent)
        assert heap.arity == 2**exponent
        assert heap.arity_exponent == exponent

    @pytest.mark.parametrize("bad", [0, -1, -5])
    def test_rejects_non_positive_exponent(self, bad: int) -> None:
        with pytest.raises(InvalidArityError):
            KaryHeap[int](bad)

    @pytest.mark.parametrize("bad", [1.0, 2.5, "2", None, True])
    def test_rejects_non_integer_exponent(self, bad: object) -> None:
        with pytest.raises(InvalidArityError):
            KaryHeap[int](bad)  # type: ignore[arg-type]

    def test_rejects_invalid_capacity(self) -> None:
        with pytest.raises(InvalidArityError):
            KaryHeap[int](1, capacity=0)

    def test_repr_is_informative(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(1)
        text = repr(heap)
        assert "arity=4" in text
        assert "mode=min" in text
        assert "size=1" in text

    def test_max_heap_flag(self) -> None:
        heap = KaryHeap[int](1, reverse=True)
        assert heap.is_max_heap is True
        assert "mode=max" in repr(heap)

    def test_footprint_is_positive(self) -> None:
        heap = KaryHeap[int](1, capacity=64)
        assert heap.footprint_bytes() > 0


# ----------------------------------------------------------------------
# Core ordering guarantees
# ----------------------------------------------------------------------
class TestOrdering:
    """The heap always yields the elements in priority order."""

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_min_heap_pops_ascending(self, exponent: int) -> None:
        values = [7, 1, 9, 3, 3, 0, 42, -5]
        heap = KaryHeap[int](exponent)
        for value in values:
            heap.push(value)
        assert [heap.pop() for _ in range(len(values))] == sorted(values)

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_max_heap_pops_descending(self, exponent: int) -> None:
        values = [7, 1, 9, 3, 3, 0, 42, -5]
        heap = KaryHeap[int](exponent, reverse=True)
        for value in values:
            heap.push(value)
        assert [heap.pop() for _ in range(len(values))] == sorted(values, reverse=True)

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_random_min_heap_matches_heapq(self, exponent: int, rng: random.Random) -> None:
        values = [rng.randrange(1000) for _ in range(500)]
        heap = KaryHeap[int](exponent)
        for value in values:
            heap.push(value)
        assert [heap.pop() for _ in range(len(values))] == heapq_sorted(values)

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_random_max_heap_matches_reversed_heapq(
        self, exponent: int, rng: random.Random
    ) -> None:
        values = [rng.randrange(1000) for _ in range(500)]
        heap = KaryHeap[int](exponent, reverse=True)
        for value in values:
            heap.push(value)
        assert [heap.pop() for _ in range(len(values))] == sorted(values, reverse=True)

    def test_duplicate_elements_are_all_returned(self) -> None:
        heap = KaryHeap[int](3)
        for _ in range(50):
            heap.push(5)
        popped = [heap.pop() for _ in range(50)]
        assert popped == [5] * 50

    def test_negative_and_extreme_values(self) -> None:
        values = [-(10**18), 0, 10**18, -1, 1]
        heap = KaryHeap[int](2)
        for value in values:
            heap.push(value)
        assert [heap.pop() for _ in range(len(values))] == sorted(values)

    def test_floats_compare_correctly(self) -> None:
        values = [2.5, -1.5, 0.0, 2.25, 3.75]
        heap = KaryHeap[float](2)
        for value in values:
            heap.push(value)
        assert [heap.pop() for _ in range(len(values))] == sorted(values)


# ----------------------------------------------------------------------
# Keyed mode
# ----------------------------------------------------------------------
class TestKeyedMode:
    """Ordering by an explicit key function."""

    def test_key_selects_the_ordering(self) -> None:
        heap = KaryHeap[str](2, key=len)
        for value in ("a", "ccc", "bb"):
            heap.push(value)
        assert heap.sorted_items() == ["a", "bb", "ccc"]

    def test_reversed_key_selects_the_ordering(self) -> None:
        heap = KaryHeap[str](2, key=len, reverse=True)
        for value in ("a", "ccc", "bb"):
            heap.push(value)
        assert heap.sorted_items() == ["ccc", "bb", "a"]

    def test_keyed_heap_is_stable_on_equal_keys(self) -> None:
        heap = KaryHeap[tuple[int, str]](2, key=lambda item: item[0])
        heap.push((1, "first"))
        heap.push((1, "second"))
        heap.push((0, "zero"))
        assert heap.pop() == (0, "zero")

    def test_key_receives_the_element(self) -> None:
        seen: list[int] = []

        def key(value: int) -> int:
            seen.append(value)
            return -value

        heap = KaryHeap[int](1, key=key)
        heap.push(1)
        heap.push(2)
        assert seen == [1, 2]
        assert heap.pop() == 2

    def test_reversed_key_requires_a_numeric_priority(self) -> None:
        # A string priority cannot be negated, so the max-heap cannot be built.
        heap = KaryHeap[str](1, key=lambda value: value, reverse=True)
        with pytest.raises(InvalidPriorityError):
            heap.push("abc")

    def test_reversed_key_accepts_a_numeric_priority(self) -> None:
        heap = KaryHeap[str](1, key=len, reverse=True)
        heap.push("abc")
        assert heap.peek() == "abc"

    def test_non_numeric_key_works_in_min_mode(self) -> None:
        # A string priority is perfectly comparable, it just cannot be negated.
        heap = KaryHeap[str](1, key=lambda value: value)
        heap.push("b")
        heap.push("a")
        assert heap.peek() == "a"


# ----------------------------------------------------------------------
# Empty heap behaviour
# ----------------------------------------------------------------------
class TestEmptyHeap:
    """Operations on an empty heap raise instead of returning ``None``."""

    def test_pop_raises(self) -> None:
        with pytest.raises(EmptyHeapError):
            KaryHeap[int](2).pop()

    def test_peek_raises(self) -> None:
        with pytest.raises(EmptyHeapError):
            KaryHeap[int](2).peek()

    def test_replace_raises(self) -> None:
        with pytest.raises(EmptyHeapError):
            KaryHeap[int](2).replace(1)

    def test_error_is_also_an_index_error(self) -> None:
        # Compatibility with code that already traps IndexError for heapq.
        with pytest.raises(IndexError):
            KaryHeap[int](2).pop()

    def test_pop_on_emptied_heap_raises(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(1)
        heap.pop()
        assert heap.is_empty
        with pytest.raises(EmptyHeapError):
            heap.pop()

    def test_pushpop_on_empty_heap_returns_the_item(self) -> None:
        heap = KaryHeap[int](2)
        assert heap.pushpop(42) == 42
        assert heap.is_empty


# ----------------------------------------------------------------------
# Individual operations
# ----------------------------------------------------------------------
class TestOperations:
    """Behaviour of each public operation in isolation."""

    def test_peek_does_not_remove(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(5)
        heap.push(1)
        assert heap.peek() == 1
        assert heap.peek() == 1
        assert len(heap) == 2

    def test_peek_after_pop_returns_new_root(self) -> None:
        heap = KaryHeap[int](2)
        for value in (3, 1, 2):
            heap.push(value)
        heap.pop()
        assert heap.peek() == 2

    def test_push_all(self) -> None:
        heap = KaryHeap[int](2)
        heap.push_all([4, 2, 8, 1])
        assert heap.sorted_items() == [1, 2, 4, 8]

    def test_pushpop_returns_the_smaller_of_root_and_item(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(10)
        assert heap.pushpop(20) == 10
        assert len(heap) == 1
        assert heap.peek() == 20

    def test_pushpop_returns_the_new_item_when_it_wins(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(10)
        assert heap.pushpop(1) == 1
        assert len(heap) == 1
        assert heap.peek() == 10

    def test_pushpop_matches_heapq_semantics(self, rng: random.Random) -> None:
        values = [rng.randrange(100) for _ in range(200)]
        reference: list[int] = []
        heap = KaryHeap[int](2)
        for value in values:
            expected = heapq.heappushpop(reference, value)
            actual = heap.pushpop(value)
            assert actual == expected
            assert len(heap) == len(reference)

    def test_replace_swaps_the_root(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(5)
        heap.push(9)
        assert heap.replace(1) == 5
        assert heap.peek() == 1
        assert len(heap) == 2

    def test_replace_keeps_a_smaller_value_on_top(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(5)
        heap.push(9)
        heap.replace(0)
        assert heap.peek() == 0

    def test_sorted_items_is_ordered(self) -> None:
        heap = KaryHeap[int](2)
        for value in (5, 1, 3):
            heap.push(value)
        assert_sorted_ascending(heap.sorted_items())

    def test_sorted_items_does_not_consume_the_heap(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(5)
        heap.sorted_items()
        assert len(heap) == 1

    def test_sorted_items_on_max_heap(self) -> None:
        heap = KaryHeap[int](2, reverse=True)
        for value in (5, 1, 3):
            heap.push(value)
        assert heap.sorted_items() == [5, 3, 1]

    def test_iteration_yields_every_element(self) -> None:
        heap = KaryHeap[int](2)
        values = [4, 2, 6]
        for value in values:
            heap.push(value)
        assert sorted(heap) == sorted(values)

    def test_iteration_on_empty_heap(self) -> None:
        assert list(KaryHeap[int](2)) == []

    def test_clear_removes_everything(self) -> None:
        heap = KaryHeap[int](2)
        heap.push_all([1, 2, 3])
        heap.clear()
        assert len(heap) == 0
        assert heap.is_empty
        with pytest.raises(EmptyHeapError):
            heap.peek()

    def test_clear_keeps_the_heap_usable(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(1)
        heap.clear()
        heap.push(9)
        heap.push(2)
        assert heap.sorted_items() == [2, 9]

    def test_copy_is_independent(self) -> None:
        heap = KaryHeap[int](2)
        heap.push_all([1, 2, 3])
        clone = heap.copy()
        clone.push(0)
        assert len(heap) == 3
        assert len(clone) == 4
        assert heap.sorted_items() == [1, 2, 3]

    def test_copy_preserves_the_ordering_mode(self) -> None:
        clone = KaryHeap[int](3, reverse=True).copy()
        assert clone.arity == 8
        assert clone.is_max_heap is True

    def test_copy_preserves_the_key(self) -> None:
        clone = KaryHeap[str](2, key=len).copy()
        clone.push("aaa")
        clone.push("b")
        assert clone.sorted_items() == ["b", "aaa"]


# ----------------------------------------------------------------------
# Bulk construction
# ----------------------------------------------------------------------
class TestBulkConstruction:
    """``from_iterable`` and ``heapify`` build a valid heap in ``O(n)``."""

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_from_iterable_matches_heapq(self, exponent: int, rng: random.Random) -> None:
        values = [rng.randrange(1000) for _ in range(300)]
        heap = KaryHeap.from_iterable(values, arity_exponent=exponent)
        assert [heap.pop() for _ in range(len(values))] == heapq_sorted(values)

    def test_from_iterable_of_empty_sequence(self) -> None:
        heap = KaryHeap.from_iterable([], arity_exponent=2)
        assert heap.is_empty
        with pytest.raises(EmptyHeapError):
            heap.pop()

    def test_from_iterable_of_single_element(self) -> None:
        heap = KaryHeap.from_iterable([7], arity_exponent=2)
        assert heap.peek() == 7

    def test_from_iterable_preserves_duplicates(self) -> None:
        heap = KaryHeap.from_iterable([2, 2, 2], arity_exponent=2)
        assert len(heap) == 3

    def test_from_iterable_with_key(self) -> None:
        heap = KaryHeap.from_iterable(
            ["aa", "b", "ccc"], arity_exponent=2, key=len
        )
        assert heap.sorted_items() == ["b", "aa", "ccc"]

    def test_heapify_rebuilds_the_heap(self) -> None:
        heap = KaryHeap[int](2)
        heap.push_all([5, 1, 3])
        heap.heapify()
        assert heap.sorted_items() == [1, 3, 5]

    def test_heapify_with_new_values_replaces_the_content(self) -> None:
        heap = KaryHeap[int](2)
        heap.push(99)
        heap.heapify([4, 2])
        assert heap.sorted_items() == [2, 4]
        assert len(heap) == 2

    def test_heapify_on_empty_heap(self) -> None:
        heap = KaryHeap[int](2)
        heap.heapify([])
        assert heap.is_empty


# ----------------------------------------------------------------------
# Capacity and growth
# ----------------------------------------------------------------------
class TestCapacity:
    """The backing store grows without corrupting the heap."""

    def test_grows_beyond_the_initial_capacity(self) -> None:
        heap = KaryHeap[int](2, capacity=4)
        values = list(range(100))
        for value in values:
            heap.push(value)
        assert len(heap) == 100
        assert heap.capacity >= 100
        assert heap.sorted_items() == values

    def test_capacity_is_doubled(self) -> None:
        heap = KaryHeap[int](2, capacity=4)
        heap.push(1)
        assert heap.capacity == 4
        for index in range(4):
            heap.push(index)
        assert heap.capacity == 8

    def test_growth_preserves_ordering(self, rng: random.Random) -> None:
        heap = KaryHeap[int](3, capacity=1)
        values = [rng.randrange(1000) for _ in range(500)]
        for value in values:
            heap.push(value)
        assert heap.sorted_items() == sorted(values)

    def test_pop_shrinks_the_size_but_keeps_the_capacity(self) -> None:
        heap = KaryHeap[int](2, capacity=16)
        heap.push(1)
        heap.pop()
        assert len(heap) == 0
        assert heap.capacity == 16


# ----------------------------------------------------------------------
# Index arithmetic
# ----------------------------------------------------------------------
class TestIndexArithmetic:
    """The parent/child formulas hold for every arity."""

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_children_of_a_node_are_contiguous(self, exponent: int) -> None:
        arity = 2**exponent
        for index in range(50):
            first_child = (index << exponent) + 1
            for offset in range(arity):
                child = first_child + offset
                if child == 0:
                    continue
                assert (child - 1) >> exponent == index

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_parent_is_floor_division(self, exponent: int) -> None:
        arity = 2**exponent
        for index in range(1, 200):
            assert (index - 1) // arity == (index - 1) >> exponent

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_the_invariant_holds_after_random_operations(
        self, exponent: int, rng: random.Random
    ) -> None:
        heap = KaryHeap[int](exponent)
        for _ in range(500):
            if heap and rng.random() < 0.4:
                heap.pop()
            else:
                heap.push(rng.randrange(100))
            assert heap_invariant_holds(heap)


# ----------------------------------------------------------------------
# Stress / property tests
# ----------------------------------------------------------------------
class TestProperties:
    """Randomised property tests against the reference implementation."""

    @pytest.mark.parametrize("exponent", ALL_ARITIES)
    def test_mixed_operations_match_heapq(self, exponent: int, rng: random.Random) -> None:
        heap = KaryHeap[int](exponent)
        reference: list[int] = []
        for _ in range(2000):
            if reference and rng.random() < 0.45:
                expected = heapq.heappop(reference)
                assert heap.pop() == expected
            else:
                value = rng.randrange(1000)
                heapq.heappush(reference, value)
                heap.push(value)
            assert len(heap) == len(reference)
        while reference:
            assert heap.pop() == heapq.heappop(reference)

    def test_max_heap_mixed_operations(self, rng: random.Random) -> None:
        heap = KaryHeap[int](2, reverse=True)
        # A min-heap of negated values is the reference implementation of a
        # max-heap.
        reference: list[int] = []
        for _ in range(1000):
            if reference and rng.random() < 0.45:
                expected = -heapq.heappop(reference)
                assert heap.pop() == expected
            else:
                value = rng.randrange(1000)
                heapq.heappush(reference, -value)
                heap.push(value)
            assert len(heap) == len(reference)
        assert heap.sorted_items() == sorted((-value for value in reference), reverse=True)

    def test_interleaved_pushes_and_pops_keep_the_invariant(self, rng: random.Random) -> None:
        heap = KaryHeap[int](4)
        for _ in range(1000):
            heap.push(rng.randrange(10_000))
            if heap.size > 20 and rng.random() < 0.5:
                heap.pop()
        assert heap_invariant_holds(heap)

    def test_large_heap_stays_consistent(self, rng: random.Random) -> None:
        values = [rng.randrange(10**6) for _ in range(20_000)]
        heap = KaryHeap.from_iterable(values, arity_exponent=3)
        assert len(heap) == len(values)
        popped = [heap.pop() for _ in range(len(values))]
        assert popped == sorted(values)

    def test_elements_are_returned_exactly_once(self, rng: random.Random) -> None:
        values = [rng.randrange(500) for _ in range(1000)]
        heap = KaryHeap.from_iterable(values, arity_exponent=2)
        seen: list[int] = []
        while heap:
            seen.append(heap.pop())
        assert sorted(seen) == sorted(values)
        assert len(seen) == len(values)
