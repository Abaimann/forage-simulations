# Goldman Sachs - Engineering Division
## Task: Cryptographic Verification & Credential Security Audit Pipeline

### Business Context
Following a security assessment of legacy internal systems, engineering teams must identify weak password hashing schemes (MD5/SHA1 without salt) and migrate credentials safely to modern standards (Argon2 / PBKDF2 / bcrypt).

### Technical Requirements
1. Implement a security auditor module that analyzes credential databases for cryptographic entropy and vulnerable hashing patterns.
2. Implement a secure password upgrade pipeline that re-hashes passwords transparently during authentication.
3. Simulate brute-force/dictionary collision resilience testing for audited algorithms.
4. Include unit tests covering edge cases: salt collision resistance, timing attack mitigation, and constant-time string comparison.
5. Document security threat models, remediation guidelines, and compliance standards (NIST SP 800-63B) in README.md.