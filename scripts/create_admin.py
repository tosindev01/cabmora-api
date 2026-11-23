"""Create the first administrator.

A script, not an endpoint. A public route that mints admins is exactly what
docs/INTEGRATION_PLAN.md §2 says must not exist — and once one admin exists,
every further one is made through `PATCH /api/v1/admin/users/{id}` by someone
who is already trusted.

    alembic upgrade head
    python -m scripts.create_admin --email you@cabmora.com \
        --first-name Ada --last-name Lovelace

The password is read from a prompt, never an argument: anything on the command
line lands in shell history and in `ps` output for every user on the box.
"""

import argparse
import asyncio
import sys

from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import (
    SqlAlchemyUserRepository,
)
from scripts._prompt import read_password


async def create_admin(email: str, first_name: str, last_name: str, password: str) -> None:
    # Assumes `alembic upgrade head` has run — this script populates a schema,
    # it does not define one.
    async with SessionFactory() as session:
        users = SqlAlchemyUserRepository(session)
        if await users.get_by_email(email.lower()) is not None:
            # Deliberately not a promotion. Silently granting admin to an
            # existing account would make this script a privilege-escalation
            # tool that leaves no trace of who ran it.
            sys.exit(
                f"An account already exists for {email}. Promote it with "
                f"PATCH /api/v1/admin/users/<id> instead."
            )
        user = await users.add(
            User(
                email=email.lower(),
                first_name=first_name.strip(),
                last_name=last_name.strip(),
                hashed_password=hash_password(password),
                role=UserRole.ADMIN,
            )
        )
        await session.commit()
        print(f"Created admin {user.email} ({user.id})")


def main() -> None:
    parser = argparse.ArgumentParser(description="Create the first administrator.")
    parser.add_argument("--email", required=True)
    parser.add_argument("--first-name", required=True)
    parser.add_argument("--last-name", required=True)
    args = parser.parse_args()

    asyncio.run(
        create_admin(args.email, args.first_name, args.last_name, read_password())
    )


if __name__ == "__main__":
    main()
