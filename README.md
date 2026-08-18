# Local Exam Grader

A focused, local web interface for grading the same questions across a folder of scanned PDF exams.

## Setup

```bash
cd frommin
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
Maximum points for 4.1: 4
Maximum points for 4.2: 6
```

The maximum is encoded in each score column (for example, `4.1_score_4`) and scores
outside the inclusive range are rejected. Then open <http://127.0.0.1:5000>.
Later runs infer the assigned questions and their maximum scores from the existing CSV header.

The app binds to localhost by default. Grades are written by atomically replacing the CSV after every successful save.


<p align="center">
  <img src="static/dune_favicon.png" alt="Logo" width="300">
</p>
