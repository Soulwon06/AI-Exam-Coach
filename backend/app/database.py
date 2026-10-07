from sqlalchemy import create_engine, event, inspect, text
from sqlalchemy.orm import sessionmaker, DeclarativeBase

from app.core.config import settings


class Base(DeclarativeBase):
    pass


connect_args = {}
if settings.database_url.startswith("sqlite"):
    connect_args = {"check_same_thread": False}

engine = create_engine(
    settings.database_url,
    connect_args=connect_args,
    future=True,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)


def init_db() -> None:
    from app import models  # noqa: F401  (ensure models are registered)

    Base.metadata.create_all(bind=engine)
    _migrate_auth_account_username()
    _ensure_material_parsing_columns()
    _ensure_study_unit_knowledge_columns()
    _ensure_study_unit_canonical_graph_columns()
    _ensure_exam_intelligence_schema()


def _migrate_auth_account_username() -> None:
    """Migrate the earlier email-only local auth table without dropping accounts."""
    if not settings.database_url.startswith("sqlite"):
        return
    columns = {column["name"] for column in inspect(engine).get_columns("auth_accounts")}
    if "email" not in columns or "username" in columns:
        return

    with engine.begin() as connection:
        connection.exec_driver_sql("ALTER TABLE auth_accounts RENAME TO auth_accounts_email_legacy")
        connection.exec_driver_sql(
            """CREATE TABLE auth_accounts (
                id VARCHAR(36) NOT NULL PRIMARY KEY,
                user_id VARCHAR(36) NOT NULL UNIQUE,
                username VARCHAR(320) NOT NULL UNIQUE,
                password_hash VARCHAR(256) NOT NULL,
                created_at DATETIME NOT NULL,
                FOREIGN KEY(user_id) REFERENCES users(id)
            )"""
        )
        connection.exec_driver_sql(
            """INSERT INTO auth_accounts (id, user_id, username, password_hash, created_at)
               SELECT id, user_id, email, password_hash, created_at FROM auth_accounts_email_legacy"""
        )
        connection.exec_driver_sql("DROP TABLE auth_accounts_email_legacy")
        connection.exec_driver_sql("CREATE INDEX ix_auth_accounts_username ON auth_accounts(username)")
        connection.exec_driver_sql("CREATE INDEX ix_auth_accounts_user_id ON auth_accounts(user_id)")


def _ensure_material_parsing_columns() -> None:
    """Add the P1-B fields to existing MVP SQLite databases.

    The project has no migration runner yet and create_all() does not alter an
    existing table.  These additive, nullable-safe ALTERs preserve all old
    rows and keep the application start-up compatible with the checked-in DB.
    """
    if not settings.database_url.startswith("sqlite"):
        return
    existing = {column["name"] for column in inspect(engine).get_columns("materials")}
    additions = {
        "parsing_status": "VARCHAR(20)",
        "parser_method": "VARCHAR(50)",
        "parser_version": "VARCHAR(50)",
        "extracted_text": "TEXT",
        "extracted_char_count": "INTEGER",
        "extraction_quality": "VARCHAR(20)",
        "extraction_error": "TEXT",
        "file_hash": "VARCHAR(64)",
    }
    missing = [(name, sql_type) for name, sql_type in additions.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f'ALTER TABLE materials ADD COLUMN "{name}" {sql_type}'))


def _ensure_study_unit_knowledge_columns() -> None:
    """Add the additive Course Knowledge Base fields to legacy SQLite DBs."""
    if not settings.database_url.startswith("sqlite"):
        return
    existing = {column["name"] for column in inspect(engine).get_columns("study_units")}
    additions = {
        "canonical_name": "VARCHAR(200)",
        "source_material_id": "VARCHAR(36)",
        "source_type": "VARCHAR(50)",
        "source_excerpt": "TEXT",
        "source_location": "VARCHAR(100)",
    }
    missing = [(name, sql_type) for name, sql_type in additions.items() if name not in existing]
    if not missing:
        return
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f'ALTER TABLE study_units ADD COLUMN "{name}" {sql_type}'))


def _ensure_study_unit_canonical_graph_columns() -> None:
    """Add the nullable canonical graph identity fields and exact uniqueness."""
    if not settings.database_url.startswith("sqlite"):
        return
    existing = {column["name"] for column in inspect(engine).get_columns("study_units")}
    additions = {
        "canonical_kp_id": "VARCHAR(64)",
        "canonical_graph_version": "VARCHAR(80)",
    }
    missing = [(name, sql_type) for name, sql_type in additions.items() if name not in existing]
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f'ALTER TABLE study_units ADD COLUMN "{name}" {sql_type}'))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_study_units_canonical_kp_id "
            "ON study_units(canonical_kp_id)"
        ))
        connection.execute(text(
            "CREATE INDEX IF NOT EXISTS ix_study_units_canonical_graph_version "
            "ON study_units(canonical_graph_version)"
        ))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_study_units_course_canonical_kp_id "
            "ON study_units(course_id, canonical_kp_id) "
            "WHERE canonical_kp_id IS NOT NULL"
        ))


def _ensure_exam_intelligence_schema() -> None:
    """Additive SQLite migration for provenance, mappings, and exam evidence."""
    if not settings.database_url.startswith("sqlite"):
        return
    existing = {column["name"] for column in inspect(engine).get_columns("questions")}
    additions = {
        "source_material_id": "VARCHAR(36)",
        "exam_year": "INTEGER",
        "question_number": "VARCHAR(20)",
        "subquestion_number": "VARCHAR(20)",
        "source_location": "VARCHAR(100)",
        "raw_source_text": "TEXT",
        "extraction_method": "VARCHAR(50)",
        "extraction_version": "VARCHAR(50)",
        "fingerprint": "VARCHAR(64)",
        "mapping_status": "VARCHAR(20)",
        "mapping_confidence": "FLOAT",
        "mapping_method": "VARCHAR(50)",
        "mapping_version": "VARCHAR(50)",
        "segmentation_status": "VARCHAR(40)",
        "content_quality": "VARCHAR(40)",
        "content_quality_reason": "TEXT",
        "segmentation_provenance": "JSON",
        "effective_question_context": "TEXT",
        "is_mapping_eligible": "BOOLEAN",
        "segmentation_is_current": "BOOLEAN",
    }
    missing = [(name, sql_type) for name, sql_type in additions.items() if name not in existing]
    with engine.begin() as connection:
        for name, sql_type in missing:
            connection.execute(text(f'ALTER TABLE questions ADD COLUMN "{name}" {sql_type}'))
        connection.execute(text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_questions_fingerprint "
            "ON questions(fingerprint) WHERE fingerprint IS NOT NULL"
        ))
    link_existing = {column["name"] for column in inspect(engine).get_columns("question_study_units")}
    evidence_existing = {column["name"] for column in inspect(engine).get_columns("exam_evidences")}
    with engine.begin() as connection:
        for name, sql_type in {
            "is_active": "BOOLEAN",
            "invalidated_reason": "VARCHAR(100)",
        }.items():
            if name not in link_existing:
                connection.execute(text(f'ALTER TABLE question_study_units ADD COLUMN "{name}" {sql_type}'))
            if name not in evidence_existing:
                connection.execute(text(f'ALTER TABLE exam_evidences ADD COLUMN "{name}" {sql_type}'))


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
