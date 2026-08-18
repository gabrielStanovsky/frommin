# Local Exam Grader

A focused, local web interface for grading the same questions across a folder of scanned PDF exams.

## Setup

```bash
cd grader
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

## Run

```bash
.venv/bin/python grade.py \
  ../data/2026b/all \
  ../data/2026b/grades.csv
```

On the first run, enter the assigned questions in the terminal, for example:

```text
Questions to grade (comma separated): 4.1,4.2
```

Then open <http://127.0.0.1:5000>. Later runs infer the assigned questions from the existing CSV header.

The app binds to localhost by default. Grades are written by atomically replacing the CSV after every successful save.
