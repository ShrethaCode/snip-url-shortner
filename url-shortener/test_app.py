"""Automated test suite for Snip URL Shortener.

Run tests with:
    python3 -m unittest test_app.py
"""

import os
import tempfile
import unittest
from datetime import datetime, timedelta, timezone

import app


class SnipTestCase(unittest.TestCase):
    def setUp(self):
        # Create a temporary file database for tests so we don't touch production data
        self.db_fd, self.temp_db_path = tempfile.mkstemp()
        app.DATABASE = self.temp_db_path
        app.init_db(self.temp_db_path)

        app.app.config["TESTING"] = True
        app.app.config["SECRET_KEY"] = "test-secret-key"
        self.client = app.app.test_client()

    def tearDown(self):
        os.close(self.db_fd)
        os.unlink(self.temp_db_path)

    # -----------------------------------------------------------------------
    # Unit Tests: URL Normalization & Validation
    # -----------------------------------------------------------------------

    def test_normalize_url_valid(self):
        self.assertEqual(
            app.normalize_url("https://example.com/blog"),
            "https://example.com/blog",
        )
        self.assertEqual(
            app.normalize_url("http://sub.domain.org"),
            "http://sub.domain.org",
        )

    def test_normalize_url_adds_scheme(self):
        self.assertEqual(
            app.normalize_url("example.com/test"),
            "https://example.com/test",
        )
        self.assertEqual(
            app.normalize_url("google.com"),
            "https://google.com",
        )

    def test_normalize_url_invalid(self):
        self.assertIsNone(app.normalize_url(""))
        self.assertIsNone(app.normalize_url("   "))
        self.assertIsNone(app.normalize_url("not a url"))
        self.assertIsNone(app.normalize_url("ftp://ftp.example.com"))
        self.assertIsNone(app.normalize_url("javascript:alert(1)"))

    def test_normalize_url_prevents_loop(self):
        # Prevent shortening links pointing back to our own host
        self.assertIsNone(
            app.normalize_url("http://127.0.0.1:5000/xyz", host="127.0.0.1:5000")
        )
        self.assertIsNone(
            app.normalize_url("https://snip.domain.com/abc", host="snip.domain.com")
        )

    # -----------------------------------------------------------------------
    # Unit Tests: Custom Short Codes
    # -----------------------------------------------------------------------

    def test_validate_custom_code(self):
        valid, _ = app.validate_custom_code("my-link_123")
        self.assertTrue(valid)

        # Too short (< 3)
        valid, err = app.validate_custom_code("ab")
        self.assertFalse(valid)
        self.assertIn("at least 3 characters", err)

        # Too long (> 30)
        valid, err = app.validate_custom_code("a" * 35)
        self.assertFalse(valid)
        self.assertIn("at most 30 characters", err)

        # Invalid characters
        valid, err = app.validate_custom_code("my link!")
        self.assertFalse(valid)
        self.assertIn("can only contain letters", err)

        # Reserved keywords
        for keyword in ("api", "stats", "delete", "static", "qr"):
            valid, err = app.validate_custom_code(keyword)
            self.assertFalse(valid)
            self.assertIn("reserved", err)

    # -----------------------------------------------------------------------
    # Unit Tests: Expiration Parsing
    # -----------------------------------------------------------------------

    def test_expiry_parsing(self):
        self.assertIsNone(app.parse_expiry("never"))
        self.assertIsNone(app.parse_expiry(None))

        exp_1h = app.parse_expiry("1h")
        self.assertIsNotNone(exp_1h)
        dt = datetime.strptime(exp_1h, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = (dt - now).total_seconds()
        self.assertTrue(3500 < diff < 3700)

        # Test 24h, 7d, 30d
        self.assertIsNotNone(app.parse_expiry("24h"))
        self.assertIsNotNone(app.parse_expiry("7d"))
        self.assertIsNotNone(app.parse_expiry("30d"))

        # Test is_expired
        past_str = (now - timedelta(minutes=5)).strftime("%Y-%m-%d %H:%M:%S")
        future_str = (now + timedelta(hours=2)).strftime("%Y-%m-%d %H:%M:%S")
        self.assertTrue(app.is_expired(past_str))
        self.assertFalse(app.is_expired(future_str))
        self.assertFalse(app.is_expired(None))

    # -----------------------------------------------------------------------
    # Integration Tests: Web Flow & Redirects
    # -----------------------------------------------------------------------

    def test_shorten_flow_and_redirect(self):
        # 1. Post to shorten a URL
        response = self.client.post(
            "/",
            data={"long_url": "https://python.org", "custom_code": "", "expiry": "never"},
            follow_redirects=True,
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Link shortened successfully", response.data)

        # 2. Get code from database
        links = app.get_recent_links(db_path=self.temp_db_path)
        self.assertEqual(len(links), 1)
        code = links[0]["short_code"]
        self.assertEqual(links[0]["clicks"], 0)

        # 3. Follow redirect
        redirect_resp = self.client.get(f"/{code}")
        self.assertEqual(redirect_resp.status_code, 302)
        self.assertEqual(redirect_resp.headers["Location"], "https://python.org")

        # 4. Check that clicks incremented
        updated_link = app.get_link_by_code(code, db_path=self.temp_db_path)
        self.assertEqual(updated_link["clicks"], 1)

    def test_custom_code_and_collision(self):
        code, err = app.create_link(
            "https://example.com/one",
            custom_code="my-alias",
            db_path=self.temp_db_path,
        )
        self.assertEqual(code, "my-alias")
        self.assertIsNone(err)

        # Trying to use the same code again should return error
        code2, err2 = app.create_link(
            "https://example.com/two",
            custom_code="my-alias",
            db_path=self.temp_db_path,
        )
        self.assertIsNone(code2)
        self.assertIn("already taken", err2)

    def test_expired_link_returns_410(self):
        # Create a link that expired 1 hour ago
        now = datetime.now(timezone.utc)
        past_str = (now - timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S")

        with app.db_connection(self.temp_db_path) as db:
            db.execute(
                "INSERT INTO links (short_code, long_url, expires_at) VALUES (?, ?, ?)",
                ("oldone", "https://old-site.com", past_str),
            )

        resp = self.client.get("/oldone")
        self.assertEqual(resp.status_code, 410)
        self.assertIn(b"This link has expired", resp.data)

    def test_delete_link(self):
        code, _ = app.create_link("https://to-delete.com", db_path=self.temp_db_path)
        self.assertIsNotNone(app.get_link_by_code(code, db_path=self.temp_db_path))

        # Delete via POST
        del_resp = self.client.post(f"/delete/{code}", follow_redirects=True)
        self.assertEqual(del_resp.status_code, 200)

        # Link should be gone
        self.assertIsNone(app.get_link_by_code(code, db_path=self.temp_db_path))
        not_found_resp = self.client.get(f"/{code}")
        self.assertEqual(not_found_resp.status_code, 404)

    def test_stats_page(self):
        code, _ = app.create_link("https://stat-check.com", custom_code="stat-test", db_path=self.temp_db_path)
        resp = self.client.get(f"/stats/{code}")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"stat-check.com", resp.data)
        self.assertIn(b"stat-test", resp.data)

    # -----------------------------------------------------------------------
    # Integration Tests: RESTful JSON API
    # -----------------------------------------------------------------------

    def test_api_shorten_and_stats(self):
        # 1. POST /api/shorten
        payload = {
            "url": "https://flask.palletsprojects.com",
            "custom_code": "flask-docs",
            "expiry": "7d",
        }
        res = self.client.post("/api/shorten", json=payload)
        self.assertEqual(res.status_code, 201)
        data = res.get_json()
        self.assertTrue(data["success"])
        self.assertEqual(data["short_code"], "flask-docs")
        self.assertIn("flask-docs", data["short_url"])

        # 2. GET /api/stats/<short_code>
        stats_res = self.client.get("/api/stats/flask-docs")
        self.assertEqual(stats_res.status_code, 200)
        stats_data = stats_res.get_json()
        self.assertEqual(stats_data["clicks"], 0)
        self.assertEqual(stats_data["long_url"], "https://flask.palletsprojects.com")
        self.assertFalse(stats_data["is_expired"])

        # 3. GET /api/links
        links_res = self.client.get("/api/links?limit=5")
        self.assertEqual(links_res.status_code, 200)
        links_data = links_res.get_json()
        self.assertEqual(links_data["count"], 1)

        # 4. DELETE /api/links/<short_code>
        delete_res = self.client.delete("/api/links/flask-docs")
        self.assertEqual(delete_res.status_code, 200)
        self.assertTrue(delete_res.get_json()["success"])

        # 5. GET /api/stats on deleted returns 404 JSON
        deleted_stats = self.client.get("/api/stats/flask-docs")
        self.assertEqual(deleted_stats.status_code, 404)
        self.assertFalse(deleted_stats.get_json()["success"])

    def test_api_invalid_url(self):
        res = self.client.post("/api/shorten", json={"url": "not a link"})
        self.assertEqual(res.status_code, 400)
        data = res.get_json()
        self.assertFalse(data["success"])

    def test_api_conflict(self):
        self.client.post("/api/shorten", json={"url": "https://a.com", "custom_code": "same-alias"})
        res2 = self.client.post("/api/shorten", json={"url": "https://b.com", "custom_code": "same-alias"})
        self.assertEqual(res2.status_code, 409)
        self.assertIn("already taken", res2.get_json()["error"])

    def test_api_404_json(self):
        res = self.client.get("/api/not-an-endpoint")
        self.assertEqual(res.status_code, 404)
        self.assertTrue(res.is_json)
        self.assertFalse(res.get_json()["success"])


if __name__ == "__main__":
    unittest.main()
