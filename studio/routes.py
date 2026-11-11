import hmac
import re
import sqlite3
import time
import secrets
from urllib.parse import urlsplit
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP

from flask import (
    Blueprint,
    abort,
    current_app,
    flash,
    redirect,
    render_template,
    request,
    session,
    url_for,
)

from .database import get_db
from .security import (
    admin_required,
    csrf_token,
    hash_password,
    ip_key,
    validate_csrf,
)

site = Blueprint("site", __name__)
PROJECT_FIELDS = (
    "slug",
    "title_ar",
    "title_en",
    "category_ar",
    "category_en",
    "description_ar",
    "description_en",
    "image_url",
)
SLUG_PATTERN = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
SKU_PATTERN = re.compile(r"^[A-Za-z0-9._/-]{1,60}$")
PRODUCT_FIELDS = (
    "slug",
    "sku",
    "title_ar",
    "title_en",
    "category_ar",
    "category_en",
    "description_ar",
    "description_en",
    "image_url",
    "price",
    "compare_at_price",
    "stock_quantity",
    "currency_code",
    "is_published",
)
CURRENCIES = {"USD", "SAR", "AED", "EGP"}
MAX_PRICE_CENTS = 99_999_999
MAX_STOCK = 1_000_000


def render_page(template, **context):
    titles = {
        "home": ("NOOR — مصممة جرافيك ومديرة فنية", "NOOR — Graphic Designer & Art Director"),
        "work": ("الأعمال — NOOR", "Selected Work — NOOR"),
        "about": ("من أنا — NOOR", "About — NOOR"),
        "services": ("الخدمات — NOOR", "Services — NOOR"),
        "contact": ("تواصل — NOOR", "Contact — NOOR"),
        "admin": ("إدارة الأعمال — NOOR", "Portfolio Management — NOOR"),
        "dashboard": ("لوحة التحكم — NOOR", "Studio Dashboard — NOOR"),
        "shop": ("المتجر — NOOR", "Shop — NOOR"),
        "settings": ("إعدادات الحساب — NOOR", "Account Settings — NOOR"),
    }
    title_ar, title_en = titles.get(
        context.get("page"), ("NOOR — معرض أعمال إبداعي", "NOOR — Creative Portfolio")
    )
    project = context.get("project")
    if project:
        title_ar = f"{project['title_ar']} — NOOR"
        title_en = f"{project['title_en']} — NOOR"
    context.setdefault("title_ar", title_ar)
    context.setdefault("title_en", title_en)
    return render_template(template, csrf_token=csrf_token, format_price=format_price, **context)


def format_price(price_cents, currency):
    whole, cents = divmod(int(price_cents), 100)
    value = f"{whole:,}.{cents:02d}"
    return f"{value} {currency}"


def flash_local(message_ar, message_en, category):
    flash({"ar": message_ar, "en": message_en}, category)


def safe_project_form():
    values = {field: request.form.get(field, "").strip() for field in PROJECT_FIELDS}
    for field, value in values.items():
        if not value or len(value) > (2000 if field.startswith("description") else 300):
            return values, (
                "أكمل جميع الحقول وتأكد من أن طولها مناسب.",
                "Complete every field and make sure its length is within the limit.",
            )
    if not SLUG_PATTERN.fullmatch(values["slug"]) or len(values["slug"]) > 80:
        return values, (
            "استخدم رابطاً إنجليزياً بسيطاً مثل: my-project.",
            "Use a simple English URL slug, such as my-project.",
        )
    try:
        image = urlsplit(values["image_url"])
        valid_image_url = (
            image.scheme == "https"
            and bool(image.hostname)
            and image.username is None
            and image.password is None
        )
        image.port
    except ValueError:
        valid_image_url = False
    if not valid_image_url:
        return values, (
            "رابط الصورة يجب أن يكون HTTPS صالحاً.",
            "The image URL must be a valid HTTPS URL.",
        )
    return values, None


