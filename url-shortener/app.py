"""Snip — A modern, full-featured URL Shortener built with Flask & SQLite.

Features:
- Fast URL shortening with collision-resistant 6-character random codes.
- Custom vanity aliases (e.g. /my-project).
- Optional link expiration (1 hour, 24 hours, 7 days, 30 days, or never).
- Per-link analytics & click tracking (/stats/<code>).
- Offline QR Code generation for instant sharing.
- RESTful JSON API (/api/shorten, /api/stats/<code>, /api/links).
- Full link management (deletion, search/filter).

Run it with:
    python app.py
Then open:
    http://127.0.0.1:5000
"""

import os
import re
import secrets
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import urlparse

from flask import (
    Flask,
    abort,
    flash,
    jsonify,
    redirect,
    render_template,
    request,
    url_for,
)

BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / "links.db"

# Characters that can appear in generated short codes (a-z, A-Z, 0-9).
ALPHABET = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
CODE_LENGTH = 6

# Reserved paths that cannot be claimed as custom short codes
RESERVED_CODES = {
    "api",
    "stats",
    "delete",
    "static",
    "qr",
    "export",
    "health",
    "favicon.ico",
    "robots.txt",
}

# Allowed custom code pattern: 3 to 30 alphanumeric characters, hyphens, or underscores
CUSTOM_CODE_REGEX = re.compile(r"^[a-zA-Z0-9_-]{3,30}$")

app = Flask(__name__)
# Secret key enables secure flash messaging between requests
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "snip-development-secret-key-39281")


# ---------------------------------------------------------------------------
# Database Helpers & Migration
# ---------------------------------------------------------------------------

@contextmanager
def db_connection(db_path=None):
    """Open a database connection, commit on success, roll back on error, always close."""
    target_db = db_path or DATABASE
    connection = sqlite3.connect(target_db)
    connection.row_factory = sqlite3.Row  # lets us access columns by name: row["short_code"]
    try:
        with connection:  # commits automatically if no exception occurs
            yield connection
    finally:
        connection.close()


def init_db(db_path=None):
    """Create the links table and automatically apply migrations if columns are missing."""
    with db_connection(db_path) as db:
        # Base table creation
        db.execute(
            """
            CREATE TABLE IF NOT EXISTS links (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                short_code  TEXT UNIQUE NOT NULL,
                long_url    TEXT NOT NULL,
                clicks      INTEGER NOT NULL DEFAULT 0,
                created_at  TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                expires_at  TEXT
            )
            """
        )

        # Index for fast lookup on short_code
        db.execute(
            "CREATE INDEX IF NOT EXISTS idx_links_short_code ON links (short_code)"
        )

        # Migration helper: add expires_at column if an older database exists
        columns = [row["name"] for row in db.execute("PRAGMA table_info(links)").fetchall()]
        if "expires_at" not in columns:
            db.execute("ALTER TABLE links ADD COLUMN expires_at TEXT")


# ---------------------------------------------------------------------------
# Helper Functions
# ---------------------------------------------------------------------------

def make_short_code(length=CODE_LENGTH):
    """Generate an unpredictable random alphanumeric string."""
    return "".join(secrets.choice(ALPHABET) for _ in range(length))


def normalize_url(raw_url, host=None):
    """Sanitize and validate user-submitted URL, preventing loops and malformed inputs.

    Returns the clean URL string, or None if invalid.
    """
    if not raw_url:
        return None

    raw_url = raw_url.strip()
    if not raw_url or any(c.isspace() for c in raw_url):
        return None

    # Prepend https:// if the user typed example.com or path without scheme
    if "://" not in raw_url:
        raw_url = "https://" + raw_url

    try:
        parsed = urlparse(raw_url)
    except Exception:
        return None

    # Enforce safe schemes
    if parsed.scheme not in ("http", "https"):
        return None

    # Must contain a valid host domain
    if not parsed.netloc or any(c.isspace() for c in parsed.netloc):
        return None

    hostname = parsed.hostname
    if not hostname:
        return None

    # Ensure hostname contains a dot (e.g., example.com) or is localhost
    if "." not in hostname and hostname != "localhost":
        return None

    # Loop prevention: cannot shorten our own shortener URL
    if host and parsed.netloc.lower() == host.lower():
        return None

    return raw_url


def validate_custom_code(code):
    """Validate a user-supplied custom short code alias.

    Returns (is_valid, error_message).
    """
    if not code:
        return False, "Custom code cannot be empty."

    code = code.strip()

    if code.lower() in RESERVED_CODES:
        return False, f"'{code}' is a reserved keyword and cannot be used as an alias."

    if len(code) < 3:
        return False, "Custom code must be at least 3 characters long."

    if len(code) > 30:
        return False, "Custom code must be at most 30 characters long."

    if not CUSTOM_CODE_REGEX.match(code):
        return False, "Custom code can only contain letters, numbers, hyphens (-), and underscores (_)."

    return True, None


