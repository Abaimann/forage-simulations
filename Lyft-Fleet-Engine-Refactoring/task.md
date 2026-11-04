# Lyft - Backend Engineering
## Task: Clean Architecture & Strategy Pattern Refactoring for Fleet Maintenance

### Business Context
Lyft's rental car fleet management service needs a modular refactor to handle different engine types (Capulet, Willoughby, Sternman) and battery/tire inspection rules across different vehicle models without tightly coupled inheritance.

### Technical Requirements
1. Design and implement a clean, extensible object-oriented architecture utilizing the Strategy and Factory patterns.
2. Decouple Engine, Battery, and Car components with clear interfaces (`Engine`, `Battery`, `Serviceable`).
3. Implement service criteria: mileage-based triggers, calendar-based intervals, and sensor wear thresholds.
4. Write robust unit tests verifying servicing logic for all car models (Calliope, Glissando, Palindrome, Rorschach, Thovex).
5. Author an in-depth README.md detailing architectural design decisions, UML diagram in text/markdown, and extensibility guidelines.