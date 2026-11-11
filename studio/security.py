import hashlib
import hmac
import secrets
from functools import wraps

from flask import abort, current_app, g, redirect, request, session, url_for

from .database import get_db

PASSWORD_ITERATIONS = 600_000


def hash_password(password, salt):
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PASSWORD_ITERATIONS
    )


def csrf_token():
    token = session.get("_csrf")
    if token is None:
        token = secrets.token_urlsafe(32)
        session["_csrf"] = token
    return token


def validate_csrf():
    expected = session.get("_csrf", "")
    provided = request.form.get("_csrf", "")
    if not expected or not hmac.compare_digest(expected, provided):
        abort(400, description="Security token expired. Refresh the page and try again.")


def ip_key():
    address = request.remote_addr or "unknown"
    return hmac.new(
        current_app.config["SECRET_KEY"].encode(), address.encode(), hashlib.sha256
    ).hexdigest()


def admin_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        username = session.get("admin")
        if not username:
            return redirect(url_for("site.admin_login"))
        user = get_db().execute(
            "SELECT username, auth_token FROM admin_users "
            "WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()
        if (
            user is None
            or not session.get("admin_token")
            or not hmac.compare_digest(
                session.get("admin_token", ""), user["auth_token"]
            )
        ):
            session.clear()
            return redirect(url_for("site.admin_login"))
        g.admin_user = user
        return view(*args, **kwargs)

    return wrapped
