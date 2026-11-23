"""Seed a local database with accounts to develop against.

Refuses to run unless ENVIRONMENT=local. These passwords are in the repository,
so an account created with them is public knowledge — the guard is what stops a
misaimed DATABASE_URL from putting a known-password admin into staging or
production. For a real administrator use `scripts/create_admin.py`, which
prompts for a password instead.

    alembic upgrade head
    python -m scripts.seed_dev
"""

import asyncio
import sys

from app.core.config import get_settings
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole
from app.infrastructure.database import SessionFactory
from app.infrastructure.repositories.user_repository_impl import (
    SqlAlchemyUserRepository,
)

# (email, password, first, last, role)
ACCOUNTS = [
    ("admin@cabmora.com", "adminpassword123", "Cabmora", "Admin", UserRole.ADMIN),
    ("creator@cabmora.com", "creatorpass123", "Casey", "Creator", UserRole.CREATOR),
    ("customer@cabmora.com", "customerpass123", "Chris", "Customer", UserRole.CUSTOMER),
]


async def seed() -> None:
    settings = get_settings()
    if settings.environment != "local":
        sys.exit(
            f"Refusing to seed: ENVIRONMENT is {settings.environment!r}, not 'local'. "
            "These credentials are published in the repo."
        )

    async with SessionFactory() as session:
        users = SqlAlchemyUserRepository(session)
        for email, password, first, last, role in ACCOUNTS:
            if await users.get_by_email(email) is not None:
                print(f"  exists  {email:24} ({role.value})")
                continue
            await users.add(
                User(
                    email=email,
                    first_name=first,
                    last_name=last,
                    hashed_password=hash_password(password),
                    role=role,
                )
            )
            print(f"  created {email:24} ({role.value})")
        await session.commit()

    print("\nSign in with:")
    for email, password, _, _, role in ACCOUNTS:
        print(f"  {role.value:9} {email:24} {password}")


if __name__ == "__main__":
    asyncio.run(seed())