def safe_product_form():
    values = {field: request.form.get(field, "").strip() for field in PRODUCT_FIELDS}
    text_limits = {
        "slug": 80,
        "sku": 60,
        "title_ar": 180,
        "title_en": 180,
        "category_ar": 120,
        "category_en": 120,
        "description_ar": 2000,
        "description_en": 2000,
        "image_url": 300,
    }
    for field, limit in text_limits.items():
        if len(values[field]) > limit:
            return values, (
                "تجاوز أحد الحقول الحد المسموح.",
                "One of the fields exceeds its maximum length.",
            )
    for field in ("title_ar", "title_en", "category_ar", "category_en",
                  "description_ar", "description_en", "image_url", "price",
                  "stock_quantity", "currency_code"):
        if not values[field]:
            return values, ("أكمل جميع الحقول المطلوبة.", "Complete all required fields.")
    if not SLUG_PATTERN.fullmatch(values["slug"]):
        return values, (
            "استخدم رابطاً إنجليزياً مثل: linen-notebook.",
            "Use a simple English URL slug, such as linen-notebook.",
        )
    if values["sku"] and not SKU_PATTERN.fullmatch(values["sku"]):
        return values, (
            "رمز المنتج يقبل الأحرف والأرقام والشرطات فقط.",
            "SKU may contain letters, numbers, dots, slashes, and hyphens.",
        )
    if values["currency_code"] not in CURRENCIES:
        return values, ("اختر عملة مدعومة.", "Choose a supported currency.")
    if values["is_published"] not in ("0", "1"):
        return values, ("اختر حالة نشر صحيحة.", "Choose a valid publication status.")
    try:
        image = urlsplit(values["image_url"])
        valid_image_url = (
            image.scheme == "https"
            and bool(image.hostname)
            and image.username is None
            and image.password is None
        )
        image.port
    except ValueError:
        valid_image_url = False
    if not valid_image_url:
        return values, ("أدخل رابط صورة HTTPS صالحاً.", "Enter a valid HTTPS image URL.")
    try:
        price = Decimal(values["price"]).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        if price <= 0 or price * 100 > MAX_PRICE_CENTS:
            raise InvalidOperation
        price_cents = int(price * 100)
        compare_value = None
        if values["compare_at_price"]:
            compare_price = Decimal(values["compare_at_price"]).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            if compare_price <= price or compare_price * 100 > MAX_PRICE_CENTS:
                raise InvalidOperation
            compare_value = int(compare_price * 100)
        stock = int(values["stock_quantity"])
        if stock < 0 or stock > MAX_STOCK:
            raise InvalidOperation
    except (InvalidOperation, ValueError):
        return values, (
            "تحقق من السعر والسعر السابق والكمية المتاحة.",
            "Check the price, previous price, and available inventory quantity.",
        )
    values["price_cents"] = price_cents
    values["compare_at_cents"] = compare_value
    values["stock_quantity"] = stock
    values["sku"] = values["sku"] or None
    values["is_published"] = int(values["is_published"] == "1")
    return values, None


@site.get("/")
def home():
    projects = get_db().execute(
        "SELECT * FROM projects ORDER BY id DESC LIMIT 3"
    ).fetchall()
    return render_page("home.html", projects=projects, page="home")


@site.get("/work")
def work():
    projects = get_db().execute("SELECT * FROM projects ORDER BY id DESC").fetchall()
    return render_page("work.html", projects=projects, page="work")


@site.get("/shop")
def shop():
    products = get_db().execute(
        "SELECT * FROM products WHERE is_published = 1 ORDER BY created_at DESC"
    ).fetchall()
    return render_page("shop.html", products=products, page="shop")


@site.get("/products/<slug>")
def product_detail(slug):
    product = get_db().execute(
        "SELECT * FROM products WHERE slug = ? AND is_published = 1", (slug,)
    ).fetchone()
    if product is None:
        abort(404)
    return render_page("product_detail.html", product=product, page="shop")


@site.get("/projects/<slug>")
def project_detail(slug):
    project = get_db().execute(
        "SELECT * FROM projects WHERE slug = ?", (slug,)
    ).fetchone()
    if project is None:
        abort(404)
    return render_page("project.html", project=project, page="work")


@site.get("/about")
def about():
    return render_page("about.html", page="about")


@site.get("/services")
def services():
    return render_page("services.html", page="services")


