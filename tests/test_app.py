import os
import tempfile
import unittest
from unittest.mock import patch


DB_FD, DB_PATH = tempfile.mkstemp(suffix=".db")
os.environ["DATABASE_URL"] = f"sqlite:///{DB_PATH}"
os.environ["SECRET_KEY"] = "test-secret"

from app import create_app  # noqa: E402
from app.db import get_db, init_db  # noqa: E402
from app.ingest import normalize_legacy_job  # noqa: E402
from app.matching import ParsedExperience, match_job_for_user, parse_experience_years  # noqa: E402
from app.models import SavedSearch, Subscription, User  # noqa: E402
from scraper import extract_experience_bounds, parse_salary  # noqa: E402


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


class MatchingLogicTest(unittest.TestCase):
    def test_superuser_no_longer_requires_technical_keyword(self):
        matched = match_job_for_user(
            "technical-product-manager",
            "10+",
            "Senior Product Manager - Vice President",
            "Requires 8+ years of product management experience.",
            salary_min=None,
            salary_max=None,
            user_email="divinejdavis@gmail.com",
        )
        self.assertTrue(matched)

    def test_parse_experience_years_handles_embedded_requirement(self):
        parsed = parse_experience_years(
            "Technical Program Manager",
            "Candidates require 8 or more years of relevant product delivery experience.",
        )
        self.assertEqual(parsed, ParsedExperience(min_years=8, max_years=None))

    def test_scraper_parse_salary_handles_k_ranges(self):
        self.assertEqual(
            parse_salary("Compensation range: $180k - $240k annually"),
            (180000, 240000),
        )

    def test_scraper_extract_experience_handles_word_numbers(self):
        self.assertEqual(
            extract_experience_bounds("Minimum eight years of professional experience required."),
            (8, None),
        )

    def test_parse_experience_years_prefers_required_over_preferred(self):
        parsed = parse_experience_years(
            "Technical Product Manager",
            "Requires 8+ years of product management experience and 15+ years preferred in leadership roles.",
        )
        self.assertEqual(parsed, ParsedExperience(min_years=8, max_years=None))

    def test_normalize_legacy_job_parses_salary_from_description(self):
        normalized = normalize_legacy_job(
            {
                "title": "Senior Product Manager - Vice President",
                "company": "Morgan Stanley",
                "url": "https://example.com/job",
                "city": "nyc",
                "salary": "See posting",
                "posted": "Posted Today",
                "location": "New York, New York, United States of America",
                "description": "New York, NY expected annual base salary for this role is $180,000 - $220,000.",
            }
        )
        self.assertEqual(normalized["salary_min"], 180000)
        self.assertEqual(normalized["salary_max"], 220000)


if __name__ == "__main__":
    unittest.main()
