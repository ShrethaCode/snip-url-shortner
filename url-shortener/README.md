# ✂️ Snip — Modern URL Shortener

> **A full-featured, lightweight URL Shortener and Analytics app built with Python, Flask, and SQLite.**

Snip transforms long, cumbersome links into clean, shareable short URLs (e.g. `http://127.0.0.1:5000/my-link`). It includes custom vanity aliases, automatic link expiration, per-link click analytics, offline QR code generation, a RESTful JSON API, and an automated test suite.

---

## ✨ Features

- ⚡ **Instant URL Shortening**: Generates collision-resistant, 6-character random alphanumeric codes.
- 🏷️ **Custom Vanity Aliases**: Create custom branded links like `snip/my-portfolio` or `snip/github`.
- ⏳ **Link Expiration (TTL)**: Set links to expire automatically after 1 hour, 24 hours, 7 days, 30 days, or never. Expired links cleanly return HTTP `410 Gone`.
- 📊 **Per-Link Analytics & Stats**: View real-time click tracking, creation timestamps, and active status at `/stats/<code>`.
- 📱 **Built-in Offline QR Codes**: Generate and download instant QR codes for any short link right in the browser (zero external network dependencies).
- 📋 **One-Click Copy**: Instant clipboard copying with animated feedback.
- 🔍 **Live Search & Filter**: Search and filter links in real time by alias or destination URL.
- 🗑️ **Link Management**: Delete short links directly from the dashboard or analytics page.
- 🌐 **RESTful JSON API**: Programmatic endpoints to shorten, inspect, list, and delete links.
- 🧪 **Automated Test Suite**: 15 unit and integration tests covering validation, collision handling, expiration, redirects, and API endpoints using Python's standard `unittest`.
- 🛡️ **Defensive & Safe**: Prevents recursive self-shortening loops, validates protocols, and automatically applies SQLite schema migrations.

---

## 📁 Project Structure

```text
url-shortener/
├── app.py                  # Core backend (Flask routes, SQLite helpers, API endpoints)
├── test_app.py             # Automated unit & integration tests (Python unittest)
├── requirements.txt        # Minimal dependencies (Flask>=3.0)
├── links.db                # SQLite database (auto-created on first run)
├── .gitignore              # Ignores virtualenvs, caches, and database files
├── static/
│   ├── app.js              # Client-side clipboard & live filter scripts
│   ├── qrcode.js           # Offline browser QR Code generator (zero dependencies)
│   └── style.css           # Modern, clean, responsive styles
└── templates/
    ├── index.html          # Main dashboard with form, recent links, and search
    ├── stats.html          # Per-link analytics, QR code display, and deletion
    ├── 404.html            # Custom "Link Not Found" page
    └── 410.html            # Custom "Link Expired" page
```

---

## 🚀 Quick Start

### 1. Set Up Virtual Environment

Open your terminal, navigate to the project directory, and activate Python:

```bash
cd url-shortener

# Create virtual environment (if not already created)
python3 -m venv .venv

# Activate the virtual environment
# On macOS / Linux:
source .venv/bin/activate
# On Windows:
# .venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### 2. Run the Application

```bash
python app.py
```

Then open your browser at **[http://127.0.0.1:5000](http://127.0.0.1:5000)**.  
*(Press `Ctrl+C` in your terminal anytime to stop the server).*

---

## 🧪 Running the Automated Tests

The project includes a comprehensive test suite written with Python's built-in `unittest` module. Tests run in memory using temporary databases without altering your live data.

To run the full test suite:

```bash
python -m unittest test_app.py
```

You should see all tests pass:

```text
...............
----------------------------------------------------------------------
Ran 15 tests in 0.034s

