# Deloitte - Technology Consulting
## Task 1: Daikibo Industrials IIoT Telemetry Ingestion Pipeline

### Business Context
Daikibo Industrials operates manufacturing plants across 4 continents. Telemetry sensors on production lines stream temperatures, vibration frequencies, and error codes in fragmented legacy JSON and CSV formats.

### Technical Requirements
1. Build an ETL ingestion module that parses heterogeneous telemetry streams from factory floor sensors.
2. Normalize timestamps into UTC ISO-8601, clean corrupted sensor anomalies, and validate data contracts.
3. Calculate statistical moving averages, anomaly detection flags (temperatures > 3 sigma above baseline), and machine health scores.
4. Provide 100% test coverage with pytest/unittest testing edge cases (corrupt inputs, schema drift, sensor dropouts).
5. Document data flow architecture, schema definition, and production deployment notes in README.md.