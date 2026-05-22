import base64
import binascii
import hashlib
import hmac
import os
from typing import Optional


PASSWORD_HASH_SCHEME = "pbkdf2_sha256"
PASSWORD_HASH_ITERATIONS = 260_000


def normalize_username(username: str) -> str:
    return username.strip().lower()


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    digest_b64 = base64.b64encode(digest).decode("ascii")
    return f"{PASSWORD_HASH_SCHEME}${PASSWORD_HASH_ITERATIONS}${salt_b64}${digest_b64}"


def parse_password_hash(value: str) -> Optional[tuple[int, bytes, bytes]]:
    try:
        scheme, iterations, salt_b64, digest_b64 = value.split("$", 3)
    except ValueError:
        return None

    if scheme != PASSWORD_HASH_SCHEME:
        return None

    try:
        return (
            int(iterations),
            base64.b64decode(salt_b64.encode("ascii")),
            base64.b64decode(digest_b64.encode("ascii")),
        )
    except (ValueError, binascii.Error):
        return None


def verify_password_hash(password: str, stored_hash: str) -> bool:
    parsed = parse_password_hash(stored_hash)
    if parsed is None:
        return False

    iterations, salt, expected_digest = parsed
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(digest, expected_digest)
