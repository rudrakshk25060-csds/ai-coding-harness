"""Tests for user_manager module.

These tests are designed to expose the bugs in UserStore.
"""
import pytest
from user_manager import UserStore, hash_password


class TestRegistration:
    """Tests for user registration."""

    def test_register_valid_user(self):
        store = UserStore()
        result = store.register("alice", "alice@example.com", "securepass123")
        assert result["username"] == "alice"
        assert result["email"] == "alice@example.com"
        assert "created_at" in result

    def test_register_short_username(self):
        store = UserStore()
        with pytest.raises(ValueError, match="3-20 alphanumeric"):
            store.register("ab", "ab@test.com", "password123")

    def test_register_invalid_email(self):
        store = UserStore()
        with pytest.raises(ValueError, match="Invalid email"):
            store.register("testuser", "not-an-email", "password123")

    def test_register_short_password(self):
        store = UserStore()
        with pytest.raises(ValueError, match="at least 8"):
            store.register("testuser", "test@test.com", "short")

    def test_register_duplicate_user(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "password123")
        with pytest.raises(ValueError, match="already taken"):
            store.register("alice", "alice2@example.com", "password456")


class TestAuthentication:
    """Tests for user authentication."""

    def test_authenticate_valid(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        assert store.authenticate("alice", "securepass123") is True

    def test_authenticate_wrong_password(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        assert store.authenticate("alice", "wrongpass") is False

    def test_authenticate_nonexistent_user(self):
        store = UserStore()
        assert store.authenticate("ghost", "password") is False

    def test_authenticate_deactivated_user(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        store.deactivate("alice")
        assert store.authenticate("alice", "securepass123") is False


class TestPasswordSecurity:
    """Tests for password hashing — these WILL FAIL due to bugs."""

    def test_password_is_hashed_not_plaintext(self):
        """Password should be stored as a hash, not plain text."""
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        user = store._users["alice"]
        # The stored password_hash should NOT equal the raw password
        assert user["password_hash"] != "securepass123", \
            "Password is stored in plain text! Must be hashed."

    def test_password_hash_matches_expected(self):
        """Stored hash should match hash_password() output."""
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        user = store._users["alice"]
        expected_hash = hash_password("securepass123")
        assert user["password_hash"] == expected_hash


class TestProfile:
    """Tests for profile retrieval."""

    def test_get_profile_exists(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        profile = store.get_profile("alice")
        assert profile["username"] == "alice"
        assert profile["email"] == "alice@example.com"

    def test_get_profile_no_password_leak(self):
        """Profile should NOT contain password_hash."""
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        profile = store.get_profile("alice")
        assert "password_hash" not in profile, \
            "Profile leaks password_hash! Must be removed."

    def test_get_profile_nonexistent(self):
        store = UserStore()
        with pytest.raises(KeyError):
            store.get_profile("ghost")


class TestDeactivation:
    """Tests for user deactivation."""

    def test_deactivate_user(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        assert store.deactivate("alice") is True

    def test_deactivate_removes_from_list(self):
        store = UserStore()
        store.register("alice", "alice@example.com", "securepass123")
        store.register("bob", "bob@example.com", "password456")
        store.deactivate("alice")
        assert "alice" not in store.list_users()
        assert "bob" in store.list_users()

    def test_deactivate_nonexistent(self):
        store = UserStore()
        with pytest.raises(KeyError):
            store.deactivate("ghost")
