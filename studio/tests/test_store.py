import os
import re
import tempfile
import unittest
from pathlib import Path

from studio import create_app
from studio.database import get_db
from studio.security import hash_password


class StoreAdminTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_database_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(Path(self.temp_dir.name) / "test.sqlite3")
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()
        self.password = "Test-Only-Original-Passphrase-2030!"
        self._create_admin()
        self._login(self.client, "store-owner", self.password)

    def tearDown(self):
        if self.old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self.old_database_path
        self.temp_dir.cleanup()

    def _create_admin(self):
        salt = b"noor-store-test!"
        with self.app.app_context():
            get_db().execute(
                """INSERT INTO admin_users (
                    username, password_hash, password_salt
                ) VALUES (?, ?, ?)""",
                ("store-owner", hash_password(self.password, salt), salt),
            )
            get_db().commit()

    def _csrf(self, client):
        response = client.get("/admin/products")
        self.assertEqual(response.status_code, 200)
        return re.search(
            rb'name="_csrf" value="([^"]+)"', response.data
        ).group(1).decode()

    def _login(self, client, username, password):
        response = client.get("/admin/login")
        self.assertEqual(response.status_code, 200)
        csrf = re.search(rb'name="_csrf" value="([^"]+)"', response.data).group(1).decode()
        return client.post(
            "/admin/login",
            data={"_csrf": csrf, "username": username, "password": password},
        )

    def _product_form(self, csrf, **overrides):
        values = {
            "_csrf": csrf,
            "slug": "linen-notebook",
            "sku": "NOOR-001",
            "title_ar": "دفتر الكتان",
            "title_en": "Linen Notebook",
            "category_ar": "قرطاسية",
            "category_en": "Stationery",
            "description_ar": "دفتر مصنوع بعناية.",
            "description_en": "A carefully crafted notebook.",
            "image_url": "https://images.unsplash.com/example",
            "price": "24.95",
            "compare_at_price": "29.95",
            "stock_quantity": "8",
            "currency_code": "USD",
            "is_published": "1",
        }
        values.update(overrides)
        return values

    def test_public_shop_product_crud_and_visibility(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Dashboard", response.data)
        self.assertIn(b"href=\"/shop\"", response.data)
        self.assertEqual(self.client.get("/shop").status_code, 200)
        admin_home = self.client.get("/admin")
        self.assertEqual(admin_home.status_code, 200)
        self.assertIn(b"Manage products", admin_home.data)
        self.assertIn(b"Account and password", admin_home.data)
        self.assertEqual(self.client.get("/admin/projects").status_code, 200)
        self.assertEqual(self.client.get("/admin/products/new").status_code, 200)
        self.assertEqual(self.client.get("/admin/settings").status_code, 200)

        csrf = self._csrf(self.client)
        response = self.client.post(
            "/admin/products/new", data=self._product_form(csrf)
        )
        self.assertEqual(response.status_code, 302)
        product = self.client.get("/products/linen-notebook")
        self.assertEqual(product.status_code, 200)
        self.assertIn(b"24.95 USD", product.data)
        self.assertIn(b"8 available", product.data)

        with self.app.app_context():
            product_id = get_db().execute(
                "SELECT id FROM products WHERE slug = ?", ("linen-notebook",)
            ).fetchone()["id"]

        edit_form = self.client.get(f"/admin/products/{product_id}/edit")
        self.assertEqual(edit_form.status_code, 200)
        self.assertIn(b'value="24.95"', edit_form.data)

        csrf = self._csrf(self.client)
        response = self.client.post(
            f"/admin/products/{product_id}/edit",
            data=self._product_form(
                csrf,
                title_ar="دفتر محدث",
                price="19.50",
                stock_quantity="0",
                is_published="0",
            ),
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/products/linen-notebook").status_code, 404)
        dashboard = self.client.get("/admin/products")
        self.assertIn("دفتر محدث".encode(), dashboard.data)
        self.assertIn(b"19.50 USD", dashboard.data)
        self.assertIn(b"Draft", dashboard.data)
        self.assertNotIn("دفتر محدث".encode(), self.client.get("/shop").data)

        csrf = self._csrf(self.client)
        response = self.client.post(
            f"/admin/products/{product_id}/delete", data={"_csrf": csrf}
        )
        self.assertEqual(response.status_code, 302)
        self.assertNotIn("دفتر محدث".encode(), self.client.get("/admin/products").data)

    def test_product_validation_and_password_change(self):
        stale_client = self.app.test_client()
        self.assertEqual(
            self._login(stale_client, "store-owner", self.password).status_code, 302
        )
        csrf = self._csrf(self.client)
        invalid = self.client.post(
            "/admin/products/new",
            data=self._product_form(csrf, price="0", compare_at_price=""),
        )
        self.assertEqual(invalid.status_code, 200)
        self.assertIn(b"Check the price", invalid.data)
        self.assertEqual(self.client.get("/shop").status_code, 200)

        csrf = self._csrf(self.client)
        response = self.client.post(
            "/admin/settings/password",
            data={
                "_csrf": csrf,
                "current_password": self.password,
                "new_password": "Test-Only-New-Store-Passphrase-2040!",
                "confirm_password": "Test-Only-New-Store-Passphrase-2040!",
            },
        )
        self.assertEqual(response.status_code, 302)
        self.assertEqual(self.client.get("/admin/settings").status_code, 200)
        self.assertEqual(stale_client.get("/admin").status_code, 302)

        old_client = self.app.test_client()
        failed_login = self._login(old_client, "store-owner", self.password)
        self.assertEqual(failed_login.status_code, 200)
        self.assertIn(b"The credentials are invalid", failed_login.data)
        new_client = self.app.test_client()
        successful_login = self._login(
            new_client, "store-owner", "Test-Only-New-Store-Passphrase-2040!"
        )
        self.assertEqual(successful_login.status_code, 302)


if __name__ == "__main__":
    unittest.main()
