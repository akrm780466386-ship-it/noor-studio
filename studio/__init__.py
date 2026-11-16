import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, request
from dotenv import load_dotenv

from .database import init_app as init_database, get_db, get_db
from .routes import site


def create_app():
    load_dotenv()
    app = Flask(__name__, instance_relative_config=True)
    secret = os.environ.get("APP_SECRET", "")
    if len(secret) < 32:
        raise RuntimeError(
            "APP_SECRET must be set to a unique random value of at least 32 characters."
        )

    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    app.config.update(
        SECRET_KEY=secret,
        DUMMY_PASSWORD_SALT=secrets.token_bytes(16),
        DATABASE=os.environ.get(
            "DATABASE_PATH", str(Path(app.instance_path) / "noor.sqlite3")
        ),
        DATABASE_URL=os.environ.get("DATABASE_URL", "").strip(),
        LEGACY_DATABASE_PATH=os.environ.get(
            "LEGACY_DATABASE_PATH",
            os.environ.get("DATABASE_PATH", str(Path(app.instance_path) / "noor.sqlite3")),
        ),
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
        TEMPLATES_AUTO_RELOAD=False,
    )

    init_database(app)
    bootstrap_username = os.environ.get("ADMIN_BOOTSTRAP_USERNAME", "").strip().lower()
    bootstrap_password = os.environ.get("ADMIN_BOOTSTRAP_PASSWORD", "")
    if bootstrap_username and bootstrap_password:
        import re
        if not re.fullmatch(r"[a-zA-Z0-9._-]{3,80}", bootstrap_username):
            raise RuntimeError("ADMIN_BOOTSTRAP_USERNAME is invalid.")
        if len(bootstrap_password) < 14 or len(bootstrap_password) > 1024:
            raise RuntimeError("ADMIN_BOOTSTRAP_PASSWORD must contain 14-1024 characters.")
        with app.app_context():
            existing_admin = get_db().execute(
                "SELECT username FROM admin_users WHERE active = 1 LIMIT 1"
            ).fetchone()
            if existing_admin is None:
                from .security import hash_password
                salt = secrets.token_bytes(16)
                get_db().execute(
                    "INSERT INTO admin_users (username, password_hash, password_salt) VALUES (?, ?, ?)",
                    (bootstrap_username, hash_password(bootstrap_password, salt), salt),
                )
                get_db().commit()
    app.register_blueprint(site)

    @app.context_processor
    def provide_csrf_token():
        from .security import csrf_token

        return {"csrf_token": csrf_token}

    @app.errorhandler(404)
    def not_found(_error):
        from flask import render_template

        return render_template(
            "error.html",
            code=404,
            page="",
            title_ar="الصفحة غير موجودة — AKRAM DESIGN",
            title_en="Page not found — AKRAM DESIGN",
        ), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        from flask import render_template

        return render_template(
            "error.html",
            code=413,
            page="",
            title_ar="الطلب كبير جداً — AKRAM DESIGN",
            title_en="Request too large — AKRAM DESIGN",
        ), 413

    @app.after_request
    def set_security_headers(response):
        response.headers["Content-Security-Policy"] = (
            "default-src 'self'; "
            "img-src 'self' https:; "
            "style-src 'self' https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com; "
            "script-src 'self'; "
            "base-uri 'self'; form-action 'self'; frame-ancestors 'none'"
        )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        response.headers["Permissions-Policy"] = (
            "camera=(), microphone=(), geolocation=()"
        )
        if os.environ.get("COOKIE_SECURE", "0") == "1":
            response.headers["Strict-Transport-Security"] = (
                "max-age=31536000; includeSubDomains"
            )
        if request.path.endswith(".js") and response.mimetype == "text/plain":
            response.mimetype = "text/javascript"
        return response

    return app