@site.get("/admin/settings")
@admin_required
def admin_settings():
    return render_page("admin_settings.html", page="settings")


@site.post("/admin/settings/password")
@admin_required
def admin_change_password():
    validate_csrf()
    current_password = request.form.get("current_password", "")[:1024]
    new_password = request.form.get("new_password", "")[:1024]
    confirmation = request.form.get("confirm_password", "")[:1024]
    database = get_db()
    admin = database.execute(
        "SELECT username, password_hash, password_salt FROM admin_users "
        "WHERE username = ? AND active = 1",
        (session["admin"],),
    ).fetchone()
    if admin is None:
        session.clear()
        return redirect(url_for("site.admin_login"))
    candidate = hash_password(current_password, admin["password_salt"])
    if not hmac.compare_digest(candidate, admin["password_hash"]):
        flash_local("كلمة المرور الحالية غير صحيحة.", "The current password is incorrect.", "error")
    elif len(new_password) < 14:
        flash_local(
            "يجب أن تتكون كلمة المرور الجديدة من 14 حرفاً على الأقل.",
            "The new password must be at least 14 characters long.",
            "error",
        )
    elif new_password != confirmation:
        flash_local("كلمتا المرور غير متطابقتين.", "The new passwords do not match.", "error")
    elif hmac.compare_digest(current_password, new_password):
        flash_local(
            "اختر كلمة مرور مختلفة عن الحالية.",
            "Choose a password different from your current one.",
            "error",
        )
    else:
        salt = secrets.token_bytes(16)
        password_hash = hash_password(new_password, salt)
        auth_token = secrets.token_urlsafe(32)
        database.execute(
            "UPDATE admin_users SET password_hash = ?, password_salt = ?, "
            "auth_token = ? WHERE username = ?",
            (password_hash, salt, auth_token, admin["username"]),
        )
        database.commit()
        username = admin["username"]
        session.clear()
        session["admin"] = username
        session["admin_token"] = auth_token
        session.permanent = True
        csrf_token()
        flash_local("تم تغيير كلمة المرور بنجاح.", "Your password was changed.", "success")
    return redirect(url_for("site.admin_settings"))


@site.get("/contact")
def contact():
    return render_page("contact.html", page="contact")


@site.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin"):
        return redirect(url_for("site.admin_dashboard"))
    if request.method == "POST":
        validate_csrf()
        database = get_db()
        key = ip_key()
        attempts = database.execute(
            "SELECT failures, locked_until FROM login_attempts WHERE ip_key = ?",
            (key,),
        ).fetchone()
        now = int(time.time())
        if attempts and attempts["locked_until"] > now:
            flash_local(
                "تعذر تسجيل الدخول. انتظر قليلاً ثم أعد المحاولة.",
                "Sign-in is temporarily unavailable. Please wait and try again.",
                "error",
            )
            return render_page("admin_login.html", page="admin")
        if attempts and attempts["locked_until"] > 0:
            attempts = None

        username = request.form.get("username", "").strip().lower()[:80]
        password = request.form.get("password", "")[:1024]
        user = database.execute(
            "SELECT username, password_hash, password_salt, auth_token FROM admin_users "
            "WHERE username = ? AND active = 1",
            (username,),
        ).fetchone()
        if user:
            candidate = hash_password(password, user["password_salt"])
            valid = hmac.compare_digest(candidate, user["password_hash"])
        else:
            # Keep the no-user path close to the cost of checking a real password.
            dummy_salt = current_app.config["DUMMY_PASSWORD_SALT"]
            hash_password(password, dummy_salt)
            valid = False

        if valid:
            auth_token = user["auth_token"] or secrets.token_urlsafe(32)
            if not user["auth_token"]:
                database.execute(
                    "UPDATE admin_users SET auth_token = ? WHERE username = ?",
                    (auth_token, user["username"]),
                )
                database.commit()
            session.clear()
            session["admin"] = user["username"]
            session["admin_token"] = auth_token
            session.permanent = True
            csrf_token()
            database.execute("DELETE FROM login_attempts WHERE ip_key = ?", (key,))
            database.commit()
            return redirect(url_for("site.admin_dashboard"))

        failures = (attempts["failures"] if attempts else 0) + 1
        locked_until = now + 900 if failures >= 5 else 0
        database.execute(
            """INSERT INTO login_attempts (ip_key, failures, locked_until)
               VALUES (?, ?, ?)
               ON CONFLICT(ip_key) DO UPDATE SET
               failures = excluded.failures, locked_until = excluded.locked_until""",
            (key, failures, locked_until),
        )
        database.commit()
        flash_local(
            "بيانات الدخول غير صحيحة أو تعذر تسجيل الدخول.",
            "The credentials are invalid or sign-in is unavailable.",
            "error",
        )
    return render_page("admin_login.html", page="admin")


