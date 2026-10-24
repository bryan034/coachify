from argon2 import PasswordHasher
from argon2.exceptions import VerificationError, InvalidHashError

# Argon2id: OWASP minimum of 19 MiB, two iterations and one lane.
hasher = PasswordHasher(time_cost=2, memory_cost=19456, parallelism=1)
_dummy_hash = hasher.hash('synthetic-timing-only-not-an-account-password')


def password_matches(encoded, password):
    try:
        return hasher.verify(encoded or _dummy_hash, password) and bool(encoded)
    except (VerificationError, InvalidHashError):
        return False
