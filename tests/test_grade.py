import csv
import tempfile
import unittest
from pathlib import Path

import pymupdf

from grade import (
    ConfigurationError,
    ExamRepository,
    GradeStore,
    ValidationError,
    create_app,
    header_for_questions,
    infer_questions,
    parse_question_list,
)


def make_pdf(path: Path, pages: int = 2) -> None:
    document = pymupdf.open()
    for page_number in range(1, pages + 1):
        page = document.new_page()
        page.insert_text((72, 72), f"Page {page_number}")
    document.save(path)
    document.close()


class GradeStoreTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)

    def tearDown(self):
        self.tempdir.cleanup()

    def test_question_parsing_and_header(self):
        questions = parse_question_list(" 4.1, 4.2 ")
        self.assertEqual(questions, ["4.1", "4.2"])
        header = header_for_questions(questions)
        self.assertEqual(
            header,
            ["student_id", "4.1_score", "4.1_comment", "4.2_score", "4.2_comment"],
        )
        self.assertEqual(infer_questions(header), questions)

    def test_invalid_header_pair_is_rejected(self):
        with self.assertRaises(ConfigurationError):
            infer_questions(["student_id", "4.1_score"])

    def test_new_csv_has_header_only(self):
        csv_path = self.root / "grades.csv"
        GradeStore(csv_path, ["4.1", "4.2"])
        with csv_path.open(newline="", encoding="utf-8") as handle:
            rows = list(csv.reader(handle))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0], header_for_questions(["4.1", "4.2"]))

    def test_save_updates_without_duplicate_and_builds_pool(self):
        store = GradeStore(self.root / "grades.csv", ["4.1"])
        store.save("203", {"4.1_score": "4", "4.1_comment": "Fully correct"})
        store.save("204", {"4.1_score": "4", "4.1_comment": "Fully correct"})
        store.save("203", {"4.1_score": "3", "4.1_comment": "Minor error"})

        rows = store.read_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(store.rows_by_student()["203"]["4.1_score"], "3")
        pool = store.combinations()["4.1"]
        self.assertEqual({item["comment"] for item in pool}, {"Minor error", "Fully correct"})

    def test_submission_validation(self):
        store = GradeStore(self.root / "grades.csv", ["4.1"])
        for form in (
            {"4.1_score": "-1", "4.1_comment": "Comment"},
            {"4.1_score": "1.5", "4.1_comment": "Comment"},
            {"4.1_score": "2", "4.1_comment": "   "},
        ):
            with self.assertRaises(ValidationError):
                store.save("203", form)
        self.assertEqual(store.read_rows(), [])

    def test_zero_score_is_valid(self):
        store = GradeStore(self.root / "grades.csv", ["4.1"])
        store.save("203", {"4.1_score": "0", "4.1_comment": "Incorrect"})
        row = store.rows_by_student()["203"]
        self.assertEqual(row["4.1_score"], "0")
        self.assertEqual(row["4.1_comment"], "Incorrect")


class AppTests(unittest.TestCase):
    def setUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.root = Path(self.tempdir.name)
        self.pdfs = self.root / "pdfs"
        self.pdfs.mkdir()
        make_pdf(self.pdfs / "203.pdf")
        make_pdf(self.pdfs / "204.pdf")
        (self.pdfs / "notes.txt").write_text("ignored", encoding="utf-8")
        self.store = GradeStore(self.root / "grades.csv", ["4.1", "4.2"])
        app = create_app(ExamRepository(self.pdfs), self.store)
        app.config.update(TESTING=True, SECRET_KEY="test")
        self.client = app.test_client()

    def tearDown(self):
        self.tempdir.cleanup()

    def test_initial_exam_and_pdf_render(self):
        response = self.client.get("/", follow_redirects=True)
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"203", response.data)
        page = self.client.get("/exam/203/page/2.png?scale=1")
        self.assertEqual(page.status_code, 200)
        self.assertEqual(page.mimetype, "image/png")

    def test_invalid_save_stays_on_exam(self):
        response = self.client.post(
            "/exam/203",
            data={
                "4.1_score": "2",
                "4.1_comment": "Good",
                "4.2_score": "",
                "4.2_comment": "",
            },
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter zero or a positive whole number", response.data)
        self.assertEqual(self.store.read_rows(), [])

    def test_valid_save_advances_to_next_ungraded(self):
        response = self.client.post(
            "/exam/203",
            data={
                "4.1_score": "2",
                "4.1_comment": "Good",
                "4.2_score": "3",
                "4.2_comment": "Also good",
            },
            follow_redirects=False,
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/exam/204?saved=1", response.headers["Location"])
        self.assertIn("203", self.store.rows_by_student())


if __name__ == "__main__":
    unittest.main()
