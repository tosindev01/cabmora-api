from app.core.exceptions import EntityAlreadyExistsError
from app.core.security import hash_password
from app.domain.entities.user import User, UserRole, UserStatus
from app.domain.repositories.user_repository import UserRepository


class RegisterUser:
    def __init__(self, users: UserRepository) -> None:
        self._users = users

    async def execute(
        self,
        email: str,
        first_name: str,
        last_name: str,
        password: str,
        account_type: str = "customer",
    ) -> User:
        """Register an account awaiting acceptance.

        The caller chooses an account *type*, never a role — see
        `RegisterRequest`. The role records what was applied for; the status
        records whether it has been granted.

        Every registration lands PENDING, customers included. That is a product
        decision (Taiwo, 2026-09-01), taken knowing it puts an admin between a
        prospective customer and their first look at the platform — the PRD
        counts registered customer accounts as an adoption metric, so the queue
        needs to be worked promptly or that number suffers.
        """
        role = UserRole.CREATOR if account_type == "creator" else UserRole.CUSTOMER
        status = UserStatus.PENDING

        existing = await self._users.get_by_email(email.lower())
        if existing is not None:
            raise EntityAlreadyExistsError("An account with this email already exists")

        user = User(
            email=email.lower(),
            first_name=first_name.strip(),
            last_name=last_name.strip(),
            hashed_password=hash_password(password),
            role=role,
            status=status,
        )
        return await self._users.add(user)
