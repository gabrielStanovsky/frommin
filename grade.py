#!/usr/bin/env python3
"""Local web application for grading the same questions across PDF exams."""

from __future__ import annotations

import argparse
import csv
import io
import os
import re
import sys
import tempfile
import threading
from collections import Counter
from pathlib import Path
from typing import Dict, Iterable, List, Mapping, Sequence, Tuple

import pymupdf
from flask import Flask, Response, abort, flash, redirect, render_template, request, url_for


QUESTION_COLUMN_RE = re.compile(r"^(?P<question>.+)_(?P<kind>score|comment)$")
MAX_RENDER_SCALE = 3.0
MIN_RENDER_SCALE = 0.75


class ConfigurationError(ValueError):
    """Raised when the exam folder or grades CSV has an invalid structure."""


class ValidationError(ValueError):
    """Raised when submitted grades do not satisfy the grading contract."""

    def __init__(self, errors: Mapping[str, str]):
        super().__init__("Invalid grade submission")
        self.errors = dict(errors)


def parse_question_list(raw: str) -> List[str]:
    """Parse and validate a terminal-entered comma-separated question list."""
    questions = [part.strip() for part in raw.split(",") if part.strip()]
    if not questions:
        raise ConfigurationError("At least one question ID is required.")
    if len(set(questions)) != len(questions):
        raise ConfigurationError("Question IDs must not be repeated.")
    for question in questions:
        if any(char in question for char in ("\r", "\n", ",")):
            raise ConfigurationError(f"Invalid question ID: {question!r}")
    return questions


def header_for_questions(questions: Sequence[str]) -> List[str]:
    header = ["student_id"]
    for question in questions:
        header.extend((f"{question}_score", f"{question}_comment"))
    return header


def infer_questions(header: Sequence[str]) -> List[str]:
    """Infer ordered question IDs and validate score/comment column pairs."""
    if not header or header[0] != "student_id":
        raise ConfigurationError("Grades CSV must start with a student_id column.")

    seen: Dict[str, set] = {}
    order: List[str] = []
    for column in header[1:]:
        match = QUESTION_COLUMN_RE.match(column)
        if not match:
            raise ConfigurationError(
                f"Unexpected CSV column {column!r}; expected <question>_score or <question>_comment."
            )
        question = match.group("question")
        kind = match.group("kind")
        if question not in seen:
            seen[question] = set()
            order.append(question)
        if kind in seen[question]:
            raise ConfigurationError(f"Duplicate column for {question}_{kind}.")
        seen[question].add(kind)

    if not order:
        raise ConfigurationError("Grades CSV does not contain any question columns.")
    for question in order:
        missing = {"score", "comment"} - seen[question]
        if missing:
            raise ConfigurationError(
                f"Question {question!r} is missing: "
                + ", ".join(f"{question}_{kind}" for kind in sorted(missing))
            )
    return order


class ExamRepository:
    """Deterministic collection of top-level PDF exams keyed by filename stem."""

    def __init__(self, folder: Path):
        self.folder = folder.expanduser().resolve()
        if not self.folder.is_dir():
            raise ConfigurationError(f"PDF folder does not exist: {self.folder}")

        exams: Dict[str, Path] = {}
        for path in sorted(self.folder.iterdir(), key=lambda item: item.name.casefold()):
            if not path.is_file() or path.suffix.lower() != ".pdf":
                continue
            student_id = path.stem
            if student_id in exams:
                raise ConfigurationError(f"Duplicate student ID from PDF filenames: {student_id}")
            exams[student_id] = path.resolve()

        if not exams:
            raise ConfigurationError(f"No PDF files found in: {self.folder}")
        self._exams = exams
        self.student_ids = sorted(exams, key=lambda value: value.casefold())

    def path_for(self, student_id: str) -> Path:
        try:
            return self._exams[student_id]
        except KeyError:
            raise KeyError(f"Unknown student ID: {student_id}") from None

    def page_count(self, student_id: str) -> int:
        with pymupdf.open(self.path_for(student_id)) as document:
            return document.page_count

    def render_page(self, student_id: str, page_number: int, scale: float) -> bytes:
        path = self.path_for(student_id)
        with pymupdf.open(path) as document:
            if page_number < 1 or page_number > document.page_count:
                raise IndexError(page_number)
            page = document.load_page(page_number - 1)
            pixmap = page.get_pixmap(matrix=pymupdf.Matrix(scale, scale), alpha=False)
            return pixmap.tobytes("png")


