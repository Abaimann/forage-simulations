"""Generic power-of-two (``2**k``-ary) heap with a cache-conscious layout.

Why not just use :mod:`heapq`?
------------------------------
``heapq`` implements a *binary* heap.  Its sift-down performs ``log2(n)``
levels, and every level requires two random memory accesses: one for the
left child and one for the right child.  On a large heap those two accesses
usually land on two different cache lines, and both are almost always
*cache misses* for heaps bigger than the L2 cache.

A ``d``-ary heap with ``d = 2**k`` trades the number of tree levels for the
number of children per level:

* ``push`` / ``pop`` traverse ``log_d(n) = log2(n) / k`` levels instead of
  ``log2(n)``.  With ``d = 8`` the tree is three times shallower.
* The children of node ``i`` occupy the *contiguous* index range
  ``[d*i + 1, d*i + d]``, so a whole sibling group is usually served by one
  or two cache lines instead of ``d`` scattered ones.

The number of *comparisons* per level grows (``d - 1`` to find the best
child), but comparisons are cheap and predictable while cache misses are
expensive and unpredictable.  That trade-off is what makes the ``d``-ary
heap win on real workloads.

Implementation notes (these are the actual optimisations)
---------------------------------------------------------
1. **Split storage.**  Elements and priorities live in two parallel arrays.
   The sift-down loop only ever touches the *priority* array, so the hot
   loop streams over a dense array of small numbers instead of chasing
   pointers into tuples/objects.
2. **Shift-based index arithmetic.**  With ``d = 2**k`` the parent of ``i``
   is ``(i - 1) >> k`` and the first child is ``(i << k) + 1``.  Bit shifts
   replace the multiplication/division of the general ``d``-ary heap.
3. **Hole-based sifting.**  Elements are moved *through* a hole instead of
   being swapped, so every level performs a single write instead of three.
4. **Early exit.**  ``sift_up`` stops at the first level that is already
   ordered, and ``sift_down`` stops as soon as the element fits.
5. **Fixed-capacity backing store.**  The store is pre-allocated and grown
   by doubling, which keeps memory predictable and lets the caller cap the
   footprint explicitly.

Genericity
----------
The heap is generic over the element type ``T`` and supports two ordering
modes:

* *element mode* (``key=None``): elements are compared with ``<`` directly.
* *keyed mode* (``key=callable``): the callable maps an element to a
  numeric priority and the elements are compared by that priority.

A reversed (max) heap is requested with ``reverse=True``.  Internally the
heap always maintains the *min*-heap invariant on its priority array, so
there is exactly one sift implementation and no comparison branches inside
the hot loops.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Any, Generic, Protocol, TypeVar, cast, runtime_checkable

from walmart_logistics.errors import (
    EmptyHeapError,
    InvalidArityError,
    InvalidPriorityError,
)

__all__ = ["KaryHeap", "MIN_HEAP", "MAX_HEAP"]

T = TypeVar("T")

#: Default minimum capacity of a heap (matches a small binary heap).
MIN_HEAP = "min"
#: Alias documenting the reversed mode.
MAX_HEAP = "max"

_MODE_ELEMENT = 0
_MODE_ELEMENT_REVERSED = 1
_MODE_KEYED = 2
_MODE_KEYED_REVERSED = 3

#: Number of slots pre-allocated for a new heap.
DEFAULT_CAPACITY = 16


@runtime_checkable
class Comparable(Protocol):
    """Structural type of a value that supports the ``<`` operator."""

    def __lt__(self, other: object) -> bool:  # pragma: no cover - protocol
        ...


class _Reversed:
    """Adapter that inverts the natural ordering of the wrapped value.

    Used for reversed *element mode* heaps, where the priority is the
    element itself and therefore cannot be negated.
    """

    __slots__ = ("value",)

    def __init__(self, value: object) -> None:
        self.value = value

    def __lt__(self, other: _Reversed) -> bool:
        if not isinstance(other, _Reversed):  # pragma: no cover - defensive
            return NotImplemented
        if not isinstance(other.value, Comparable) or not isinstance(self.value, Comparable):
            return NotImplemented  # pragma: no cover - defensive
        return bool(other.value < self.value)

    def __repr__(self) -> str:  # pragma: no cover - debugging helper
        return f"_Reversed({self.value!r})"


class KaryHeap(Generic[T]):
    """A generic ``2**k``-ary min/max heap.

    Args:
        arity_exponent: ``k`` in ``d = 2**k``.  Must be an integer ``>= 1``;
            ``k = 1`` is a classic binary heap, ``k = 3`` is an 8-ary heap.
        key: Optional callable mapping an element to a comparable priority.
            When omitted the elements themselves are compared with ``<``.
            A reversed (max) heap additionally requires the priority to
            support unary minus.
        reverse: When ``True`` the heap behaves as a max-heap.
        capacity: Initial number of pre-allocated slots.  The store grows
            by doubling when it overflows, so ``capacity`` only influences
            the memory profile, never correctness.

    Raises:
        InvalidArityError: If ``arity_exponent`` is not an integer ``>= 1``.
        InvalidPriorityError: If ``key`` does not return a number while
            ``reverse=True``.

    Example:
        >>> heap = KaryHeap[int](arity_exponent=2)
        >>> for value in (5, 1, 4, 1, 3):
        ...     heap.push(value)
        >>> [heap.pop() for _ in range(5)]
        [1, 1, 3, 4, 5]
    """

    __slots__ = ("_store", "_prio", "_size", "_capacity", "_shift", "_arity", "_mode", "_key")

    def __init__(
        self,
        arity_exponent: int = 1,
        *,
        key: Callable[[T], Any] | None = None,
        reverse: bool = False,
        capacity: int = DEFAULT_CAPACITY,
    ) -> None:
        if isinstance(arity_exponent, bool) or not isinstance(arity_exponent, int):
            raise InvalidArityError(
                "arity_exponent must be an integer, "
                f"got {type(arity_exponent).__name__}"
            )
        if arity_exponent < 1:
            raise InvalidArityError(
                f"arity_exponent must be >= 1 (arity = 2**k), got {arity_exponent}"
            )
        if capacity < 1:
            raise InvalidArityError(f"capacity must be >= 1, got {capacity}")

        self._shift = arity_exponent
        self._arity = 1 << arity_exponent
        self._capacity = capacity
        self._store: list[T | None] = [None] * capacity
        self._prio: list[Any] = [None] * capacity
        self._size = 0
        self._key = key

        if key is None:
            self._mode = _MODE_ELEMENT_REVERSED if reverse else _MODE_ELEMENT
        else:
            self._mode = _MODE_KEYED_REVERSED if reverse else _MODE_KEYED

    # ------------------------------------------------------------------
    # Introspection
    # ------------------------------------------------------------------
    @property
    def arity(self) -> int:
        """Number of children per node (``d = 2**k``)."""
        return self._arity

    @property
    def arity_exponent(self) -> int:
        """The exponent ``k`` such that ``arity == 2**k``."""
        return self._shift

    @property
    def is_max_heap(self) -> bool:
        """``True`` when the heap was created with ``reverse=True``."""
        return self._mode in (_MODE_ELEMENT_REVERSED, _MODE_KEYED_REVERSED)

    @property
    def size(self) -> int:
        """Number of elements currently stored."""
        return self._size

    @property
    def capacity(self) -> int:
        """Number of pre-allocated slots."""
        return self._capacity

    @property
    def is_empty(self) -> bool:
        """``True`` when the heap holds no element."""
        return self._size == 0

    def footprint_bytes(self) -> int:
        """Approximate memory footprint of the backing store, in bytes."""
        import sys

        return sys.getsizeof(self._store) + sys.getsizeof(self._prio)

    def __len__(self) -> int:
        return self._size

    def __bool__(self) -> bool:
        return self._size > 0

    def __repr__(self) -> str:
        mode = "max" if self.is_max_heap else "min"
        return (
            f"KaryHeap(arity={self._arity}, mode={mode}, "
            f"size={self._size}, capacity={self._capacity})"
        )

    # ------------------------------------------------------------------
    # Priority handling
    # ------------------------------------------------------------------
    def _make_priority(self, item: T) -> object:
        """Return the *min-oriented* priority used for internal ordering."""
        mode = self._mode
        if mode == _MODE_ELEMENT:
            return item
        if mode == _MODE_ELEMENT_REVERSED:
            return _Reversed(item)
        key = self._key
        assert key is not None  # narrowed by construction
        value = key(item)
        if mode == _MODE_KEYED:
            return value
        try:
            return -value
        except TypeError as exc:
            raise InvalidPriorityError(
                "a reversed (max) heap requires key() to return a number "
                "that supports unary minus"
            ) from exc

    # ------------------------------------------------------------------
    # Core heap operations
    # ------------------------------------------------------------------
    def push(self, item: T) -> None:
        """Insert ``item`` into the heap.

        Time complexity: ``O(log_d n)`` in the worst case, ``O(1)`` if the
        element is not smaller than its parent.
        """
        priority = self._make_priority(item)
        size = self._size
        if size == self._capacity:
            self._grow()
        self._store[size] = item
        self._prio[size] = priority
        self._size = size + 1
        self._sift_up(size)

    def pop(self) -> T:
        """Remove and return the highest-priority element.

        Time complexity: ``O(log_d n)``.

        Raises:
            EmptyHeapError: If the heap is empty.
        """
        size = self._size
        if size == 0:
            raise EmptyHeapError("pop from an empty heap")
        item = self._store[0]
        self._size = size - 1
        if size > 1:
            self._store[0] = self._store[size - 1]
            self._prio[0] = self._prio[size - 1]
        # Release the references so the element can be garbage collected.
        self._store[size - 1] = None
        self._prio[size - 1] = None
        if self._size > 0:
            self._sift_down(0)
        return item  # type: ignore[return-value]

    def peek(self) -> T:
        """Return the highest-priority element without removing it.

        Time complexity: ``O(1)``.

        Raises:
            EmptyHeapError: If the heap is empty.
        """
        if self._size == 0:
            raise EmptyHeapError("peek from an empty heap")
        return self._store[0]  # type: ignore[return-value]

    def pushpop(self, item: T) -> T:
        """Push ``item`` and return the highest-priority element.

        Mirrors :func:`heapq.heappushpop` exactly: the heap size does not
        change and the returned element is the best of the heap *after* the
        insertion.

        * On an empty heap the item is returned and the heap stays empty,
          exactly like :func:`heapq.heappushpop`.
        * If ``item`` outranks the current root it is returned immediately
          and the heap is left untouched (``O(1)``).
        * Otherwise the root is evicted, ``item`` takes its place and the
          heap is repaired with a single sift-down (``O(log_d n)``).

        Raises:
            InvalidPriorityError: If the priority of ``item`` cannot be
                derived (see :meth:`_make_priority`).
        """
        if self._size == 0:
            # heapq.heappushpop on an empty heap returns the item and
            # leaves the heap empty.
            self._make_priority(item)  # validates the priority eagerly
            return item
        priority = self._make_priority(item)
        root_priority = self._prio[0]
        if priority < root_priority:
            # The newcomer is the new minimum: it is returned right away and
            # the heap content stays exactly the same.
            return item
        # The root wins: evict it, install the newcomer and repair.
        evicted = self._store[0]
        self._store[0] = item
        self._prio[0] = priority
        self._sift_down(0)
        return evicted  # type: ignore[return-value]

    def replace(self, item: T) -> T:
        """Pop the root and push ``item`` in a single sift operation.

        Time complexity: ``O(log_d n)``.

        Raises:
            EmptyHeapError: If the heap is empty.
        """
        if self._size == 0:
            raise EmptyHeapError("replace on an empty heap")
        evicted = self._store[0]
        priority = self._make_priority(item)
        self._store[0] = item
        self._prio[0] = priority
        self._sift_down(0)
        return evicted  # type: ignore[return-value]

    def push_all(self, items: Iterable[T]) -> None:
        """Insert every element of ``items``.

        Time complexity: ``O(m log_d n)``.
        """
        for item in items:
            self.push(item)

    @classmethod
    def from_iterable(
        cls,
        items: Iterable[T],
        *,
        arity_exponent: int = 1,
        key: Callable[[T], float] | None = None,
        reverse: bool = False,
    ) -> KaryHeap[T]:
        """Build a heap from ``items`` in ``O(n)`` using bottom-up heapify.

        Example:
            >>> KaryHeap.from_iterable([3, 1, 2], arity_exponent=2).pop()
            1
        """
        materialised = list(items)
        heap = cls(
            arity_exponent,
            key=key,
            reverse=reverse,
            capacity=max(len(materialised), 1),
        )
        heap._store[: len(materialised)] = materialised
        for index, item in enumerate(materialised):
            heap._prio[index] = heap._make_priority(item)
        heap._size = len(materialised)
        # Bottom-up heapify: every internal node is sifted down once.
        for index in range(heap._size // 2 - 1, -1, -1):
            heap._sift_down(index)
        return heap

    def heapify(self, items: Iterable[T] | None = None) -> None:
        """Rebuild the heap in ``O(n)``.

        When ``items`` is ``None`` the current content is re-heapified;
        otherwise the heap is replaced by ``items``.
        """
        if items is not None:
            materialised: list[T] = list(items)
        else:
            materialised = [cast(T, item) for item in self._store[: self._size]]
        self.clear()
        self._ensure_capacity(max(len(materialised), 1))
        self._store[: len(materialised)] = materialised
        for index, item in enumerate(materialised):
            self._prio[index] = self._make_priority(item)
        self._size = len(materialised)
        for index in range(self._size // 2 - 1, -1, -1):
            self._sift_down(index)

    def clear(self) -> None:
        """Remove every element, keeping the allocated capacity."""
        self._size = 0
        for index in range(len(self._store)):
            self._store[index] = None
            self._prio[index] = None

    def copy(self) -> KaryHeap[T]:
        """Return an independent copy of this heap."""
        clone = KaryHeap(
            self._shift,
            key=self._key,
            reverse=self.is_max_heap,
            capacity=self._capacity,
        )
        clone._store[: self._size] = self._store[: self._size]
        clone._prio[: self._size] = self._prio[: self._size]
        clone._size = self._size
        return clone

    def sorted_items(self) -> list[T]:
        """Return every element ordered by priority (best first).

        Time complexity: ``O(n log_d n)``.
        """
        clone = self.copy()
        return [clone.pop() for _ in range(clone._size)]

    def __iter__(self) -> Iterator[T]:
        """Iterate over the *storage order* of the elements.

        The order is unspecified but deterministic; use :meth:`sorted_items`
        when a priority order is required.
        """
        for index in range(self._size):
            yield self._store[index]  # type: ignore[misc]

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _ensure_capacity(self, needed: int) -> None:
        if needed <= self._capacity:
            return
        new_capacity = self._capacity
        while new_capacity < needed:
            new_capacity *= 2
        self._store.extend([None] * (new_capacity - self._capacity))
        self._prio.extend([None] * (new_capacity - self._capacity))
        self._capacity = new_capacity

    def _grow(self) -> None:
        self._ensure_capacity(self._capacity * 2)

    def _sift_up(self, index: int) -> None:
        """Move the element at ``index`` up until the heap invariant holds."""
        prio = self._prio
        store = self._store
        item = store[index]
        priority = prio[index]
        shift = self._shift
        while index > 0:
            parent = (index - 1) >> shift
            parent_priority = prio[parent]
            if not (priority < parent_priority):
                break
            prio[index] = parent_priority
            store[index] = store[parent]
            index = parent
        prio[index] = priority
        store[index] = item

    def _sift_down(self, index: int) -> None:
        """Move the element at ``index`` down until the heap invariant holds.

        The best child is selected with ``min()`` over a *slice* of the
        priority array rather than with an explicit Python loop.  Slicing a
        small window and letting the C-implemented ``min`` scan it is
        measurably faster than interpreting a Python loop, and the slice
        only ever holds ``d`` (at most 16) elements.
        """
        prio = self._prio
        store = self._store
        size = self._size
        shift = self._shift
        arity = self._arity
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