def parse_expiry(expiry_choice):
    """Calculate expiration UTC ISO timestamp based on selected duration.

    Accepted choices: '1h', '24h', '7d', '30d', or None/'never'.
    """
    if not expiry_choice or expiry_choice in ("never", "none", ""):
        return None

    now = datetime.now(timezone.utc)
    if expiry_choice == "1h":
        expires = now + timedelta(hours=1)
    elif expiry_choice in ("24h", "1d"):
        expires = now + timedelta(days=1)
    elif expiry_choice == "7d":
        expires = now + timedelta(days=7)
    elif expiry_choice == "30d":
        expires = now + timedelta(days=30)
    else:
        # If integer days passed
        try:
            days = float(expiry_choice)
            expires = now + timedelta(days=days)
        except ValueError:
            return None

    return expires.strftime("%Y-%m-%d %H:%M:%S")


def is_expired(expires_at_str):
    """Check if an expiration timestamp string is in the past."""
    if not expires_at_str:
        return False

    now = datetime.now(timezone.utc)
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d %H:%M:%S%z"):
        try:
            dt = datetime.strptime(expires_at_str, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return now > dt
        except ValueError:
            continue
    return False


def create_link(long_url, custom_code=None, expiry_choice=None, db_path=None):
    """Create a new short link, returning (code, error_message)."""
    expires_at = parse_expiry(expiry_choice)

    with db_connection(db_path) as db:
        if custom_code:
            custom_code = custom_code.strip()
            valid, err = validate_custom_code(custom_code)
            if not valid:
                return None, err

            # Check for existing code collision
            existing = db.execute(
                "SELECT id FROM links WHERE short_code = ?", (custom_code,)
            ).fetchone()
            if existing is not None:
                return None, f"The alias '{custom_code}' is already taken. Please choose another one."

            db.execute(
                "INSERT INTO links (short_code, long_url, expires_at) VALUES (?, ?, ?)",
                (custom_code, long_url, expires_at),
            )
            return custom_code, None

        # Random code generation with collision retry loop
        max_attempts = 10
        for _ in range(max_attempts):
            code = make_short_code()
            try:
                db.execute(
                    "INSERT INTO links (short_code, long_url, expires_at) VALUES (?, ?, ?)",
                    (code, long_url, expires_at),
                )
                return code, None
            except sqlite3.IntegrityError:
                continue

        return None, "Failed to generate a unique code. Please try again."


def get_link_by_code(code, db_path=None):
    """Fetch a link row from the database by short code."""
    with db_connection(db_path) as db:
        return db.execute(
            "SELECT id, short_code, long_url, clicks, created_at, expires_at FROM links WHERE short_code = ?",
            (code,),
        ).fetchone()


def increment_click(code, db_path=None):
    """Atomically increment the click counter for a short link."""
    with db_connection(db_path) as db:
        db.execute(
            "UPDATE links SET clicks = clicks + 1 WHERE short_code = ?",
            (code,),
        )


def delete_link(code, db_path=None):
    """Delete a link by its short code. Returns True if deleted, False if not found."""
    with db_connection(db_path) as db:
        cursor = db.execute("DELETE FROM links WHERE short_code = ?", (code,))
        return cursor.rowcount > 0


def get_recent_links(limit=30, db_path=None):
    """Fetch the latest links, formatting expiration and status."""
    with db_connection(db_path) as db:
        rows = db.execute(
            """
            SELECT id, short_code, long_url, clicks, created_at, expires_at
            FROM links
            ORDER BY id DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()

    result = []
    for row in rows:
        item = dict(row)
        item["is_expired"] = is_expired(row["expires_at"])
        result.append(item)
    return result


# ---------------------------------------------------------------------------
# Web UI Routes
# ---------------------------------------------------------------------------

@app.route("/", methods=["GET", "POST"])
def index():
    error = None
    created_link = None
    long_url_val = ""
    custom_code_val = ""
    expiry_val = "never"

    if request.method == "POST":
        long_url_val = request.form.get("long_url", "")
        custom_code_val = request.form.get("custom_code", "").strip()
        expiry_val = request.form.get("expiry", "never")

        clean_url = normalize_url(long_url_val, host=request.host)

        if not clean_url:
            error = "Please enter a valid web URL (e.g. example.com or https://site.com/path)"
        else:
            custom = custom_code_val if custom_code_val else None
            code, err = create_link(clean_url, custom_code=custom, expiry_choice=expiry_val)

            if err:
                error = err
            else:
                full_short_url = url_for("follow_link", short_code=code, _external=True)
                stats_url = url_for("link_stats", short_code=code)
                created_link = {
                    "code": code,
                    "short_url": full_short_url,
                    "long_url": clean_url,
                    "stats_url": stats_url,
                }
                flash(f"Link shortened successfully: /{code}", "success")
                # Clear form inputs after successful creation
                long_url_val = ""
                custom_code_val = ""
                expiry_val = "never"

    return render_template(
        "index.html",
        error=error,
        created_link=created_link,
        long_url_val=long_url_val,
        custom_code_val=custom_code_val,
        expiry_val=expiry_val,
        links=get_recent_links(),
    )


@app.route("/<short_code>")
def follow_link(short_code):
    """Look up the short code, check expiration, increment clicks, and redirect."""
    row = get_link_by_code(short_code)

    if row is None:
        abort(404)

    # Check if link has passed its expiration time
    if is_expired(row["expires_at"]):
        return render_template("410.html", code=short_code, row=dict(row)), 410

    # Track click and redirect (HTTP 302 Temporary Redirect)
    increment_click(short_code)
    return redirect(row["long_url"], code=302)


@app.route("/stats/<short_code>")
def link_stats(short_code):
    """Detailed analytics, metadata, and QR code view for a specific link."""
    row = get_link_by_code(short_code)
    if row is None:
        abort(404)

    link_data = dict(row)
    link_data["is_expired"] = is_expired(row["expires_at"])
    link_data["short_url"] = url_for("follow_link", short_code=short_code, _external=True)

    return render_template("stats.html", link=link_data)


@app.route("/delete/<short_code>", methods=["POST"])
def delete_link_route(short_code):
    """Delete a link by code and redirect to dashboard with a flash message."""
    deleted = delete_link(short_code)
    if deleted:
        flash(f"Link /{short_code} was deleted successfully.", "info")
    else:
        flash(f"Link /{short_code} could not be found.", "error")
    return redirect(url_for("index"))


# ---------------------------------------------------------------------------
# RESTful JSON API Routes
# ---------------------------------------------------------------------------

@app.route("/api/shorten", methods=["POST"])
def api_shorten():
    """Create a shortened link via JSON API.

    JSON payload:
        {
            "url": "https://example.com/long/path",
            "custom_code": "optional-custom-alias",
            "expiry": "7d"  (or "1h", "24h", "30d", "never")
        }
    """
    data = request.get_json(silent=True) or {}
    raw_url = data.get("url") or request.form.get("url")
    custom_code = (data.get("custom_code") or request.form.get("custom_code") or "").strip()
    expiry = data.get("expiry") or request.form.get("expiry") or "never"

    clean_url = normalize_url(raw_url, host=request.host)
    if not clean_url:
        return jsonify({
            "success": False,
            "error": "A valid 'url' is required (e.g. 'https://example.com')."
        }), 400

    code, err = create_link(
        clean_url,
        custom_code=custom_code if custom_code else None,
        expiry_choice=expiry,
    )

    if err:
        status_code = 409 if "already taken" in err else 400
        return jsonify({"success": False, "error": err}), status_code

    row = get_link_by_code(code)
    short_url = url_for("follow_link", short_code=code, _external=True)
    stats_url = url_for("link_stats", short_code=code, _external=True)

    return jsonify({
        "success": True,
        "short_code": code,
        "short_url": short_url,
        "long_url": clean_url,
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "stats_url": stats_url,
    }), 201


@app.route("/api/stats/<short_code>", methods=["GET"])
def api_stats(short_code):
    """Retrieve JSON analytics for a given short code."""
    row = get_link_by_code(short_code)
    if row is None:
        return jsonify({"success": False, "error": "Link not found."}), 404

    return jsonify({
        "success": True,
        "short_code": row["short_code"],
        "short_url": url_for("follow_link", short_code=short_code, _external=True),
        "long_url": row["long_url"],
        "clicks": row["clicks"],
        "created_at": row["created_at"],
        "expires_at": row["expires_at"],
        "is_expired": is_expired(row["expires_at"]),
    }), 200


@app.route("/api/links", methods=["GET"])
def api_links():
    """List recent links in JSON."""
    limit = min(request.args.get("limit", default=20, type=int), 100)
    links = get_recent_links(limit=limit)
    for link in links:
        link["short_url"] = url_for("follow_link", short_code=link["short_code"], _external=True)
    return jsonify({"success": True, "count": len(links), "links": links}), 200


@app.route("/api/links/<short_code>", methods=["DELETE"])
def api_delete(short_code):
    """Delete a link via API."""
    if delete_link(short_code):
        return jsonify({"success": True, "message": f"Link /{short_code} deleted."}), 200
    return jsonify({"success": False, "error": "Link not found."}), 404


# ---------------------------------------------------------------------------
# Error Handlers
# ---------------------------------------------------------------------------

@app.errorhandler(404)
def not_found_error(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "Resource not found."}), 404
    return render_template("404.html"), 404


@app.errorhandler(410)
def gone_error(_error):
    if request.path.startswith("/api/"):
        return jsonify({"success": False, "error": "This link has expired."}), 410
    return render_template("410.html"), 410


# ---------------------------------------------------------------------------
# Application Initialization
# ---------------------------------------------------------------------------

init_db()

if __name__ == "__main__":
    # debug=True enables live code reloading and detailed tracebacks
    app.run(debug=True, port=5000)