OK
```

---

## 🔌 RESTful JSON API Reference

Snip provides a complete JSON API for integrating with other apps, scripts, or frontend frameworks.

### 1. Shorten a URL
- **Endpoint**: `POST /api/shorten`
- **Headers**: `Content-Type: application/json`
- **Body**:
  ```json
  {
    "url": "https://news.ycombinator.com",
    "custom_code": "hackernews",
    "expiry": "7d"
  }
  ```
  *(Note: `custom_code` and `expiry` are optional. Expiry options: `"1h"`, `"24h"`, `"7d"`, `"30d"`, `"never"`).*

- **Response (`201 Created`)**:
  ```json
  {
    "success": true,
    "short_code": "hackernews",
    "short_url": "http://127.0.0.1:5000/hackernews",
    "long_url": "https://news.ycombinator.com",
    "created_at": "2026-11-13 14:20:00",
    "expires_at": "2026-11-20 14:20:00",
    "stats_url": "http://127.0.0.1:5000/stats/hackernews"
  }
  ```

- **Example curl**:
  ```bash
  curl -X POST http://127.0.0.1:5000/api/shorten \
    -H "Content-Type: application/json" \
    -d '{"url": "https://github.com", "custom_code": "my-gh"}'
  ```

---

### 2. Get Link Analytics
- **Endpoint**: `GET /api/stats/<short_code>`
- **Response (`200 OK`)**:
  ```json
  {
    "success": true,
    "short_code": "my-gh",
    "short_url": "http://127.0.0.1:5000/my-gh",
    "long_url": "https://github.com",
    "clicks": 14,
    "created_at": "2026-11-13 14:00:00",
    "expires_at": null,
    "is_expired": false
  }
  ```

---

### 3. List Recent Links
- **Endpoint**: `GET /api/links?limit=10`
- **Response (`200 OK`)**:
  ```json
  {
    "success": true,
    "count": 2,
    "links": [
      {
        "id": 2,
        "short_code": "my-gh",
        "short_url": "http://127.0.0.1:5000/my-gh",
        "long_url": "https://github.com",
        "clicks": 14,
        "created_at": "2026-11-13 14:00:00",
        "expires_at": null,
        "is_expired": false
      }
    ]
  }
  ```

---

### 4. Delete a Link
- **Endpoint**: `DELETE /api/links/<short_code>`
- **Response (`200 OK`)**:
  ```json
  {
    "success": true,
    "message": "Link /my-gh deleted."
  }
  ```

---

## 💡 Key Concepts for Beginners

As your first full project, here are the core software engineering patterns used in this codebase and why they matter:

1. **Context Managers (`@contextmanager`)**:
   In `app.py`, `db_connection()` ensures that every database connection opens, automatically commits changes on success, rolls back on errors, and closes cleanly even if an exception occurs.
2. **Parameterized SQL Queries (`?` placeholders)**:
   We never format raw user strings directly into SQL (e.g. `f"SELECT * WHERE short_code = '{code}'"`). Using `?` prevents **SQL Injection attacks**.
3. **HTTP Status Codes**:
   - `200 OK`: Successful retrieval.
   - `201 Created`: New resource successfully created via API.
   - `302 Found`: Temporary redirect pointing the browser to the destination URL.
   - `400 Bad Request`: User sent invalid input (e.g. malformed URL).
   - `404 Not Found`: Link does not exist.
   - `409 Conflict`: Custom alias is already taken.
   - `410 Gone`: Link has expired and is permanently inactive.
4. **Automated Schema Migrations**:
   The `init_db()` function checks `PRAGMA table_info(links)`. If a new column (like `expires_at`) was added in an update, it runs `ALTER TABLE links ADD COLUMN ...` automatically without corrupting or deleting existing links!
5. **Separation of Concerns**:
   - `app.py`: Server-side business logic and database interactions.
   - `templates/`: HTML structures and semantic layouts.
   - `static/`: Styling (`style.css`), UX behaviors (`app.js`), and QR rendering (`qrcode.js`).
   - `test_app.py`: Verification that changes don't break existing behavior.

---

## 🚢 Next Steps & Portfolio Ideas

When you're ready to take this project further:
1. **Push to GitHub**:
   ```bash
   git init
   git add .
   git commit -m "feat: complete url shortener with analytics, expiration, and API"
   ```
2. **Deploy to the Cloud**:
   Deploy for free to platforms like **Render**, **Railway**, or **Fly.io** using Gunicorn (`pip install gunicorn`).
3. **Build a Frontend in React / Vue**:
   Connect a React frontend directly to the `/api/shorten` and `/api/links` endpoints!
