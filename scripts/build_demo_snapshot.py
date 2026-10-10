"""Build the public, reproducible Demo database snapshot.

This script is intentionally explicit about the rows that are published.  It
keeps one prepared course and its complete learning graph/question set, removes
unrelated users and courses, invalidates old browser sessions, and assigns a
public-only Demo password.

Usage from the repository root:

    python scripts/build_demo_snapshot.py --source D:/path/to/aiexamcoach.db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import secrets
from pathlib import Path


DEMO_COURSE_ID = "2fac5adf-a99b-47f1-838d-08563331a5f1"
DEMO_USERNAME = "demo"
DEMO_PASSWORD = "demo1234"
PBKDF2_ITERATIONS = 310_000


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS)
    return f"pbkdf2_sha256${PBKDF2_ITERATIONS}${salt.hex()}${digest.hex()}"


def ids(connection: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> set[str]:
    return {str(row[0]) for row in connection.execute(sql, params)}


def placeholders(values: set[str]) -> str:
    return ",".join("?" for _ in values) or "NULL"


def delete_not_in(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    keep: set[str],
) -> None:
    if keep:
        marks = placeholders(keep)
        connection.execute(f"DELETE FROM {table} WHERE {column} NOT IN ({marks})", tuple(keep))
    else:
        connection.execute(f"DELETE FROM {table}")


def build(source: Path, output: Path) -> None:
    if not source.is_file():
        raise FileNotFoundError(f"Source database does not exist: {source}")
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        output.unlink()
    shutil.copy2(source, output)

    connection = sqlite3.connect(output)
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        row = connection.execute(
            "SELECT user_id FROM courses WHERE id = ?", (DEMO_COURSE_ID,)
        ).fetchone()
        if row is None:
            raise RuntimeError(f"Prepared Demo course not found: {DEMO_COURSE_ID}")
        demo_user_id = str(row[0])

        material_ids = ids(
            connection, "SELECT id FROM materials WHERE course_id = ?", (DEMO_COURSE_ID,)
        )
        study_unit_ids = ids(
            connection, "SELECT id FROM study_units WHERE course_id = ?", (DEMO_COURSE_ID,)
        )
        question_ids = ids(
            connection, "SELECT id FROM questions WHERE course_id = ?", (DEMO_COURSE_ID,)
        )
        evidence_ids = ids(
            connection,
            "SELECT id FROM evidences WHERE material_id IN "
            f"({placeholders(material_ids)})",
            tuple(material_ids),
        )

        # Delete child rows first. Foreign keys are disabled only while pruning;
        # the integrity check below is run before the snapshot is published.
        if question_ids:
            delete_not_in(connection, "pilot_question_enrichments", "question_id", question_ids)
            delete_not_in(connection, "exam_evidences", "question_id", question_ids)
            delete_not_in(connection, "question_study_units", "question_id", question_ids)
        else:
            for table in ("pilot_question_enrichments", "exam_evidences", "question_study_units"):
                connection.execute(f"DELETE FROM {table}")
        if study_unit_ids:
            delete_not_in(connection, "pilot_knowledge_points", "study_unit_id", study_unit_ids)
            if evidence_ids:
                connection.execute(
                    "DELETE FROM study_unit_evidences "
                    f"WHERE study_unit_id NOT IN ({placeholders(study_unit_ids)}) "
                    f"OR evidence_id NOT IN ({placeholders(evidence_ids)})",
                    tuple(study_unit_ids) + tuple(evidence_ids),
                )
            else:
                connection.execute("DELETE FROM study_unit_evidences")
        else:
            connection.execute("DELETE FROM pilot_knowledge_points")
            connection.execute("DELETE FROM study_unit_evidences")
        if question_ids and study_unit_ids:
            connection.execute(
                "DELETE FROM question_study_units "
                f"WHERE question_id NOT IN ({placeholders(question_ids)}) "
                f"OR study_unit_id NOT IN ({placeholders(study_unit_ids)})",
                tuple(question_ids) + tuple(study_unit_ids),
            )
        else:
            connection.execute("DELETE FROM question_study_units")
        # Publish the prepared course but start every public run with a clean
        # student state, so all questions are available to the reviewer.
        connection.execute("DELETE FROM practice_records")
        delete_not_in(connection, "evidences", "id", evidence_ids)
        connection.execute("DELETE FROM learning_records")
        connection.execute("DELETE FROM recommendations")
        connection.execute("DELETE FROM events")
        delete_not_in(connection, "user_preferences", "course_id", {DEMO_COURSE_ID})
        connection.execute("DELETE FROM learning_sessions")
        delete_not_in(connection, "materials", "id", material_ids)
        # The frozen Demo consumes persisted extracted_text. Do not publish
        # workstation-specific source paths from the original database.
        connection.execute("UPDATE materials SET file_path = NULL")
        delete_not_in(connection, "study_units", "id", study_unit_ids)
        delete_not_in(connection, "questions", "id", question_ids)
        delete_not_in(connection, "knowledge_domains", "course_id", {DEMO_COURSE_ID})
        connection.execute(
            "UPDATE study_units SET mastery_status = 'UNKNOWN', "
            "coverage_status = 'NOT_STARTED', progress = 0 WHERE course_id = ?",
            (DEMO_COURSE_ID,),
        )
        connection.execute("UPDATE courses SET status = 'READY' WHERE id = ?", (DEMO_COURSE_ID,))
        delete_not_in(connection, "courses", "id", {DEMO_COURSE_ID})
        delete_not_in(connection, "auth_accounts", "user_id", {demo_user_id})
        connection.execute("DELETE FROM auth_sessions")
        delete_not_in(connection, "users", "id", {demo_user_id})

        account = connection.execute(
            "SELECT id FROM auth_accounts WHERE user_id = ?", (demo_user_id,)
        ).fetchone()
        if account is None:
            raise RuntimeError("The prepared Demo user has no auth account")
        connection.execute(
            "UPDATE auth_accounts SET username = ?, password_hash = ? WHERE user_id = ?",
            (DEMO_USERNAME, hash_password(DEMO_PASSWORD), demo_user_id),
        )

        connection.commit()
        connection.execute("VACUUM")
        violations = connection.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Foreign-key violations in Demo snapshot: {violations[:3]}")
    finally:
        connection.close()

    check = sqlite3.connect(f"file:{output}?mode=ro", uri=True)
    try:
        course_count = check.execute("SELECT COUNT(*) FROM courses").fetchone()[0]
        material_count = check.execute("SELECT COUNT(*) FROM materials").fetchone()[0]
        unit_count = check.execute("SELECT COUNT(*) FROM study_units").fetchone()[0]
        question_count = check.execute("SELECT COUNT(*) FROM questions").fetchone()[0]
        if (course_count, unit_count, question_count) != (1, len(study_unit_ids), len(question_ids)):
            raise RuntimeError("Demo snapshot count check failed")
        digest = hashlib.sha256(output.read_bytes()).hexdigest()
        manifest = {
            "format_version": 1,
            "course_id": DEMO_COURSE_ID,
            "username": DEMO_USERNAME,
            "provider_required": False,
            "counts": {
                "courses": course_count,
                "materials": material_count,
                "study_units": unit_count,
                "questions": question_count,
            },
            "sha256": digest,
        }
        output.with_name("manifest.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(f"Demo snapshot: {output}")
        print(f"Demo username: {DEMO_USERNAME}")
        print(f"Demo password: {DEMO_PASSWORD}")
        print(
            f"Courses: {course_count}; Materials: {material_count}; "
            f"StudyUnits: {unit_count}; Questions: {question_count}"
        )
        print(f"SHA256: {digest}")
    finally:
        check.close()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("demo/aiexamcoach-demo.sqlite3"),
    )
    args = parser.parse_args()
    build(args.source.resolve(), args.output.resolve())


if __name__ == "__main__":
    main()
