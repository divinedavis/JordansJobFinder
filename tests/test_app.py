import os
import tempfile
import unittest
from unittest.mock import patch


DB_FD, DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app  # noqa: E402
from app.db import get_db, init_db  # noqa: E402
from app.models import SavedSearch, Subscription, User  # noqa: E402


class AppSmokeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = create_app()
        cls.app.testing = True
        with cls.app.app_context():
            init_db()

    @classmethod
    def tearDownClass(cls):
        os.close(DB_FD)
        os.unlink(DB_PATH)

    def setUp(self):
        self.client = self.app.test_client()
        with self.app.app_context():
            db = get_db()
            db.query(SavedSearch).delete()
            db.query(Subscription).delete()
            db.query(User).delete()
            user = User(email="test@example.com")
            user.set_password("password123")
            db.add(user)
            db.commit()
            db.refresh(user)
            db.add(Subscription(user_id=user.id))
            db.commit()
            self.user_id = user.id

    def _login(self):
        with self.client.session_transaction() as session:
            session["user_id"] = self.user_id

    def test_public_pages_render(self):
        for path in ["/", "/sign-in", "/login"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)

    def test_private_pages_render_with_session(self):
        self._login()
        for path in ["/dashboard", "/settings", "/search", "/billing"]:
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200)

    def test_signup_creates_account_and_logs_user_in(self):
        response = self.client.post(
            "/sign-in",
            data={
                "email": "newuser@example.com",
                "password": "newpassword123",
                "confirm_password": "newpassword123",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Account created.", response.data)
        with self.app.app_context():
            db = get_db()
            user = db.query(User).filter(User.email == "newuser@example.com").one_or_none()
            self.assertIsNotNone(user)
            self.assertTrue(user.check_password("newpassword123"))

    def test_login_accepts_valid_password(self):
        response = self.client.post(
            "/login",
            data={
                "email": "test@example.com",
                "password": "password123",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Signed in.", response.data)

    def test_login_rejects_invalid_password(self):
        response = self.client.post(
            "/login",
            data={
                "email": "test@example.com",
                "password": "wrongpass123",
            },
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Invalid email or password.", response.data)

    def test_billing_checkout_gracefully_blocks_when_stripe_missing(self):
        self._login()
        response = self.client.post(
            "/billing/checkout/city-plan",
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Stripe is not configured yet.", response.data)

    def test_billing_success_updates_subscription_flags(self):
        self._login()
        with patch(
            "app.routes.sync_checkout_result",
            return_value="City replacement plan is now active.",
        ) as sync_mock:
            response = self.client.get(
                "/billing?checkout=success&session_id=cs_test_123",
                follow_redirects=True,
            )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"City replacement plan is now active.", response.data)
        sync_mock.assert_called_once_with("cs_test_123")

    def test_cancel_city_plan_reverts_to_free_cities_without_stripe(self):
        self._login()
        with self.app.app_context():
            db = get_db()
            user = db.get(User, self.user_id)
            db.add(
                SavedSearch(
                    user_id=user.id,
                    title_slug="technical-product-manager",
                    experience_bucket="3-6",
                    city_1="Chicago, IL",
                    city_2="Dallas, TX",
                    city_3="Seattle, WA",
                    is_paid_city_override=True,
                    change_count=1,
                )
            )
            user.subscription.city_override_active = True
            user.subscription.status = "active"
            db.commit()

        response = self.client.post("/billing/cancel-city-plan", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"City plan cancelled", response.data)

        with self.app.app_context():
            db = get_db()
            user = db.get(User, self.user_id)
            self.assertFalse(user.subscription.city_override_active)
            self.assertEqual(user.subscription.status, "free")
            self.assertEqual(user.saved_search.city_1, "New York, NY")
            self.assertEqual(user.saved_search.city_2, "Atlanta, GA")
            self.assertEqual(user.saved_search.city_3, "Miami, FL")
            self.assertFalse(user.saved_search.is_paid_city_override)

    def test_delete_account_removes_user_history(self):
        self._login()
        with self.app.app_context():
            db = get_db()
            user = db.get(User, self.user_id)
            db.add(
                SavedSearch(
                    user_id=user.id,
                    title_slug="technical-program-manager",
                    experience_bucket="7-9",
                    city_1="New York, NY",
                    city_2="Atlanta, GA",
                    city_3="Miami, FL",
                    is_paid_city_override=False,
                    change_count=0,
                )
            )
            db.commit()

        response = self.client.post("/account/delete", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"have been deleted", response.data)

        with self.app.app_context():
            db = get_db()
            deleted = db.query(User).filter(User.id == self.user_id).one_or_none()
            self.assertIsNone(deleted)


if __name__ == "__main__":
    unittest.main()
