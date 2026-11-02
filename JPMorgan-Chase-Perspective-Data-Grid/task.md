# J.P. Morgan Chase & Co. - Software Engineering Lite
## Task 2: Live Perspective Data Grid & Stream Processor

### Business Context
Traders on the desk require a dynamic, real-time visual interface to monitor price discrepancies between correlated stock symbols in real-time.

### Technical Requirements
1. Implement a real-time data feeding server and client utility using Python.
2. Ingest continuous mock tick streams containing `stock`, `top_ask_price`, `top_bid_price`, and `timestamp`.
3. Aggregate quotes into a Perspective-ready data structure containing computed fields (`price`, `ratio`, `upper_bound`, `lower_bound`, `trigger_alert`).
4. Write comprehensive unit test suites verifying streaming throughput, aggregation logic, and alert threshold detection.
5. Include production-ready README.md explaining architecture, latency considerations, and step-by-step verification.