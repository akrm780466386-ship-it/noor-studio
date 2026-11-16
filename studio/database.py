import os
import sqlite3
from pathlib import Path

from flask import current_app, g

try:
    import psycopg
    INTEGRITY_ERRORS = (sqlite3.IntegrityError, psycopg.IntegrityError)
except ImportError:
    psycopg = None
    INTEGRITY_ERRORS = (sqlite3.IntegrityError,)

PROJECT_IMAGE_URLS = {
    "sunday-studio": "/static/images/portfolio/design-01.jpg.jpeg",
    "forma-objects": "/static/images/portfolio/design-02.jpg.jpeg",
    "serein-living": "/static/images/portfolio/design-03.jpg.jpeg",
}

PROJECTS = (
    (
        "serein-living", "Serein Living", "Serein Living",
        "هوية بصرية · أسلوب حياة", "Visual identity · Lifestyle",
        "هوية هادئة لمساحة تحتفي بالتفاصيل اليومية.",
        "A calm identity for a space that celebrates everyday details.",
        PROJECT_IMAGE_URLS["serein-living"],
    ),
    (
        "forma-objects", "Forma Objects", "Forma Objects",
        "تغليف · فن وعطور", "Packaging · Art & fragrance",
        "نظام تغليف يلتقي فيه الفن المعاصر بعالم العطور.",
        "A packaging system where contemporary art meets fragrance.",
        PROJECT_IMAGE_URLS["forma-objects"],
    ),
    (
        "sunday-studio", "Sunday Studio", "Sunday Studio",
        "حملة إبداعية · ثقافة", "Creative campaign · Culture",
        "حملة مرحة تحتفي بالألوان والإبداع.",
        "A playful campaign celebrating color and creativity.",
        PROJECT_IMAGE_URLS["sunday-studio"],
    ),
)


class HybridRow:
    """A database row supporting both SQLite-style integer and named indexing."""

    def __init__(self, names, values):
        self._names = tuple(names)
        self._values = tuple(values)
        self._mapping = dict(zip(self._names, self._values))

    def __getitem__(self, key):
        if isinstance(key, str):
            return self._mapping[key]
        return self._values[key]

    def __iter__(self):
        return iter(self._values)

    def __len__(self):
        return len(self._values)

    def keys(self):
        return self._names


class HybridCursor:
    def __init__(self, cursor):
        self._cursor = cursor

    def _convert(self, row):
        if row is None:
            return None
        names = [
            column.name if hasattr(column, "name") else column[0]
            for column in self._cursor.description
        ]
        return HybridRow(names, row)

    def fetchone(self):
        return self._convert(self._cursor.fetchone())

    def fetchall(self):
        return [self._convert(row) for row in self._cursor.fetchall()]

    @property
    def rowcount(self):
        return self._cursor.rowcount


class PostgresConnection:
    """Small compatibility layer for the existing parameterized SQLite queries."""

    def __init__(self, connection):
        self._connection = connection

    def execute(self, query, parameters=()):
        cursor = self._connection.execute(query.replace("?", "%s"), parameters)
        return HybridCursor(cursor)

    def executemany(self, query, parameters):
        cursor = self._connection.cursor()
        cursor.executemany(query.replace("?", "%s"), parameters)
        return HybridCursor(cursor)

    def commit(self):
        self._connection.commit()

    def rollback(self):
        self._connection.rollback()

    def close(self):
        self._connection.close()


def get_db():
    if "db" not in g:
        database_url = current_app.config.get("DATABASE_URL")
        if database_url:
            if psycopg is None:
                raise RuntimeError("Install psycopg to use DATABASE_URL.")
            connection = psycopg.connect(
                database_url,
                connect_timeout=10,
                sslmode="require",
                prepare_threshold=None,
            )
            g.db = PostgresConnection(connection)
        else:
            g.db = sqlite3.connect(current_app.config["DATABASE"])
            g.db.row_factory = sqlite3.Row
            g.db.execute("PRAGMA foreign_keys = ON")
            g.db.execute("PRAGMA busy_timeout = 5000")
    return g.db


def close_db(_error=None):
    database = g.pop("db", None)
    if database is not None:
        database.close()


