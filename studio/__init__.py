import os
import secrets
from datetime import timedelta
from pathlib import Path

from flask import Flask, request
from dotenv import load_dotenv

from .database import init_app as init_database
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
        MAX_CONTENT_LENGTH=16 * 1024,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=os.environ.get("COOKIE_SECURE", "0") == "1",
        PERMANENT_SESSION_LIFETIME=timedelta(hours=4),
        TEMPLATES_AUTO_RELOAD=False,
    )

    init_database(app)
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
            title_ar="الصفحة غير موجودة — NOOR",
            title_en="Page not found — NOOR",
        ), 404

    @app.errorhandler(413)
    def request_too_large(_error):
        from flask import render_template

        return render_template(
            "error.html",
            code=413,
            page="",
            title_ar="الطلب كبير جداً — NOOR",
            title_en="Request too large — NOOR",
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