class GradeStore:
    """CSV-backed grades with validation and atomic replacement writes."""

    def __init__(self, path: Path, questions: Sequence[str] | None = None):
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()

        if self.path.exists():
            header, _ = self._read_unlocked()
            self.questions = infer_questions(header)
        else:
            if not questions:
                raise ConfigurationError("Questions are required when creating a grades CSV.")
            self.questions = list(questions)
            self._atomic_write([], header_for_questions(self.questions))

        self.header = header_for_questions(self.questions)

    def _read_unlocked(self) -> Tuple[List[str], List[Dict[str, str]]]:
        try:
            with self.path.open("r", encoding="utf-8-sig", newline="") as handle:
                reader = csv.DictReader(handle)
                if reader.fieldnames is None:
                    raise ConfigurationError(f"Grades CSV is empty: {self.path}")
                rows = []
                seen = set()
                for row_number, row in enumerate(reader, start=2):
                    student_id = (row.get("student_id") or "").strip()
                    if not student_id:
                        raise ConfigurationError(f"Missing student_id on CSV row {row_number}.")
                    if student_id in seen:
                        raise ConfigurationError(f"Duplicate student_id in grades CSV: {student_id}")
                    seen.add(student_id)
                    normalized = {key: (value or "") for key, value in row.items() if key is not None}
                    normalized["student_id"] = student_id
                    rows.append(normalized)
                return list(reader.fieldnames), rows
        except UnicodeDecodeError as exc:
            raise ConfigurationError(f"Grades CSV is not valid UTF-8: {self.path}") from exc

    def read_rows(self) -> List[Dict[str, str]]:
        with self._lock:
            header, rows = self._read_unlocked()
            questions = infer_questions(header)
            if questions != self.questions or list(header) != self.header:
                raise ConfigurationError("Grades CSV header changed while the app was running.")
            return rows

    def rows_by_student(self) -> Dict[str, Dict[str, str]]:
        return {row["student_id"]: row for row in self.read_rows()}

    def combinations(self) -> Dict[str, List[Dict[str, object]]]:
        rows = self.read_rows()
        result: Dict[str, List[Dict[str, object]]] = {}
        for question in self.questions:
            counts: Counter = Counter()
            for row in rows:
                score = row.get(f"{question}_score", "").strip()
                comment = row.get(f"{question}_comment", "").strip()
                if score and comment:
                    counts[(score, comment)] += 1
            ordered = sorted(
                counts.items(),
                key=lambda item: (-item[1], _numeric_sort_key(item[0][0]), item[0][1].casefold()),
            )
            result[question] = [
                {"score": score, "comment": comment, "count": count}
                for (score, comment), count in ordered
            ]
        return result

    def validate_submission(self, form: Mapping[str, str]) -> Dict[str, str]:
        errors: Dict[str, str] = {}
        cleaned: Dict[str, str] = {}
        for question in self.questions:
            score_key = f"{question}_score"
            comment_key = f"{question}_comment"
            score_raw = (form.get(score_key) or "").strip()
            comment = (form.get(comment_key) or "").strip()
            try:
                score = int(score_raw)
                if score < 0 or str(score) != score_raw:
                    raise ValueError
            except ValueError:
                errors[score_key] = "Enter zero or a positive whole number."
            else:
                cleaned[score_key] = str(score)

            if not comment:
                errors[comment_key] = "Enter a comment."
            else:
                cleaned[comment_key] = comment

        if errors:
            raise ValidationError(errors)
        return cleaned

    def save(self, student_id: str, form: Mapping[str, str]) -> Dict[str, str]:
        cleaned = self.validate_submission(form)
        with self._lock:
            header, rows = self._read_unlocked()
            if list(header) != self.header:
                raise ConfigurationError("Grades CSV header changed while the app was running.")

            new_row = {column: "" for column in self.header}
            new_row["student_id"] = student_id
            new_row.update(cleaned)

            replaced = False
            for index, row in enumerate(rows):
                if row["student_id"] == student_id:
                    rows[index] = new_row
                    replaced = True
                    break
            if not replaced:
                rows.append(new_row)
            self._atomic_write(rows, self.header)
        return new_row

    def _atomic_write(self, rows: Iterable[Mapping[str, str]], header: Sequence[str]) -> None:
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                "w",
                encoding="utf-8",
                newline="",
                dir=self.path.parent,
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                delete=False,
            ) as handle:
                temporary_path = Path(handle.name)
                writer = csv.DictWriter(handle, fieldnames=list(header), extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self.path)
        except Exception:
            if temporary_path is not None:
                try:
                    temporary_path.unlink(missing_ok=True)
                except OSError:
                    pass
            raise


