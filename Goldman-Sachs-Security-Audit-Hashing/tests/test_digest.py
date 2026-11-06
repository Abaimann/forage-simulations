"""Tests for the self-describing digest wire format."""

from __future__ import annotations

import pytest

from crypto_audit.domain.algorithms import HashAlgorithm
from crypto_audit.domain.digest import HashDigest, decode_base64, encode_base64
from crypto_audit.domain.exceptions import InvalidDigestError, UnsupportedAlgorithmError


class TestHashDigestConstruction:
    def test_rejects_empty_hash(self) -> None:
        with pytest.raises(InvalidDigestError):
            HashDigest(algorithm=HashAlgorithm.MD5, hash=b"")

    def test_rejects_empty_salt(self) -> None:
        with pytest.raises(InvalidDigestError):
            HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16, salt=b"")

    def test_accepts_none_salt(self) -> None:
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"x" * 16, salt=None)
        assert digest.is_salted is False

    def test_accepts_string_algorithm(self) -> None:
        digest = HashDigest(algorithm="md5", hash=b"x" * 16)  # type: ignore[arg-type]
        assert digest.algorithm is HashAlgorithm.MD5

    def test_params_are_copied_not_aliased(self) -> None:
        params = {"iterations": 10}
        digest = HashDigest(
            algorithm=HashAlgorithm.PBKDF2_SHA256, hash=b"x" * 16, params=params
        )
        params["iterations"] = 999
        assert digest.params["iterations"] == 10


class TestHashDigestEncoding:
    def test_round_trip_preserves_all_fields(self) -> None:
        original = HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=bytes(range(32)),
            salt=bytes(range(16)),
            params={"m": 65536, "t": 3, "p": 4},
        )
        restored = HashDigest.decode(original.encode())
        assert restored.algorithm == original.algorithm
        assert restored.hash == original.hash
        assert restored.salt == original.salt
        assert restored.params == original.params

    def test_encoding_is_deterministic(self) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.BCRYPT,
            hash=b"a" * 31,
            salt=b"$2b$04$abcdefghijklmnopqrstuv",
            params={"cost": 4},
        )
        assert digest.encode() == digest.encode()

    def test_param_order_is_sorted(self) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.ARGON2ID,
            hash=b"a" * 32,
            salt=b"b" * 16,
            params={"t": 3, "p": 4, "m": 65536},
        )
        encoded = digest.encode()
        assert encoded.split("$")[1] == "m=65536,p=4,t=3"

    def test_unsalted_digest_has_empty_salt_field(self) -> None:
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"a" * 16, salt=None)
        encoded = digest.encode()
        assert encoded.split("$")[2] == ""

    def test_decoded_unsalted_digest_has_none_salt(self) -> None:
        digest = HashDigest(
            algorithm=HashAlgorithm.SHA1,
            hash=b"a" * 20,
            salt=None,
            params={"salted": 0},
        )
        restored = HashDigest.decode(digest.encode())
        assert restored.salt is None
        assert restored.is_salted is False


class TestHashDigestDecodingErrors:
    @pytest.mark.parametrize(
        "payload",
        [
            "",
            "md5",
            "md5$$$",
            "md5$iterations=1$c2FsdA==",
            "md5$$c2FsdA==$extra",
        ],
    )
    def test_malformed_payloads_are_rejected(self, payload: str) -> None:
        with pytest.raises(InvalidDigestError):
            HashDigest.decode(payload)

    def test_unknown_algorithm_is_rejected(self) -> None:
        with pytest.raises(UnsupportedAlgorithmError):
            HashDigest.decode("rot13$$c2FsdA==$aGFzaA==")

    def test_invalid_base64_is_rejected(self) -> None:
        with pytest.raises(InvalidDigestError):
            HashDigest.decode("md5$!!!not-base64!!!$aGFzaA==")

    def test_non_string_payload_is_rejected(self) -> None:
        with pytest.raises(InvalidDigestError):
            HashDigest.decode(b"md5$$aGFzaA==")  # type: ignore[arg-type]

    def test_malformed_parameter_is_rejected(self) -> None:
        with pytest.raises(InvalidDigestError):
            HashDigest.decode("md5$novalue$c2FsdA==$aGFzaA==")


class TestHashDigestParams:
    def test_integer_params_are_coerced(self) -> None:
        digest = HashDigest.decode("argon2id$m=65536,t=3,p=4$c2FsdA==$aGFzaA==")
        assert digest.params["m"] == 65536
        assert isinstance(digest.params["m"], int)

    def test_string_params_stay_strings(self) -> None:
        digest = HashDigest.decode("bcrypt$cost=4,prefix=2b$c2FsdA==$aGFzaA==")
        assert digest.params["prefix"] == "2b"

    def test_param_int_falls_back_on_bad_value(self) -> None:
        digest = HashDigest.decode("pbkdf2_sha256$iterations=abc$c2FsdA==$aGFzaA==")
        assert digest.param_int("iterations", 42) == 42

    def test_param_int_returns_default_when_missing(self) -> None:
        digest = HashDigest(algorithm=HashAlgorithm.MD5, hash=b"a" * 16)
        assert digest.param_int("missing", 7) == 7


class TestBase64Helpers:
    def test_encode_decode_round_trip(self) -> None:
        raw = bytes(range(256))
        assert decode_base64(encode_base64(raw)) == raw

    def test_decode_rejects_garbage(self) -> None:
        with pytest.raises(InvalidDigestError):
            decode_base64("***")
