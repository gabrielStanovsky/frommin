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

## Grade closed questions

Grade parsed closed-question answers using literal matches against a reference CSV:

```bash
.venv/bin/python grade_closed_questions.py \
  data/2026b/all_exam_answers_carefully_rechecked.csv \
  data/2026b/correct_answers_with_scores_and_comments.csv \
  data/2026b/closed_question_grades.csv
```

Each reference row contains repeated `answer,score,comment` triplets. An exact match
receives that answer's score and comment; a blank reference comment defaults to
`תשובה נכונה`. Every unlisted answer receives zero and `תשובה לא נכונה`. The
highest listed score becomes the maximum encoded in a header such as `1.1_score_2`,
so the output is compatible with the manual grader's CSV schema.

## Merge all grades

Merge every grade CSV in a folder into one file, with questions in natural numeric
order:

```bash
.venv/bin/python merge_grades.py all_grades data/2026b/all_grades.csv
```

The script validates score ranges and reports every student with a missing score or
comment. It still writes the merged file with blanks for missing values and exits
with status 2 when missing grades are found. Schema or score errors exit with status
1. If the output file is inside the input folder, it is excluded from the inputs.

## Create a JSON breakdown CSV

Convert the final merged CSV into two columns: `student_id` and a `scores` JSON
dictionary:

```bash
.venv/bin/python grades_to_breakdown.py all_grades.csv breakdown_grades.csv
```

The output format is equivalent to:

```csv
student_id,scores
203605985,"{""1.1"":[2,""תשובה נכונה""]}"
```

Each JSON key is a question identifier. Its value is a two-element array containing
the numeric grade and explanation; JSON arrays represent the requested tuples.
Questions and students are naturally sorted. Missing comments, missing scores, and
scores outside the encoded maximum are rejected rather than silently omitted.

## Join two final-grade files

Create a three-column CSV for students who took both exams:

```bash
.venv/bin/python join_final_grades.py \
  ~/Downloads/final_2026a.csv \
  ~/Downloads/final_2026b_23_8.csv \
  joined_final_grades.csv
```

The first column is `student_id`. Each grade column is named after its input
filename without `.csv`, and only student IDs present in both inputs are included.
Both `final_grade` and `final grade` are accepted as the source grade header.

## Verify student email coverage

Check that every complete PDF filename, excluding only its final `.pdf` suffix, has
an exact ID match and a non-empty email:

```bash
.venv/bin/python verify_student_emails.py \
  data/2026b/all \
  ~/Downloads/student_id_to_email.csv
```

No trimming, case folding, or other ID normalization is performed. Missing IDs and
blank emails are listed, and the script exits with status 2 when either is found.
Every successful match is printed as `student_id,email`.


<p align="center">
  <img src="static/dune_favicon.png" alt="Logo" width="300">
</p>
