# Walmart Global Tech - Advanced Software Engineering
## Task: High-Performance Multi-way Heap for Real-time Warehouse Logistics

### Business Context
Walmart distribution centers process millions of package fulfillment requests per hour. The existing binary priority queue suffers from cache-miss bottlenecks under heavy multi-core loads.

### Technical Requirements
1. Implement a generic, high-performance Power-of-Two (2^k-ary) Min-Heap / Max-Heap data structure from scratch in Python.
2. Optimize branch prediction and cache-line locality for push/pop/peek operations compared to standard binary heaps.
3. Implement a priority-based order dispatch simulation simulating thousands of simultaneous package arrivals and truck loading events.
4. Provide benchmark test suites comparing time complexity, memory footprint, and operations-per-second against standard `heapq`.
5. Write technical README.md detailing algorithmic complexity analysis, mathematical proof of child-parent indices, and profiling results.