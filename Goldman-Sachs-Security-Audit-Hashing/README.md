# Cryptographic Verification & Credential Security Audit Pipeline

**Goldman Sachs — Engineering Division**
Reference implementation of a credential-security audit and migration pipeline for
legacy internal systems.

Legacy credential stores persist. This package answers three questions an
engineering team has to answer before they can modernise one:

1. **What is actually wrong?** — analyse a credential estate for weak
   algorithms, missing/short salts, weak work factors, password reuse and low
   entropy, and emit machine-readable, actionable findings.
2. **How do we migrate without locking anyone out?** — verify legacy digests
   and, on a *successful* login, transparently re-hash the credential with the
   modern target algorithm. No plaintext is ever stored; no user is forced to
   change a password they did not need to change.
3. **How much does the current scheme actually cost an attacker?** — benchmark
   each algorithm and extrapolate dictionary- and keyspace-cracking effort.

---

## Table of contents

- [Quick start](#quick-start)
- [Architecture](#architecture)
- [Core concepts](#core-concepts)
- [API reference](#api-reference)
- [Threat model](#threat-model)
- [Remediation guidelines](#remediation-guidelines)
- [NIST SP 800-63B compliance mapping](#nist-sp-800-63b-compliance-mapping)
- [Testing](#testing)
- [Project layout](#project-layout)
- [Design decisions](#design-decisions)
- [License](#license)

---

## Quick start

### Requirements

- Python **3.10+**
- `argon2-cffi >= 23.1.0`
- `bcrypt >= 4.0.1`
- `pytest >= 7.4` (test only)

### Installation

```bash
# From the project root
python -m pip install -r requirements.txt
python -m pip install -e .          # optional: installs the `crypto-audit` CLI
```

### Run the test suite

```bash
python -m pytest -q
```

Expected output:

```
247 passed, 6 skipped
```

### Run the demonstration

```bash
PYTHONPATH=src python -m crypto_audit.cli demo
```

The demo performs four phases against a deliberately vulnerable sample estate:

```
STEP 1 - AUDIT OF THE LEGACY ESTATE
Credentials audited : 8
Findings            : critical=9 high=11 medium=0 info=1
  [CRITICAL] alice.legacy       WEAK_ALGORITHM
  [CRITICAL] alice.legacy       MISSING_SALT
  ...
STEP 2 - BRUTE-FORCE RESILIENCE
md5                     139,860 guesses/s  60-bit keyspace: 2.612e+05 years
argon2id                     10 guesses/s  60-bit keyspace: 3.507e+09 years
STEP 3 - TRANSPARENT UPGRADE ON SUCCESSFUL LOGIN
  alice.legacy       authenticated=True  md5        -> argon2id   upgraded
  ...
STEP 4 - RE-AUDIT AFTER MIGRATION
Critical findings before : 9
Critical findings after  : 0
```

### CLI commands

| Command | Purpose | Exit code |
|---|---|---|
| `demo` | Full end-to-end demonstration (audit → benchmark → upgrade → re-audit) | `0` |
| `audit` | Audit the sample estate; `--json` for machine-readable output | `1` if non-compliant |
| `benchmark` | Guesses/sec and keyspace-cracking estimates per algorithm | `0` |
| `collision` | Salt/collision resilience check for one algorithm | `1` if not resistant |

```bash
PYTHONPATH=src python -m crypto_audit.cli audit --json
PYTHONPATH=src python -m crypto_audit.cli --target bcrypt audit
PYTHONPATH=src python -m crypto_audit.cli collision --algorithm argon2id --samples 128
```

### Library usage

```python
from crypto_audit import (
    CredentialAuditor,
    HashAlgorithm,
    HashingPolicy,
    InMemoryCredentialRepository,
    LegacyHashHasher,
    UpgradePipeline,
)
from crypto_audit.domain.credential import Credential

# The legacy credential as it exists in the old store: unsalted MD5.
legacy = LegacyHashHasher(HashAlgorithm.MD5, salted=False)
repository = InMemoryCredentialRepository()
repository.save(Credential("alice", legacy.hash("the-real-password")))

# 1. Audit
report = CredentialAuditor().audit(repository)
for finding in report.findings:
    print(finding.severity.value, finding.username, finding.message)
# critical alice Credential uses MD5, which is not a password KDF: ...
# critical alice Credential is stored without a salt: ...

# 2. Transparent upgrade on next successful login
pipeline = UpgradePipeline(repository, HashingPolicy())
result = pipeline.authenticate("alice", "the-real-password")
assert result.authenticated and result.upgraded
# -> alice's stored digest is now Argon2id with a fresh 128-bit salt
```

---

## Architecture

The package follows a **ports-and-adapters (hexagonal)** layout. Dependencies
point inwards: the domain knows nothing about hashing libraries, and the
application layer talks to infrastructure only through protocols.

```
┌─────────────────────────────────────────────────────────────────────┐
│  domain/                        Pure business rules. No I/O.         │
│  ├── algorithms.py              HashAlgorithm taxonomy + metadata    │
│  ├── credential.py              Credential entity + repository port   │
│  ├── digest.py                  Self-describing, parseable digest     │
│  ├── policy.py                  HashingPolicy: thresholds & costs     │
│  ├── password.py                NFKC normalisation + byte ceiling     │
│  ├── findings.py                Severity model, findings, report      │
│  └── exceptions.py              Typed error hierarchy                  │
└─────────────────────────────────────────────────────────────────────┘
                                   ▲ depends on
┌─────────────────────────────────────────────────────────────────────┐
│  application/                   Use cases. Orchestrates domain+ports. │
│  ├── auditor.py                 CredentialAuditor  → AuditReport      │
│  ├── upgrade_pipeline.py        UpgradePipeline   → Authentication    │
│  ├── brute_force.py             BruteForceTester  → resilience data   │
│  ├── constant_time.py           secure_compare (timing-safe)          │
│  ├── entropy.py                 Shannon entropy + density metrics     │
│  └── ports.py                   PasswordHasher / HasherFactory proto  │
└─────────────────────────────────────────────────────────────────────┘
                                   ▲ implements
┌─────────────────────────────────────────────────────────────────────┐
│  infrastructure/                Concrete adapters.                  │
│  ├── argon2_hasher.py           Argon2id  (preferred)                │
│  ├── bcrypt_hasher.py           bcrypt (cost configurable)           │
│  ├── pbkdf2_hasher.py           PBKDF2-HMAC-SHA256                   │
│  ├── legacy_hashers.py          MD5 / SHA-1 / SHA-256 (verify only)  │
│  ├── hasher_factory.py          HasherRegistry (algorithm → hasher)  │
│  ├── repository.py              InMemoryCredentialRepository         │
│  └── sample_data.py             Deterministic vulnerable sample estate│
└─────────────────────────────────────────────────────────────────────┘
                                   ▲ invoked by
┌─────────────────────────────────────────────────────────────────────┐
│  cli.py                         argparse front-end (audit/demo/…)     │
└─────────────────────────────────────────────────────────────────────┘
```

### Dependency rules (enforced by review, tested by `tests/test_package.py`)

- `domain/` imports **nothing** from `application/` or `infrastructure/`.
- `application/` imports **only** from `domain/` and from `application/ports.py`.
- `infrastructure/` implements the ports declared in `application/ports.py`.
- Concrete hashers are reachable only through `HasherRegistry`, so the
  application layer never names `bcrypt` or `argon2`.

### Why each piece exists

| Component | Responsibility | Fails if |
|---|---|---|
| `HashDigest` | Canonical, self-describing wire format for a stored credential | A digest cannot be parsed or its algorithm identified |
| `HashingPolicy` | Single source of truth for "good enough" (target + thresholds) | Costs and audit thresholds drift apart |
| `CredentialAuditor` | Read-only analysis producing ranked findings | An auditor mutates production data |
| `UpgradePipeline` | Authenticate → verify → transparently re-hash → persist | A legacy user is locked out, or plaintext is persisted |
| `BruteForceTester` | Empirical attacker-cost measurement | A security claim is made without evidence |
| `secure_compare` | Timing-safe equality for every secret comparison | A comparison leaks a prefix match length |

---

## Core concepts

### 1. The digest wire format

Every stored credential uses one canonical, `$`-delimited format:

```
<algorithm>$<parameters>$<base64 salt>$<base64 hash>
```

Real examples produced by this package:

```
argon2id$length=32,m=65536,p=4,t=3$To+6WcDsDgcflGmAT7aDlA==$Ew7aRPnD0KdUXY2SFsasiReSPtYq8MPOlaY5ebSCXRw=
bcrypt$cost=12,prefix=2b$JDJiJDEyJFBpeFRPdlhFbVJ5VThyRk44RU9XOGU=$NFQ4d285VHVVM3FidXZzQy5IdFBnRk1keHNpVjRpZQ==
pbkdf2_sha256$iterations=600000,length=32$UYOjPVCimcn6S3gnhZB06g==$Bjbtjs9YUMEFy+SXw2Doo29eJDg5XQhNGYRo7MLHfr8=
md5$salted=0$$X03MO1qnZdYdgyfeuILPmQ==
```

Note the last line: the **salt field is empty** for unsalted legacy digests —
that is precisely the condition the auditor reports as `MISSING_SALT`.
Parameters are stored **with the digest**, so a stored credential can always
be re-verified with exactly the parameters it was created with (critical
when policy thresholds change over time). Parameters are sorted on encoding,
so the representation is deterministic and diffable.

### 2. Hashing policy

`HashingPolicy` is immutable, serialisable, and holds two distinct groups of
values: the **cost parameters** used to *create* digests, and the **audit
thresholds** used to *judge* them.

| Setting | Default | Rationale |
|---|---|---|
| `target_algorithm` | `argon2id` | NIST SP 800-63B preferred KDF |
| `salt_bytes` | 16 | NIST SP 800-132: ≥ 128-bit random salt |
| `pbkdf2_iterations` | 600,000 | SP 800-63B (2025) minimum for HMAC-SHA256 |
| `bcrypt_cost` | 12 | OWASP recommendation |
| `argon2_memory_kib` | 65,536 | OWASP: 64 MiB |
| `argon2_time_cost` | 3 | OWASP |
| `argon2_parallelism` | 4 | OWASP |
| `minimum_password_length` | 12 | Above the SP 800-63B floor of 8 |
| `minimum_password_entropy_bits` | 64 | SP 800-63B §3.1.1.1 |
| `minimum_digest_entropy_density` | 0.85 | Uniformity of the stored digest |

`policy.needs_rehash(digest)` returns `True` when a digest is legacy, has a
missing/short salt, uses an algorithm other than the target, or carries
outdated cost parameters. This single predicate drives the whole migration.

### 3. Entropy: density, not bits-per-byte

Shannon entropy of a *sample* is bounded by `log2(sample_length)`. A 32-byte
digest can never exceed 5 bits/byte and a 16-byte salt never more than
4 bits/byte — no matter how random they are. Comparing short samples against
the theoretical 8 bits/byte ceiling would flag every correctly generated
credential as low-entropy.

This package therefore distinguishes:

- `shannon_entropy_bits(data)` / `normalised_entropy_bits_per_byte(data)` —
  raw measured entropy, useful for detecting constant or patterned data.
- `entropy_density(data)` — measured entropy as a fraction of the maximum
  achievable for a sample of that length (`0.0`–`1.0`). **This is the metric
  the policy compares against**, because it is length-independent.

### 4. Transparent upgrade pipeline

```
authenticate(username, password)
  │
  ├─ credential missing? ──► perform decoy verification ──► reject
  │
  ├─ stored algorithm ≠ target? ──► perform decoy verification  (timing equalisation)
  │
  ├─ verify against the stored digest (constant time)
  │     └─ invalid ──► reject, do NOT upgrade
  │
  ├─ policy.needs_rehash(digest)?
  │     ├─ no  ──► accept, no write
  │     └─ yes ──► re-hash with target algorithm, persist, bump version, accept
```

Key guarantees:

- **No plaintext is persisted.** The pipeline re-hashes the secret that the
  user just supplied and stores only the resulting digest.
- **Failed logins never trigger an upgrade**, so an attacker cannot force a
  digest rotation to a value they choose.
- **Migration is opportunistic**: a credential is upgraded the first time its
  owner logs in successfully. Dormant accounts require the bulk
  `migrate_all()` path or a forced reset.
- **`migrate_all()` never downgrades** a credential that is already compliant.

---

## API reference

### `CredentialAuditor`

```python
auditor = CredentialAuditor(policy: HashingPolicy | None = None)
report: AuditReport = auditor.audit(
    repository: CredentialRepository,
    candidates: Mapping[str, str] | None = None,   # username → plaintext
)
```

`candidates` is optional and used only for offline strength screening of
already-recovered plaintext. The auditor **never** writes plaintext into a
finding or into the report.

#### Finding categories

| Category | Severity | Trigger | Remediation |
|---|---|---|---|
| `WEAK_ALGORITHM` | CRITICAL | MD5 / SHA-1 / SHA-256 stored digest | Re-hash with Argon2id, PBKDF2 or bcrypt |
| `MISSING_SALT` | CRITICAL | Digest carries no salt | Re-hash with a unique ≥ 128-bit salt |
| `SHORT_SALT` | HIGH | Salt shorter than policy minimum | Re-hash with a fresh, policy-sized salt |
| `WEAK_PARAMETERS` | HIGH | Cost parameters below policy | Re-hash with policy-compliant parameters |
| `LOW_ENTROPY` | HIGH / MEDIUM | Digest uniformity below threshold, or recovered password too weak | Re-hash / force a strong passphrase |
| `PASSWORD_REUSE` | HIGH | Two or more accounts share an identical digest | Force individual resets |
| `POLICY_NON_COMPLIANT` | HIGH | Recovered password shorter than policy minimum | Enforce a longer passphrase |
| `TIMING_RISK` | MEDIUM | A salt is reused across accounts | Ensure independent salts |
| `COMPLIANT` | INFO | Digest satisfies the whole policy | None |

### `UpgradePipeline`

```python
pipeline = UpgradePipeline(
    repository: CredentialRepository,
    policy: HashingPolicy | None = None,
    *,
    registry: HasherRegistry | None = None,
    clock: Callable[[], datetime] | None = None,
)

result: AuthenticationResult = pipeline.authenticate(username, password)
results: dict[str, AuthenticationResult] = pipeline.migrate_all({"user": "secret"})
bool: pipeline.verify_secret(candidate, expected)
```

`AuthenticationResult` fields: `authenticated`, `upgraded`,
`previous_algorithm`, `current_algorithm`, `credential`, `reason`
(`unknown_user` / `invalid_password` / `up_to_date` / `upgraded`).

### `BruteForceTester`

```python
tester = BruteForceTester(policy, benchmark_iterations=3)

report: CollisionReport = tester.collision_report(hasher, samples=64)
estimate: BruteForceEstimate = tester.estimate(hasher, dictionary_size=10_000_000,
                                                 keyspace_bits=60)
attack: DictionaryAttackResult = tester.dictionary_attack(hasher, digest, dictionary)
all_estimates: dict[str, BruteForceEstimate] = tester.compare(hashers)
```

`CollisionReport.is_collision_resistant` is `True` only when all three hold:
no digest collisions, every sample used a distinct salt, and identical
passwords still produced distinct digests.

### `secure_compare`

```python
secure_compare(left: str | bytes, right: str | bytes) -> bool
secure_compare_bytes(left: bytes, right: bytes) -> bool
```

Both delegate to `hmac.compare_digest`, which does not short-circuit on the
first differing byte. Use these — never `==` — for anything secret.

---

## Threat model

### Scope

**In scope:** credential storage and verification at rest; offline cracking of
a stolen credential database; credential reuse across accounts; side-channel
leakage of verification timing; accidental downgrade of hashing strength.

**Out of scope:** network transport (use TLS), session management, MFA,
authorisation, endpoint compromise, and exfiltration through application logs.

### Assets

| Asset | Security property | Why it matters |
|---|---|---|
| Credential digests | Confidentiality | The digest database is the offline attack target |
| Plaintext secrets | Confidentiality | Never persisted by this pipeline |
| Hashing policy | Integrity | Downgrading policy silently weakens every credential |
| Verification path | Integrity | Timing leaks reveal account existence |

### Actors and attack vectors

| # | Threat | Vector | Mitigation implemented |
|---|---|---|---|
| T1 | **Offline brute force** | Steal the credential table, hash guesses offline | Argon2id (64 MiB, t=3) raises the per-guess cost by ~5 orders of magnitude vs MD5 |
| T2 | **Rainbow-table / precomputation** | Precompute digests for common passwords once, reuse across targets | Per-credential random 128-bit salt defeats precomputation |
| T3 | **Credential stuffing** | Reuse a password breached elsewhere | Per-credential salt means identical passwords produce different digests, hiding reuse from an attacker who holds only hashes |
| T4 | **Same-password mass cracking** | One cracked password unlocks many accounts | Same as T3 — salted digests do not cluster |
| T5 | **Timing side channel (enumeration)** | Measure response time to enumerate valid usernames | Unknown users trigger a decoy verification, so timing is independent of account existence |
| T6 | **Timing side channel (algorithm disclosure)** | Infer that a target is still on MD5 and attack it offline | For legacy credentials the pipeline *additionally* performs a target-algorithm verification, so timing does not reveal the stored algorithm |
| T7 | **Timing side channel (prefix length)** | Recover a secret byte-by-byte from comparison timing | All comparisons use `hmac.compare_digest`; no `==` on secrets |
| T8 | **Unicode normalisation bypass** | Register with NFC, authenticate with NFD (or full-width vs ASCII) | All passwords are NFKC-normalised before hashing and verification |
| T9 | **Silent policy downgrade** | Lower the cost parameters to make logins faster | Stored parameters travel with the digest; `needs_rehash` flags any digest that no longer meets policy |
| T10 | **Forced rotation by attacker** | Trigger an upgrade to a value the attacker controls | Failed authentications never trigger an upgrade |
| T11 | **bcrypt 72-byte truncation** | Assume two passwords sharing a 72-byte prefix are equivalent | bcrypt refuses passwords over 72 bytes instead of silently truncating |
| T12 | **Denial of service via huge passwords** | Submit a multi-megabyte password | Hard byte ceiling (`MAX_PASSWORD_BYTES = 4096`) before any KDF runs |
| T13 | **Salt reuse across accounts** | A shared salt lets a precomputation cover many users | The auditor reports salt reuse as `TIMING_RISK`; the factory always generates fresh salts |
| T14 | **Low-entropy digest / constant hash** | A truncated or constant digest verifies trivially | Entropy-density screening against the policy threshold |
| T15 | **Malformed digest as an oracle** | Send crafted digest strings to distinguish error paths | All parsing failures raise typed, non-revealing errors; verification returns `False` rather than distinguishing failure modes |

### Residual risks

- **Memory-hard ≠ resistant to GPU/ASIC.** Argon2id raises cost substantially
  but is not a silver bullet against well-funded hardware attacks.
- **The decoy digest is cached in memory.** It is a throwaway random value,
  never a credential; a memory dump of the process is out of scope.
- **Offline attacks on a compromised database cannot be prevented**, only
  made more expensive. The pipeline raises the floor; it does not remove it.
- **`candidates` requires plaintext in memory.** Use it only in a controlled
  migration environment, never in a long-running service.

---

## Remediation guidelines

### Phase 0 — Contain and measure (week 0)

1. **Inventory** the credential estate: algorithm, salt presence, salt length,
   stored parameters.
2. **Run the auditor** and export the JSON report as the baseline artefact.
3. **Identify reuse** (`PASSWORD_REUSE`) — these accounts need individual
   resets, not just re-hashing.
4. **Freeze policy drift**: no new credential may be created with a weaker
   algorithm than the current target.

### Phase 1 — Deploy the target algorithm (week 1)

1. Ship Argon2id with the policy parameters.
2. Deploy the **upgrade pipeline** in front of the legacy verifier.
3. Keep the legacy hashers **read-only for verification**; they must never be
   used to create a new credential.

### Phase 2 — Opportunistic migration (weeks 1–8)

1. Every successful login transparently re-hashes the credential.
2. Monitor `upgraded` vs `up_to_date` in `AuthenticationResult` to track
   migration progress per account.
3. Do **not** force a global reset — it generates support load and training
   risk, and the re-hash already removes the offline attack advantage.

### Phase 3 — Drain the legacy tail (weeks 8–12)

1. For service accounts whose plaintext is known, use `migrate_all()` during
   a maintenance window.
2. For dormant accounts, run a forced reset with a generated passphrase
   (or a reset link), then expire the legacy digest.
3. When the last legacy digest is gone, **remove the legacy hashers from the
   registry entirely** — this is the control that makes the migration final.

### Phase 4 — Sustain (ongoing)

1. Run the auditor on a schedule; alert on new `CRITICAL` findings.
2. Re-benchmark the target algorithm at least annually and raise parameters
   as hardware improves.
3. Re-check against the current NIST SP 800-63B revision.

### Parameter change procedure

When policy thresholds change:

1. Deploy the new thresholds — the auditor immediately flags affected
   digests as `WEAK_PARAMETERS`.
2. `needs_rehash` returns `True` for them, so the next successful login
   re-hashes at the new cost.
3. Because parameters travel with the digest, old digests remain verifiable
   during the drain — no forced reset is required to keep people logged in.

### Anti-patterns to avoid

| Anti-pattern | Why it is wrong | Do instead |
|---|---|---|
| "Just add a salt to MD5." | MD5 is far too fast; salting does not fix a missing work factor | Use Argon2id / PBKDF2 / bcrypt |
| "Rotate the salt on every login." | Defeats offline caching benefits and adds write amplification | Rotate only on a successful login, when the algorithm/parameters change |
| "Store the plaintext to allow re-hashing." | Converts a hash breach into a full credential breach | Re-hash at authentication time, where the plaintext already exists |
| "Force everyone to reset immediately." | Support cost, training risk, and users will reuse passwords | Opportunistic upgrade, then targeted resets for reuse/weakness |
| "Compare digests with `==`." | Leaks prefix-match length | Use `secure_compare` / `hmac.compare_digest` |
| "Accept bcrypt's silent 72-byte truncation." | Two distinct passwords can collide | Reject over-length passwords, or use Argon2id |
| "Lower the work factor to fix login latency." | Silently downgrades every credential | Raise the *capacity*, not the cost; or lower the policy floor only as a documented, dated decision |

---

## NIST SP 800-63B compliance mapping

Reference: *NIST SP 800-63B-4, Digital Identity Guidelines: Authentication
and Authenticator Management* (July 2025).

| SP 800-63B requirement | Section | Implementation | Status |
|---|---|---|---|
| Verifiers **SHALL** use an approved password KDF | §3.1.1.2 | `HashingPolicy.target_algorithm` restricted to Argon2id / PBKDF2-HMAC-SHA256 / bcrypt; `HashAlgorithm.is_approved_for_new_credentials` | ✅ |
| Argon2id **SHOULD** be used; Argon2i/Argon2d avoided (side-channel) | §3.1.1.2 | `HashAlgorithm.ARGON2ID` is the default target; Argon2id uses `low_level.Type.ID` | ✅ |
| PBKDF2 **SHOULD** use ≥ 600,000 iterations with HMAC-SHA256 | §3.1.1.2 | `minimum_pbkdf2_iterations = 600_000`, `AlgorithmParameters.pbkdf2_iterations = 600_000` | ✅ |
| bcrypt **MAY** be used with a cost ≥ 10 | §3.1.1.2 | `minimum_bcrypt_cost = 10`, default cost 12 | ✅ |
| Argon2 **SHOULD** use ≥ 64 MiB memory, ≥ 3 passes, parallelism 1–4 | §3.1.1.2 | `argon2_memory_kib = 65_536`, `argon2_time_cost = 3`, `argon2_parallelism = 4` | ✅ |
| Salt **SHALL** be ≥ 64 bits and uniquely assigned per credential | §5.1.1.2 | `salt_bytes = 16` (128-bit), `secrets.token_bytes`, unique-salt tests | ✅ |
| Verifiers **SHALL** NOT impose composition rules (uppercase/digit/symbol) | §3.1.1.1 | No composition rule is enforced; only length + entropy are checked | ✅ |
| Verifiers **SHOULD** require ≥ 64 bits of entropy | §3.1.1.1 | `minimum_password_entropy_bits = 64.0`, `analyse_password_entropy` | ✅ |
| Verifiers **SHOULD** permit ≥ 64 characters and **SHOULD NOT** truncate | §3.1.1.1 | `MAX_PASSWORD_BYTES = 4096`; bcrypt's 72-byte limit is **rejected**, not silently applied | ✅ |
| Passwords **SHALL** be compared in a manner resistant to timing attacks | §3.1.1.2 | `secure_compare` / `hmac.compare_digest` on every digest comparison | ✅ |
| Verifiers **SHOULD** rate-limit and not reveal account existence | §3.1.1.2 | Decoy verification equalises timing; identical error reason for unknown user and bad password | ⚠️ Partial — see §5.1.1.2 |
| Verifiers **SHOULD** check against a blocklist of common/compromised passwords | §3.1.1.2 | `BruteForceTester.dictionary_attack` supports screening; the sample dictionary ships in `tests/` | ⚠️ Partial — plug in a production breach corpus |
| Passwords **SHOULD NOT** be periodically rotated without evidence of compromise | §3.1.1.2 | Opportunistic upgrade on login; no scheduled forced rotation | ✅ |
| Passwords **SHOULD NOT** be stored with a reversible transformation | §5.1.1.2 | Only one-way digests are persisted; the pipeline never writes plaintext | ✅ |
| Salt **SHALL** be stored alongside the hash | §5.1.1.2 | Digest wire format carries the salt and parameters | ✅ |
| The KDF cost **SHALL** be stored with the credential | §5.1.1.2 | `HashDigest.params` | ✅ |

### Deviations and how they are handled

- **bcrypt 72-byte limit.** SP 800-63B notes bcrypt's truncation. This
  implementation *rejects* over-length passwords rather than truncating them
  silently, and the error message directs the caller to Argon2id. Where
  bcrypt must be used with long passwords, pre-hash with a separate KDF —
  never truncate.
- **Rate limiting / lockout** is out of scope for this library (it is an
  application-level concern); the timing-equalisation property this library
  provides is a prerequisite for it, not a replacement.
- **Breach-corpus screening** requires a licensed/current corpus; the
  dictionary-attack machinery to apply one is provided and tested.

---

## Testing

```bash
python -m pytest -q                                   # full suite
python -m pytest -q --cov=crypto_audit --cov-report=term-missing
python -m pytest -q tests/test_constant_time.py       # a single module
python -m pytest -q -k "salt"                         # by keyword
```

Current status: **247 passed, 6 skipped**, **96% line coverage**.

The skips are intentional and self-documenting:

- 4 skips: algorithms whose byte ceiling equals the policy ceiling have no
  tighter-than-policy limit to reject.
- 2 skips: the unsalted legacy MD5 hasher legitimately accepts a `None` salt.

### Test module map

| Module | What it proves |
|---|---|
| `tests/test_digest.py` | Wire-format round-trip, malformed input, strict base64, parameter coercion |
| `tests/test_hashers.py` | A shared contract across all five hashers: correct/wrong password, empty & long secrets, cross-algorithm rejection, wire round-trip, fresh salt per hash, constructor validation |
| `tests/test_constant_time.py` | Constant-time comparison semantics **and** empirical timing evidence that early mismatch is not faster than late mismatch |
| `tests/test_salt_and_entropy.py` | Salt collision resistance (200 unique salts, zero collisions), salt entropy density, Shannon entropy bounds, password entropy estimation |
| `tests/test_auditor.py` | Each finding category fires for exactly the condition it describes; report ordering, statistics and serialisation |
| `tests/test_upgrade_pipeline.py` | Transparent upgrade, no-plaintext persistence, no upgrade on failure, timing equalisation (call-count spies + wall-clock ratio), bulk migration never downgrades |
| `tests/test_brute_force.py` | Collision resilience per algorithm, dictionary attack recovery, benchmark estimates, modern-vs-legacy slowdown |
| `tests/test_policy_repository_cli.py` | Policy thresholds, repository adapter, hasher registry, and every CLI subcommand including JSON output |
| `tests/test_package.py` | Public API surface and the layering rule (no infrastructure imports in the domain) |

### Notable edge cases covered

- **Salt collision resistance** — 200 hashes of the same password yield 200
  distinct salts and 200 distinct digests, for Argon2id, bcrypt, PBKDF2 and
  salted legacy MD5.
- **Timing-attack mitigation** — an unknown user performs exactly one decoy
  verification; a legacy user performs a target-algorithm verification *plus*
  the legacy one; wall-clock time for known vs unknown accounts stays within
  a 5× band.
- **Constant-time comparison** — `secure_compare` rejects non-string/bytes
  operands with a typed error; timing ratios for early vs late mismatch stay
  within 0.5–2.0.
- **Malformed input** — truncated digests, invalid base64, unknown
  algorithms, malformed parameters, and non-string payloads all raise typed
  errors rather than leaking behaviour.
- **Unicode** — NFKC normalisation makes visually identical passwords hash
  identically; non-ASCII passwords round-trip.
- **Limits** — bcrypt rejects > 72 bytes; every KDF rejects > 4096 bytes.
- **Empty and boundary values** — empty password, 1-byte salt, zero
  iterations, zero memory, unknown usernames, empty repositories.

---

## Project layout

```
.
├── README.md
├── pyproject.toml              # packaging + pytest configuration
├── requirements.txt
├── .gitignore
├── src/
│   └── crypto_audit/
│       ├── __init__.py         # public API re-exports
│       ├── cli.py              # argparse front-end
│       ├── domain/
│       │   ├── algorithms.py
│       │   ├── credential.py
│       │   ├── digest.py
│       │   ├── exceptions.py
│       │   ├── findings.py
│       │   ├── password.py
│       │   └── policy.py
│       ├── application/
│       │   ├── auditor.py
│       │   ├── brute_force.py
│       │   ├── constant_time.py
│       │   ├── entropy.py
│       │   ├── ports.py
│       │   └── upgrade_pipeline.py
│       └── infrastructure/
│           ├── argon2_hasher.py
│           ├── bcrypt_hasher.py
│           ├── hasher_factory.py
│           ├── legacy_hashers.py
│           ├── pbkdf2_hasher.py
│           ├── repository.py
│           └── sample_data.py
└── tests/
    ├── conftest.py
    ├── test_auditor.py
    ├── test_brute_force.py
    ├── test_constant_time.py
    ├── test_digest.py
    ├── test_hashers.py
    ├── test_package.py
    ├── test_policy_repository_cli.py
    ├── test_salt_and_entropy.py
    └── test_upgrade_pipeline.py
```

---

## Design decisions

**Why Argon2id as the default?** It is the SP 800-63B preferred KDF and is
memory-hard, which raises the cost of GPU/ASIC cracking far more than an
iteration count alone can. PBKDF2 and bcrypt remain fully supported as
approved alternatives, selectable via `policy.with_target(...)`.

**Why store the parameters with the digest?** A stored credential must remain
verifiable after policy thresholds change, and an auditor must be able to
judge a digest without guessing which parameters created it. Both requirements
push the parameters into the wire format.

**Why is the audit read-only?** An auditor that mutates state cannot be run
against production as a diagnostic. Mutation is a separate, explicit concern
owned by the upgrade pipeline.

**Why is `migrate_all()` separate from `authenticate()`?** Bulk migration
requires the plaintext, which only exists for service accounts with known
secrets. Exposing it as a distinct operation makes the trust boundary
obvious and keeps the login path free of a plaintext cache.

**Why does the pipeline verify *twice* for legacy credentials?** It looks
wasteful, but it is the price of not leaking the stored algorithm through
timing. A cheap legacy verification followed by a re-hash would otherwise
return measurably faster than a modern-account login.

**Why are the legacy hashers still in the codebase?** They are required to
verify credentials during the migration window. They are isolated in
`infrastructure/legacy_hashers.py`, unreachable for *creation* through the
registry, and every digest they produce is reported as `CRITICAL`. They are
deleted in Phase 4 of the remediation plan.

---

## License

MIT.
