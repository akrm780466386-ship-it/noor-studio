import sqlite3
from pathlib import Path

from flask import current_app, g

PROJECTS = (
    (
        "serein-living",
        "Serein Living",
        "Serein Living",
        "هوية بصرية · أسلوب حياة",
        "Visual identity · Lifestyle",
        "هوية هادئة لمساحة تحتفي بالتفاصيل اليومية.",
        "A calm identity for a space that celebrates everyday details.",
        "https://images.unsplash.com/photo-1600210492486-724fe5c67fb0?auto=format&fit=crop&w=1200&q=85",
    ),
    (
        "forma-objects",
        "Forma Objects",
        "Forma Objects",
        "تغليف · فن وعطور",
        "Packaging · Art & fragrance",
        "نظام تغليف يلتقي فيه الفن المعاصر بعالم العطور.",
        "A packaging system where contemporary art meets fragrance.",
        "https://images.unsplash.com/photo-1547887538-e3a2f32cb1cc?auto=format&fit=crop&w=1200&q=85",
    ),
    (
        "sunday-studio",
        "Sunday Studio",
        "Sunday Studio",
        "حملة إبداعية · ثقافة",
        "Creative campaign · Culture",
        "حملة مرحة تحتفي بالألوان والإبداع.",
        "A playful campaign celebrating color and creativity.",
        "https://images.unsplash.com/photo-1549490349-8643362247b5?auto=format&fit=crop&w=1200&q=85",
    ),
)


def get_db():
    if "db" not in g:
        g.db = sqlite3.connect(current_app.config["DATABASE"])
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
        g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def init_db():
    database = get_db()
    database.executescript(
        """
        CREATE TABLE IF NOT EXISTS projects (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            title_ar TEXT NOT NULL,
            title_en TEXT NOT NULL,
            category_ar TEXT NOT NULL,
            category_en TEXT NOT NULL,
            description_ar TEXT NOT NULL,
            description_en TEXT NOT NULL,
            image_url TEXT NOT NULL,
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS admin_users (
            username TEXT PRIMARY KEY,
            password_hash BLOB NOT NULL,
            password_salt BLOB NOT NULL,
            active INTEGER NOT NULL DEFAULT 1,
            auth_token TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE IF NOT EXISTS login_attempts (
            ip_key TEXT PRIMARY KEY,
            failures INTEGER NOT NULL DEFAULT 0,
            locked_until INTEGER NOT NULL DEFAULT 0
        );
        CREATE TABLE IF NOT EXISTS site_meta (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS products (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL UNIQUE,
            sku TEXT UNIQUE,
            title_ar TEXT NOT NULL,
            title_en TEXT NOT NULL,
            category_ar TEXT NOT NULL,
            category_en TEXT NOT NULL,
            description_ar TEXT NOT NULL,
            description_en TEXT NOT NULL,
            image_url TEXT NOT NULL,
            price_cents INTEGER NOT NULL CHECK (price_cents > 0),
            compare_at_cents INTEGER CHECK (compare_at_cents IS NULL OR compare_at_cents > price_cents),
            stock_quantity INTEGER NOT NULL DEFAULT 0 CHECK (stock_quantity >= 0),
            currency_code TEXT NOT NULL DEFAULT 'USD',
            is_published INTEGER NOT NULL DEFAULT 1 CHECK (is_published IN (0, 1)),
            created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
            updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
        );
        """
    )
    product_columns = {
        row["name"] for row in database.execute("PRAGMA table_info(products)")
    }
    if "currency_code" not in product_columns:
        database.execute(
            "ALTER TABLE products ADD COLUMN currency_code TEXT NOT NULL DEFAULT 'USD'"
        )
    admin_columns = {
        row["name"] for row in database.execute("PRAGMA table_info(admin_users)")
    }
    if "auth_token" not in admin_columns:
        database.execute(
            "ALTER TABLE admin_users ADD COLUMN auth_token TEXT NOT NULL DEFAULT ''"
        )
    seeded = database.execute(
        "SELECT value FROM site_meta WHERE key = 'sample_projects_seeded'"
    ).fetchone()
    if seeded is None:
        if database.execute("SELECT COUNT(*) FROM projects").fetchone()[0] == 0:
            database.executemany(
                """INSERT INTO projects (
                    slug, title_ar, title_en, category_ar, category_en,
                    description_ar, description_en, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                PROJECTS,
            )
        database.execute(
            "INSERT INTO site_meta (key, value) VALUES ('sample_projects_seeded', '1')"
        )
    database.commit()


def init_app(app):
    database_path = Path(app.config["DATABASE"])
    database_path.parent.mkdir(parents=True, exist_ok=True)
    app.teardown_appcontext(close_db)
    with app.app_context():
        init_db()
