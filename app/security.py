from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re


PASSWORD_ALGORITHM = "pbkdf2_sha256"
PASSWORD_ITERATIONS = 240_000


def hash_password(password: str) -> str:
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_ITERATIONS,
    )
    return "$".join(
        [
            PASSWORD_ALGORITHM,
            str(PASSWORD_ITERATIONS),
            base64.b64encode(salt).decode("ascii"),
            base64.b64encode(digest).decode("ascii"),
        ]
    )


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, iterations_raw, salt_raw, digest_raw = stored_hash.split("$", 3)
    except ValueError:
        return False

    if algorithm != PASSWORD_ALGORITHM:
        return False

    try:
        iterations = int(iterations_raw)
        salt = base64.b64decode(salt_raw.encode("ascii"))
        expected = base64.b64decode(digest_raw.encode("ascii"))
    except Exception:
        return False

    candidate = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        iterations,
    )
    return hmac.compare_digest(candidate, expected)


def normalize_whitespace(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ")).strip()


def clean_teacher_name(raw_name: str) -> str:
    compact = normalize_whitespace(raw_name)
    return re.sub(r"\(\d+\)$", "", compact).strip()


def build_unique_usernames(display_names: list[str]) -> list[str]:
    counts: dict[str, int] = {}
    usernames: list[str] = []
    for name in display_names:
        counts[name] = counts.get(name, 0) + 1
        usernames.append(name)

    if all(total == 1 for total in counts.values()):
        return usernames

    seen: dict[str, int] = {}
    resolved: list[str] = []
    for name in display_names:
        total = counts[name]
        if total == 1:
            resolved.append(name)
            continue
        seen[name] = seen.get(name, 0) + 1
        resolved.append(f"{name}{seen[name]}")
    return resolved


def validate_password_strength(new_password: str) -> None:
    if len(new_password) < 4:
        raise ValueError("비밀번호는 최소 4자 이상이어야 합니다.")
