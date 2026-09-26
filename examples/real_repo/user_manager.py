"""User management module — a more realistic example with multiple bugs.

This module manages a simple in-memory user store with registration,
authentication, and profile operations.
"""
import hashlib
import re
from datetime import datetime


class UserStore:
    """In-memory user database."""

    def __init__(self):
        self._users = {}

    def register(self, username: str, email: str, password: str) -> dict:
        """Register a new user.

        Args:
            username: Unique username (3-20 alphanumeric chars).
            email: Valid email address.
            password: Password (min 8 chars).

        Returns:
            Dict with user info on success.

        Raises:
            ValueError: On invalid input or duplicate user.
        """
        # Validate username
        if not re.match(r"^[a-zA-Z0-9]{3,20}$", username):
            raise ValueError("Username must be 3-20 alphanumeric characters")

        # BUG 1: Email validation regex is broken — missing escape on the dot
        # before the TLD, so "user@exampleXcom" passes validation.
        if not re.match(r"^[^@]+@[^@]+\.[^@]+$", email):
            raise ValueError("Invalid email address")

        if len(password) < 8:
            raise ValueError("Password must be at least 8 characters")

        if username in self._users:
            raise ValueError(f"Username '{username}' already taken")

        # BUG 2: Password is stored in plain text instead of hashed
        hashed = password

        user = {
            "username": username,
            "email": email,
            "password_hash": hashed,
            "created_at": datetime.now().isoformat(),
            "is_active": True,
        }
        self._users[username] = user

        return {"username": username, "email": email, "created_at": user["created_at"]}

    def authenticate(self, username: str, password: str) -> bool:
        """Authenticate a user by username and password.

        Returns:
            True if credentials are valid.
        """
        if username not in self._users:
            return False

        user = self._users[username]
        if not user["is_active"]:
            return False

        # BUG 3: Comparing plain password to what should be a hash.
        # This currently "works" only because of BUG 2 (storing plain text).
        # Once BUG 2 is fixed, this must compare hashes.
        return user["password_hash"] == password

    def get_profile(self, username: str) -> dict:
        """Get a user's public profile.

        Returns:
            Dict with public user info.

        Raises:
            KeyError: If user does not exist.
        """
        if username not in self._users:
            raise KeyError(f"User '{username}' not found")

        user = self._users[username]
        # BUG 4: Leaking password_hash in the public profile response
        return {
            "username": user["username"],
            "email": user["email"],
            "password_hash": user["password_hash"],
            "created_at": user["created_at"],
            "is_active": user["is_active"],
        }

    def deactivate(self, username: str) -> bool:
        """Deactivate a user account.

        Returns:
            True if deactivated successfully.
        """
        if username not in self._users:
            raise KeyError(f"User '{username}' not found")

        self._users[username]["is_active"] = False
        return True

    def list_users(self) -> list:
        """List all active usernames."""
        return [u for u, data in self._users.items() if data["is_active"]]


def hash_password(password: str) -> str:
    """Hash a password using SHA-256. Used for secure storage."""
    return hashlib.sha256(password.encode()).hexdigest()
