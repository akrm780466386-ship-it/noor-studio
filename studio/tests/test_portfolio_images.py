import os
import tempfile
import unittest
from pathlib import Path

from studio import create_app
from studio.database import PROJECT_IMAGE_URLS, get_db
from studio.routes import safe_project_form


class PortfolioImageReplacementTests(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.old_database_path = os.environ.get("DATABASE_PATH")
        os.environ["DATABASE_PATH"] = str(Path(self.temp_dir.name) / "portfolio.sqlite3")
        self.app = create_app()
        self.app.config.update(TESTING=True)
        self.client = self.app.test_client()

    def tearDown(self):
        if self.old_database_path is None:
            os.environ.pop("DATABASE_PATH", None)
        else:
            os.environ["DATABASE_PATH"] = self.old_database_path
        self.temp_dir.cleanup()

    def test_project_records_and_public_pages_use_local_images(self):
        filenames = (
            "design-01.jpg.jpeg",
            "design-02.jpg.jpeg",
            "design-03.jpg.jpeg",
        )
        with self.app.app_context():
            projects = [
                dict(project)
                for project in get_db().execute(
                    "SELECT * FROM projects ORDER BY id DESC"
                ).fetchall()
            ]
        expected_slugs = ["sunday-studio", "forma-objects", "serein-living"]
        self.assertEqual([project["slug"] for project in projects], expected_slugs)
        self.assertEqual(
            {project["slug"]: project["image_url"] for project in projects},
            PROJECT_IMAGE_URLS,
        )

        for filename in filenames:
            response = self.client.get(
                f"/static/images/portfolio/{filename}"
            )
            try:
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.mimetype, "image/jpeg")
            finally:
                response.close()

        for route in ("/", "/work"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertNotIn(b"images.unsplash.com", response.data)
            self.assertNotIn(b"/projects/learn-design", response.data)
            for index, filename in enumerate(filenames):
                self.assertIn(filenames[index].encode(), response.data)
                self.assertIn(
                    f'href="/projects/{expected_slugs[index]}"'.encode(),
                    response.data,
                )

        for index, slug in enumerate(expected_slugs):
            detail = self.client.get(f"/projects/{slug}")
            self.assertEqual(detail.status_code, 200)
            self.assertNotIn(b"images.unsplash.com", detail.data)
            self.assertIn(filenames[index].encode(), detail.data)
            for other_index, filename in enumerate(filenames):
                if other_index != index:
                    self.assertNotIn(filename.encode(), detail.data)

        with self.app.app_context():
            final_projects = [
                dict(project)
                for project in get_db().execute(
                    "SELECT * FROM projects ORDER BY id DESC"
                ).fetchall()
            ]
            self.assertEqual(final_projects, projects)

    def test_project_form_accepts_known_local_portfolio_paths(self):
        project = {
            "slug": "sunday-studio",
            "title_ar": "Sunday Studio",
            "title_en": "Sunday Studio",
            "category_ar": "حملة إبداعية",
            "category_en": "Creative campaign",
            "description_ar": "وصف",
            "description_en": "Description",
            "image_url": PROJECT_IMAGE_URLS["sunday-studio"],
        }
        with self.app.test_request_context(method="POST", data=project):
            _values, error = safe_project_form()
        self.assertIsNone(error)

        project["image_url"] = "/static/images/portfolio/../design-01.jpg.jpeg"
        with self.app.test_request_context(method="POST", data=project):
            _values, error = safe_project_form()
        self.assertIsNotNone(error)

    def test_contact_details_are_localized_and_link_to_official_destinations(self):
        for route in ("/", "/contact"):
            response = self.client.get(route)
            self.assertEqual(response.status_code, 200)
            self.assertIn(b"mailto:akrm780466386@gmail.com", response.data)
            self.assertIn(b"https://wa.me/967780466386", response.data)
            self.assertIn(b"akrm780466386@gmail.com", response.data)
            self.assertIn(b"+967 780 466 386", response.data)
            self.assertIn(
                'data-ar="البريد الإلكتروني" data-en="Email"'.encode(),
                response.data,
            )
            self.assertIn(
                'data-ar="واتساب" data-en="WhatsApp"'.encode(),
                response.data,
            )


if __name__ == "__main__":
    unittest.main()