def _numeric_sort_key(value: str) -> Tuple[int, str]:
    try:
        return int(value), ""
    except ValueError:
        return sys.maxsize, value.casefold()


def _next_target(student_ids: Sequence[str], current: str, graded: set) -> str:
    current_index = student_ids.index(current)
    remaining = [student_id for student_id in student_ids if student_id not in graded]
    if remaining:
        after = [student_id for student_id in remaining if student_ids.index(student_id) > current_index]
        return after[0] if after else remaining[0]
    return student_ids[(current_index + 1) % len(student_ids)]


def create_app(exams: ExamRepository, grades: GradeStore) -> Flask:
    app = Flask(__name__)
    app.config.update(SECRET_KEY=os.urandom(24), EXAMS=exams, GRADES=grades)

    @app.get("/")
    def index():
        rows = grades.rows_by_student()
        initial = next(
            (student_id for student_id in exams.student_ids if student_id not in rows),
            exams.student_ids[0],
        )
        return redirect(url_for("exam", student_id=initial))

    @app.route("/exam/<student_id>", methods=["GET", "POST"])
    def exam(student_id: str):
        if student_id not in exams.student_ids:
            abort(404)

        submitted = None
        errors: Dict[str, str] = {}
        if request.method == "POST":
            submitted = request.form.to_dict()
            try:
                grades.save(student_id, request.form)
            except ValidationError as exc:
                errors = exc.errors
            except OSError as exc:
                app.logger.exception("Could not save grades")
                flash(f"Could not save grades: {exc}", "error")
            else:
                rows_after_save = grades.rows_by_student()
                target = _next_target(exams.student_ids, student_id, set(rows_after_save))
                return redirect(url_for("exam", student_id=target, saved=1))

        rows = grades.rows_by_student()
        graded = set(rows).intersection(exams.student_ids)
        current_index = exams.student_ids.index(student_id)
        previous_id = exams.student_ids[(current_index - 1) % len(exams.student_ids)]
        existing = rows.get(student_id, {})
        values = {}
        for question in grades.questions:
            for kind in ("score", "comment"):
                key = f"{question}_{kind}"
                values[key] = (
                    (submitted.get(key) or "") if submitted is not None else existing.get(key, "")
                )

        if request.args.get("saved") == "1":
            flash("Saved", "success")

        return render_template(
            "grader.html",
            student_id=student_id,
            questions=grades.questions,
            values=values,
            errors=errors,
            combinations=grades.combinations(),
            page_count=exams.page_count(student_id),
            position=current_index + 1,
            total=len(exams.student_ids),
            graded_count=len(graded),
            remaining_count=len(exams.student_ids) - len(graded),
            is_graded=student_id in graded,
            all_complete=len(graded) == len(exams.student_ids),
            previous_id=previous_id,
        )

    @app.get("/exam/<student_id>/page/<int:page_number>.png")
    def exam_page(student_id: str, page_number: int):
        if student_id not in exams.student_ids:
            abort(404)
        try:
            scale = float(request.args.get("scale", "1.5"))
        except ValueError:
            abort(400)
        if scale < MIN_RENDER_SCALE or scale > MAX_RENDER_SCALE:
            abort(400)
        try:
            image = exams.render_page(student_id, page_number, scale)
        except IndexError:
            abort(404)
        return Response(
            image,
            mimetype="image/png",
            headers={"Cache-Control": "private, max-age=3600"},
        )

    return app


def initialize_store(csv_path: Path) -> GradeStore:
    if csv_path.expanduser().exists():
        return GradeStore(csv_path)

    while True:
        try:
            questions = parse_question_list(input("Questions to grade (comma separated): "))
            return GradeStore(csv_path, questions)
        except ConfigurationError as exc:
            print(f"Error: {exc}", file=sys.stderr)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the local PDF exam grading tool.")
    parser.add_argument("pdf_folder", type=Path, help="Folder containing student-ID PDF files")
    parser.add_argument("grades_csv", type=Path, help="CSV file used to store grades")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", default=5000, type=int, help="Port to bind (default: 5000)")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        exams = ExamRepository(args.pdf_folder)
        grades = initialize_store(args.grades_csv)
    except ConfigurationError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    app = create_app(exams, grades)
    print(f"Loaded {len(exams.student_ids)} exams; grading: {', '.join(grades.questions)}")
    print(f"Grades CSV: {grades.path}")
    app.run(host=args.host, port=args.port, debug=False, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