@site.post("/admin/logout")
@admin_required
def admin_logout():
    validate_csrf()
    session.clear()
    return redirect(url_for("site.admin_login"))


@site.get("/admin")
@admin_required
def admin_dashboard():
    database = get_db()
    return render_page(
        "admin_dashboard.html",
        page="dashboard",
        product_count=database.execute(
            "SELECT COUNT(*) FROM products"
        ).fetchone()[0],
        published_count=database.execute(
            "SELECT COUNT(*) FROM products WHERE is_published = 1"
        ).fetchone()[0],
        low_stock_count=database.execute(
            "SELECT COUNT(*) FROM products WHERE is_published = 1 AND stock_quantity < 5"
        ).fetchone()[0],
        project_count=database.execute(
            "SELECT COUNT(*) FROM projects"
        ).fetchone()[0],
    )


@site.get("/admin/projects")
@admin_required
def admin_projects():
    projects = get_db().execute(
        "SELECT * FROM projects ORDER BY created_at DESC"
    ).fetchall()
    return render_page("admin_projects.html", projects=projects, page="portfolio-admin")


@site.get("/admin/products")
@admin_required
def admin_products():
    products = get_db().execute(
        "SELECT * FROM products ORDER BY created_at DESC, id DESC"
    ).fetchall()
    return render_page("admin_products.html", products=products, page="admin")


