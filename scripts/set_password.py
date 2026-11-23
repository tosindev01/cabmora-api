"""Reset an existing user's password.

The counterpart to `create_admin`. There is no password-change endpoint yet, so
this is the only supported way to rotate a credential — including the first
admin's, which is set before anyone has a way to change it.

    railway ssh --service cabmora-api \
        python -m scripts.set_password --email you@cabmora.com

Uses the repository's `set_password`, not `update`: `update` writes only role
and status, and widening it to cover credentials is exactly the mistake its
docstring warns against.
"""

import argparse
import asyncio
import sys

from app.core.security import hash_password
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import (
    SqlAlchemyUserRepository,
)
from scripts._prompt import read_password


async def set_password(email: str, password: str) -> None:
    async with SessionFactory() as session:
        users = SqlAlchemyUserRepository(session)
        user = await users.get_by_email(email.lower())
        if user is None:
            # Not "wrong password" — this is an operator tool, not a login
            # surface, so there is nothing to be gained by being vague.
            sys.exit(f"No account exists for {email}.")

        user.hashed_password = hash_password(password)
        await users.set_password(user)
        print(f"Password updated for {user.email} ({user.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Reset a user's password.")
    parser.add_argument("--email", required=True)
    args = parser.parse_args()

    asyncio.run(set_password(args.email, read_password()))


if __name__ == "__main__":
    main()