def _import_legacy_sqlite(database):
    marker = database.execute(
        "SELECT value FROM site_meta WHERE key = ?",
        ("legacy_sqlite_imported",),
    ).fetchone()
    if marker is not None:
        return

    legacy_path = Path(current_app.config["LEGACY_DATABASE_PATH"])
    if not legacy_path.is_file():
        current_app.logger.warning(
            "Legacy SQLite import skipped: database file was not found at %s.",
            legacy_path,
        )
        return

    allowed_tables = (
        "projects",
        "admin_users",
        "login_attempts",
        "site_meta",
        "products",
    )
    legacy = sqlite3.connect(f"file:{legacy_path}?mode=ro", uri=True)
    legacy.row_factory = sqlite3.Row
    try:
        integrity = legacy.execute("PRAGMA quick_check").fetchone()
        if integrity is None or integrity[0] != "ok":
            raise RuntimeError("The legacy SQLite database failed its integrity check.")

        existing_tables = {
            row[0]
            for row in legacy.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        required_tables = {"projects", "admin_users", "site_meta"}
        missing_tables = required_tables - existing_tables
        if missing_tables:
            raise RuntimeError(
                "The legacy SQLite database is missing required tables: "
                + ", ".join(sorted(missing_tables))
            )

        for table in allowed_tables:
            exists = legacy.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            if exists is None:
                continue
            legacy_columns = [
                row["name"] for row in legacy.execute(f"PRAGMA table_info({table})")
            ]
            destination_columns = {
                row[0]
                for row in database.execute(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'public' AND table_name = ?",
                    (table,),
                ).fetchall()
            }
            columns = [column for column in legacy_columns if column in destination_columns]
            if not columns:
                continue

            # Let PostgreSQL assign fresh identity values. The imported records
            # have no dependent foreign keys, and this avoids collisions with
            # rows seeded in the destination before the legacy file is found.
            if table in ("projects", "products") and "id" in columns:
                columns.remove("id")

            placeholders = ", ".join("?" for _ in columns)
            column_sql = ", ".join(columns)
            if table in ("projects", "products") and "slug" in columns:
                updates = [column for column in columns if column != "slug"]
                conflict_sql = (
                    "ON CONFLICT (slug) DO UPDATE SET "
                    + ", ".join(f"{column} = EXCLUDED.{column}" for column in updates)
                    if updates
                    else "ON CONFLICT (slug) DO NOTHING"
                )
            else:
                conflict_sql = "ON CONFLICT DO NOTHING"
            insert_sql = (
                f"INSERT INTO {table} ({column_sql}) VALUES ({placeholders}) "
                f"{conflict_sql}"
            )
            for row in legacy.execute(f"SELECT {column_sql} FROM {table}"):
                database.execute(insert_sql, tuple(row[column] for column in columns))

        database.execute(
            "INSERT INTO site_meta (key, value) VALUES (?, ?) ON CONFLICT DO NOTHING",
            ("legacy_sqlite_imported", "1"),
        )
        for table in ("projects", "products"):
            maximum = database.execute(
                f"SELECT MAX(id) FROM {table}"
            ).fetchone()[0]
            if maximum is not None:
                database.execute(
                    "SELECT setval(pg_get_serial_sequence(?, 'id'), ?, true)",
                    (f"public.{table}", maximum),
                )
        database.commit()
    except Exception:
        database.rollback()
        raise
    finally:
        legacy.close()


def _seed_postgres(database):
    seeded = database.execute(
        "SELECT value FROM site_meta WHERE key = ?",
        ("sample_projects_seeded",),
    ).fetchone()
    if seeded is None:
        count = database.execute("SELECT COUNT(*) FROM projects").fetchone()[0]
        if count == 0:
            database.executemany(
                """INSERT INTO projects (
                    slug, title_ar, title_en, category_ar, category_en,
                    description_ar, description_en, image_url
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (slug) DO NOTHING""",
                PROJECTS,
            )
        database.execute(
            "INSERT INTO site_meta (key, value) VALUES (?, ?) ON CONFLICT DO NOTHING",
            ("sample_projects_seeded", "1"),
        )
    database.commit()


def init_db():
    database = get_db()
    if current_app.config.get("DATABASE_URL"):
        _import_legacy_sqlite(database)
        _seed_postgres(database)
        return

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
    app.teardown_appcontext(close_db)
    if not app.config.get("DATABASE_URL"):
        database_path = Path(app.config["DATABASE"])
        database_path.parent.mkdir(parents=True, exist_ok=True)
    with app.app_context():
        init_db()
