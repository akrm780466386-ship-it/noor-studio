# NOOR Studio

A bilingual Arabic/English portfolio with separate pages, persistent light/dark themes, a custom logo loading screen, a SQLite project catalogue, and a password-protected project dashboard.

The store has its own public product catalogue and item pages. From the dashboard, manage Arabic and English names and descriptions, images, SKU, price, optional sale price, currency, stock, and publishing status.

## Requirements

- Python 3.10 or later
- Windows PowerShell, macOS, or Linux
- Internet access for the remote Unsplash demo images and Google Fonts

## Run locally

From this directory, create and activate a virtual environment, then install the dependencies:

```powershell
py -3 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
```

Open `.env` and replace `APP_SECRET` with a unique value generated with:

```powershell
python -c "import secrets; print(secrets.token_hex(32))"
```

Keep the generated secret private. Create the first administrator; the password is requested securely in the terminal and is never stored in plaintext:

```powershell
python -m studio.create_admin
```

Start the local development server:

```powershell
python run.py
```

Open [http://127.0.0.1:5000](http://127.0.0.1:5000). Sign in at `/admin/login`. The SQLite database is created at `instance/noor.sqlite3`, and the first run seeds three editable example projects.

## Pages

- `/` — portfolio home
- `/work` — project index
- `/projects/<slug>` — an individual project page
- `/about` — designer profile
- `/services` — design services
- `/contact` — contact details
- `/shop` and `/products/<slug>` — published products and item details
- `/admin/login` and `/admin` — private overview with product, stock, and portfolio summaries
- `/admin/projects` — manage portfolio projects
- `/admin/products` — add, edit, publish, and remove products
- `/admin/settings` — change the signed-in administrator's password

Every page has a **Dashboard** link in the site header; unauthenticated visitors are sent to the sign-in page. The dashboard can add, edit, and remove portfolio projects as well as shop products. Each product has Arabic and English content, an HTTPS image URL, inventory, and pricing in USD, SAR, AED, or EGP. Mark an item as a draft to keep it private, or set inventory to zero to display it as sold out. Changing the password requires the existing password and a new password of at least 14 characters.

The shop currently supports product discovery and email enquiries. It does not process orders, collect payment, calculate shipping, or automatically decrement stock.

## Production and security

- Do not expose Flask's development server to the public internet. Use a production WSGI server (Waitress is included) behind a correctly configured HTTPS reverse proxy.
- For a local production-server smoke check, run `waitress-serve --listen=127.0.0.1:8000 run:app` and open `http://127.0.0.1:8000`.
- Set a new, private `APP_SECRET` on the production host and set `COOKIE_SECURE=1` only when HTTPS is enabled. Never use the example secret in a deployed environment.
- Create the initial admin with `python -m studio.create_admin`; there is no default username or password.
- Passwords are stored as salted PBKDF2-HMAC-SHA256 hashes. The dashboard uses CSRF tokens, parameterized SQL, escaped templates, login throttling, short-lived HTTP-only SameSite cookies, HTTPS-only image URLs, and security headers.
- Run the built-in checks after a code change: `python -m unittest discover -s tests -v`.
- Keep the `instance` directory private and include the SQLite database in your backup plan. Do not commit `.env`, secrets, or production database files.

The images and sample project copy are placeholders; replace them with the designer's own licensed content before launch.