@site.route("/admin/products/new", methods=["GET", "POST"])
@admin_required
def admin_new_product():
    if request.method == "POST":
        validate_csrf()
        values, error = safe_product_form()
        if error:
            flash_local(error[0], error[1], "error")
            return render_page("admin_edit_product.html", product=values, mode="new", page="admin")
        try:
            get_db().execute(
                """INSERT INTO products (
                    slug, sku, title_ar, title_en, category_ar, category_en,
                    description_ar, description_en, image_url, price_cents,
                    compare_at_cents, stock_quantity, currency_code, is_published
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(values[field] for field in PRODUCT_FIELDS[:9])
                + (
                    values["price_cents"],
                    values["compare_at_cents"],
                    values["stock_quantity"],
                    values["currency_code"],
                    values["is_published"],
                ),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            flash_local(
                "رابط المنتج أو رمز SKU مستخدم مسبقاً.",
                "That product URL or SKU is already in use.",
                "error",
            )
            return render_page("admin_edit_product.html", product=values, mode="new", page="admin")
        flash_local("تمت إضافة المنتج.", "Product added.", "success")
        return redirect(url_for("site.admin_products"))
    return render_page("admin_edit_product.html", product={}, mode="new", page="admin")


@site.route("/admin/products/<int:product_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_product(product_id):
    database = get_db()
    existing = database.execute(
        "SELECT * FROM products WHERE id = ?", (product_id,)
    ).fetchone()
    if existing is None:
        abort(404)
    if request.method == "POST":
        validate_csrf()
        values, error = safe_product_form()
        if error:
            flash_local(error[0], error[1], "error")
            return render_page("admin_edit_product.html", product=values, mode="edit", page="admin")
        try:
            database.execute(
                """UPDATE products SET
                    slug = ?, sku = ?, title_ar = ?, title_en = ?,
                    category_ar = ?, category_en = ?, description_ar = ?,
                    description_en = ?, image_url = ?, price_cents = ?,
                    compare_at_cents = ?, stock_quantity = ?, currency_code = ?,
                    is_published = ?, updated_at = CURRENT_TIMESTAMP
                   WHERE id = ?""",
                tuple(values[field] for field in PRODUCT_FIELDS[:9])
                + (
                    values["price_cents"],
                    values["compare_at_cents"],
                    values["stock_quantity"],
                    values["currency_code"],
                    values["is_published"],
                    product_id,
                ),
            )
            database.commit()
        except sqlite3.IntegrityError:
            flash_local(
                "رابط المنتج أو رمز SKU مستخدم مسبقاً.",
                "That product URL or SKU is already in use.",
                "error",
            )
            return render_page("admin_edit_product.html", product=values, mode="edit", page="admin")
        flash_local("تم حفظ تعديلات المنتج.", "Product changes saved.", "success")
        return redirect(url_for("site.admin_products"))
    return render_page("admin_edit_product.html", product=existing, mode="edit", page="admin")


@site.post("/admin/products/<int:product_id>/delete")
@admin_required
def admin_delete_product(product_id):
    validate_csrf()
    database = get_db()
    cursor = database.execute("DELETE FROM products WHERE id = ?", (product_id,))
    database.commit()
    if cursor.rowcount == 0:
        abort(404)
    flash_local("تم حذف المنتج.", "Product deleted.", "success")
    return redirect(url_for("site.admin_products"))


@site.route("/admin/projects/new", methods=["GET", "POST"])
@admin_required
def admin_new_project():
    if request.method == "POST":
        validate_csrf()
        values, error = safe_project_form()
        if error:
            flash_local(error[0], error[1], "error")
            return render_page(
                "admin_edit_project.html", project=values, mode="new", page="admin"
            )
        try:
            get_db().execute(
                """INSERT INTO projects (
                    slug, title_ar, title_en, category_ar, category_en,
                    description_ar, description_en, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                tuple(values[field] for field in PROJECT_FIELDS),
            )
            get_db().commit()
        except sqlite3.IntegrityError:
            flash_local(
                "هذا الرابط مستخدم بالفعل. اختر رابطاً آخر.",
                "That URL is already in use. Choose another.",
                "error",
            )
            return render_page(
                "admin_edit_project.html", project=values, mode="new", page="admin"
            )
        flash_local("تمت إضافة المشروع.", "Project added.", "success")
        return redirect(url_for("site.admin_projects"))
    return render_page("admin_edit_project.html", project={}, mode="new", page="admin")


@site.route("/admin/projects/<int:project_id>/edit", methods=["GET", "POST"])
@admin_required
def admin_edit_project(project_id):
    database = get_db()
    existing = database.execute(
        "SELECT * FROM projects WHERE id = ?", (project_id,)
    ).fetchone()
    if existing is None:
        abort(404)
    if request.method == "POST":
        validate_csrf()
        values, error = safe_project_form()
        if error:
            flash_local(error[0], error[1], "error")
            return render_page(
                "admin_edit_project.html",
                project=values,
                mode="edit",
                page="admin",
            )
        try:
            database.execute(
                """UPDATE projects SET slug = ?, title_ar = ?, title_en = ?,
                   category_ar = ?, category_en = ?, description_ar = ?,
                   description_en = ?, image_url = ? WHERE id = ?""",
                tuple(values[field] for field in PROJECT_FIELDS) + (project_id,),
            )
            database.commit()
        except sqlite3.IntegrityError:
            flash_local(
                "هذا الرابط مستخدم بالفعل. اختر رابطاً آخر.",
                "That URL is already in use. Choose another.",
                "error",
            )
            return render_page(
                "admin_edit_project.html",
                project=values,
                mode="edit",
                page="admin",
            )
        flash_local("تم حفظ التعديلات.", "Changes saved.", "success")
        return redirect(url_for("site.admin_projects"))
    return render_page("admin_edit_project.html", project=existing, mode="edit", page="admin")


@site.post("/admin/projects/<int:project_id>/delete")
@admin_required
def admin_delete_project(project_id):
    validate_csrf()
    database = get_db()
    cursor = database.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    database.commit()
    if cursor.rowcount == 0:
        abort(404)
    flash_local("تم حذف المشروع.", "Project deleted.", "success")
    return redirect(url_for("site.admin_projects"))
