"""Unit tests for the core engines:
- Practice grading (docs/11 Phase 11, docs/03 user flow)
- Scoring labels / mastery transitions (docs/05)
- Decision Engine phases (docs/06)
- Heuristic question extraction must never emit unanswerable/fake questions

Per docs/11 Phase 20: Scoring, Decision, Practice, and Course Brain mapping all
need unit coverage, and docs/12 forbids "fake completion".
"""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models as m
from app.routers import learning, study_units
from app.database import Base
from app.services import decision_engine, practice, scoring
from app.services.course_brain import _resolve_material_path
from app.services.ai_provider import HeuristicProvider
from app.services.scoring import _label, update_mastery_after_answer
from app.services.practice_metrics import practice_metrics


@pytest.fixture
def db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine, autoflush=False)
    session = Session()
    yield session
    session.close()
    engine.dispose()


def _make_unit(db, course_id="c1", **kw):
    u = m.StudyUnit(
        id=kw.get("id", "u1"),
        course_id=course_id,
        domain_id=None,
        title=kw.get("title", "TCP三次握手"),
        canonical_name=kw.get("canonical_name", kw.get("title", "TCP三次握手")),
        source_type=kw.get("source_type", "TEXTBOOK"),
        importance_score=kw.get("importance_score", 60.0),
        importance_label=kw.get("importance_label", "HIGH"),
        difficulty_score=kw.get("difficulty_score", 50.0),
        mastery_status=kw.get("mastery_status", "UNKNOWN"),
        coverage_status=kw.get("coverage_status", "NOT_STARTED"),
    )
    db.add(u)
    db.flush()
    return u


def _attach_short_answer_question(db, unit, question_id):
    question = m.Question(
        id=question_id,
        course_id=unit.course_id,
        type="SHORT_ANSWER",
        content="请解释这个知识点的核心含义。",
        answer="核心含义",
    )
    db.add(question)
    db.flush()
    db.add(m.QuestionStudyUnit(
        question_id=question.id,
        study_unit_id=unit.id,
        is_primary=True,
        relevance_score=1.0,
    ))
    db.flush()
    return question


# --------------------------------------------------------------------------- #
# Practice grading


def test_choice_grading_accepts_letter_and_text():
    q = m.Question(id="q1", course_id="c1", type="SINGLE_CHOICE", content="甲选？", answer="B",
                   options=["A. 甲", "B. 乙", "C. 丙", "D. 丁"])
    assert practice._is_correct(q, "B") is True
    assert practice._is_correct(q, "乙") is True
    assert practice._is_correct(q, "A") is False
    assert practice._is_correct(q, "  b  ") is True


def test_judgment_grading_normalizes_variants():
    q = m.Question(id="q2", course_id="c1", type="TRUE_FALSE", content="判断：XX", answer="T")
    for hit in ("T", "t", "对", "正确", "√"):
        assert practice._is_correct(q, hit) is True, hit
    for miss in ("F", "错", "错误", "×"):
        assert practice._is_correct(q, miss) is False, miss


def test_multiple_choice_order_independent():
    q = m.Question(id="q3", course_id="c1", type="MULTIPLE_CHOICE", content="多选", answer="ABD",
                   options=["A. 甲", "B. 乙", "C. 丙", "D. 丁"])
    assert practice._is_correct(q, "ABD") is True
    assert practice._is_correct(q, "DBA") is True
    assert practice._is_correct(q, "AB") is False
    assert practice._is_correct(q, "ABC") is False


def test_short_answer_keyword_overlap():
    q = m.Question(id="q4", course_id="c1", type="SHORT_ANSWER",
                   content="简述TCP", answer="TCP建立连接需要三次握手")
    assert practice._is_correct(q, "TCP建立连接需要进行三次握手") is True
    assert practice._is_correct(q, "完全无关的内容") is False
    assert practice._is_correct(q, "") is False


def test_empty_answer_cannot_be_graded_true():
    q = m.Question(id="q5", course_id="c1", type="SHORT_ANSWER", content="问", answer="")
    assert practice._is_correct(q, "随便什么") is False
    assert practice._is_correct(q, "") is False


# --------------------------------------------------------------------------- #
# Scoring


def test_importance_labels():
    assert _label(90) == "HIGH"
    assert _label(45) == "MEDIUM"
    assert _label(10) == "LOW"


def test_mastery_transitions(db):
    unit = _make_unit(db)
    _attach_short_answer_question(db, unit, "qx")
    db.add(m.PracticeRecord(id="r1", session_id="s1", question_id="qx", user_id="u1",
                            study_unit_id=unit.id, answer="x", correct=False))
    db.commit()
    update_mastery_after_answer(db, db.query(m.PracticeRecord).first())
    assert unit.mastery_status == "WEAK"
    assert unit.coverage_status == "COVERED"


def test_mastery_after_correct_answers(db):
    unit = _make_unit(db, id="u2")
    _attach_short_answer_question(db, unit, "qx")
    for i in range(5):
        db.add(m.PracticeRecord(id=f"r{i}", session_id="s1", question_id="qx", user_id="u1",
                                study_unit_id=unit.id, answer="x", correct=True))
    record = m.PracticeRecord(id="rz", session_id="s1", question_id="qx", user_id="u1",
                              study_unit_id=unit.id, answer="x", correct=True)
    db.add(record)
    db.commit()
    update_mastery_after_answer(db, record)
    assert unit.mastery_status == "MASTERED"


def test_coverage_counts_distinct_questions_and_exposes_partial_state(db):
    user, _, unit, session, questions = _make_practice_session(db, question_count=3)
    first = m.PracticeRecord(
        id="coverage-first",
        session_id=session.id,
        question_id=questions[0].id,
        user_id=user.id,
        study_unit_id=unit.id,
        answer="A",
        correct=True,
    )
    db.add(first)
    db.flush()
    update_mastery_after_answer(db, first)

    metrics = practice_metrics(db, user_id=user.id, unit=unit)
    assert metrics["valid_question_count"] == 3
    assert metrics["attempted_question_count"] == 1
    assert metrics["coverage_status"] == "PARTIAL"
    assert unit.coverage_status == "IN_PROGRESS"  # database compatibility value


def test_mastery_uses_latest_answer_per_question_only_after_coverage(db):
    user, _, unit, session, questions = _make_practice_session(db, question_count=3)
    records = []
    for index, (question, correct) in enumerate(zip(questions, (True, True, False)), start=1):
        record = m.PracticeRecord(
            id=f"latest-record-{index}",
            session_id=session.id,
            question_id=question.id,
            user_id=user.id,
            study_unit_id=unit.id,
            answer="A",
            correct=correct,
        )
        db.add(record)
        records.append(record)
    db.flush()
    update_mastery_after_answer(db, records[-1])

    metrics = practice_metrics(db, user_id=user.id, unit=unit)
    assert metrics["coverage_status"] == "COVERED"
    assert metrics["mastery_percent"] == 66.7
    assert unit.mastery_status == "LEARNING"


def test_repeated_attempt_does_not_add_coverage_but_latest_answer_wins(db):
    user, _, unit, session, questions = _make_practice_session(db, question_count=2)
    first = m.PracticeRecord(
        id="repeat-wrong",
        session_id=session.id,
        question_id=questions[0].id,
        user_id=user.id,
        study_unit_id=unit.id,
        answer="B",
        correct=False,
        created_at=datetime.utcnow(),
    )
    second = m.PracticeRecord(
        id="repeat-right",
        session_id=session.id,
        question_id=questions[0].id,
        user_id=user.id,
        study_unit_id=unit.id,
        answer="A",
        correct=True,
        created_at=datetime.utcnow() + timedelta(seconds=1),
    )
    db.add_all([first, second])
    db.flush()
    update_mastery_after_answer(db, second)

    metrics = practice_metrics(db, user_id=user.id, unit=unit)
    assert metrics["attempted_question_count"] == 1
    assert metrics["coverage_status"] == "PARTIAL"
    assert metrics["mastery_percent"] == 100.0


def _make_owned_unit(db, user_id="state-user", course_id="state-course", unit_id="state-unit"):
    user = m.User(id=user_id)
    course = m.Course(id=course_id, user_id=user.id, name="State Contract Course", status="READY")
    db.add_all([user, course])
    db.flush()
    unit = _make_unit(db, course_id=course.id, id=unit_id)
    return user, course, unit


def test_skip_endpoint_records_deferred_preference_without_verified_mastery(db):
    user, _, unit = _make_owned_unit(db)

    result = study_units.skip_study_unit(unit.id, db, user)

    db.refresh(unit)
    assert result["data"]["status"] == "SKIPPED"
    assert unit.mastery_status == "UNKNOWN"
    assert unit.progress == 0
    assert db.query(m.PracticeRecord).count() == 0
    assert db.query(m.LearningRecord).filter_by(study_unit_id=unit.id, event_type="SKIPPED").count() == 1


def test_master_endpoint_records_self_assessment_without_fabricating_verified_mastery(db):
    user, _, unit = _make_owned_unit(db, user_id="master-user", course_id="master-course", unit_id="master-unit")

    result = study_units.master_study_unit(unit.id, db, user)

    db.refresh(unit)
    assert result["data"]["self_assessed_mastery"] is True
    assert unit.mastery_status == "UNKNOWN"
    assert unit.coverage_status == "NOT_STARTED"
    assert unit.progress == 0
    assert db.query(m.PracticeRecord).count() == 0
    assert db.query(m.LearningRecord).filter_by(study_unit_id=unit.id, event_type="MASTERED").count() == 1


def test_skipped_study_unit_remains_excluded_from_recommendation(db):
    user, course, skipped = _make_owned_unit(
        db, user_id="recommend-user", course_id="recommend-course", unit_id="skipped-unit"
    )
    skipped.mastery_status = "SKIPPED"
    active = _make_unit(db, course_id=course.id, id="active-unit", title="Active Unit")

    recommendation = decision_engine.get_recommendation(db, user, course)

    assert recommendation["study_unit"]["id"] == active.id


def test_percentage_api_contract_stays_on_zero_to_hundred_scale(db):
    user, course, unit = _make_owned_unit(
        db, user_id="percentage-user", course_id="percentage-course", unit_id="percentage-unit"
    )
    _attach_short_answer_question(db, unit, "percentage-question-1")
    _attach_short_answer_question(db, unit, "percentage-question-2")
    for index, correct in enumerate((True, False), start=1):
        db.add(
            m.PracticeRecord(
                id=f"percentage-record-{index}",
                session_id="percentage-session",
                question_id=f"percentage-question-{index}",
                user_id=user.id,
                study_unit_id=unit.id,
                answer="x",
                correct=correct,
            )
        )
    db.commit()

    assert scoring.recent_accuracy(db, user.id, unit.id) == 50.0
    progress = scoring.course_progress(db, course)
    assert all(0 <= value <= 100 for value in progress.values())


# --------------------------------------------------------------------------- #
# Decision Engine phases


def test_phase_strategy():
    assert decision_engine._phase(8) == "STRENGTHENING"
    assert decision_engine._phase(4) == "COVERAGE"
    assert decision_engine._phase(2) == "FINAL_SPRINT"
    assert decision_engine._phase(1) == "FINAL_SPRINT"


def test_final_sprint_prioritizes_importance_regardless_of_coverage():
    unit = m.StudyUnit(id="uf", course_id="c1", title="重要", importance_score=80.0,
                       importance_label="HIGH", difficulty_score=50.0,
                       mastery_status="UNKNOWN", coverage_status="NOT_STARTED",
                       question_links=[])
    score, reason = decision_engine.compute_priority(unit, 1, "FINAL_SPRINT", {})
    assert "FINAL_SPRINT" in reason
    assert score > 0
    # In sprint, a not-yet-covered unit is not penalized: coverage not in formula.
    score2, _ = decision_engine.compute_priority(unit, 1, "COVERAGE", {})
    assert score2 != score


# --------------------------------------------------------------------------- #
# Practice session lifecycle


def _make_practice_session(db, question_count=3):
    user = m.User(id="practice-user")
    course = m.Course(id="practice-course", user_id=user.id, name="Practice Course")
    unit = _make_unit(db, course_id=course.id, id="practice-unit", title="Practice Unit")
    session = m.LearningSession(
        id="practice-session",
        user_id=user.id,
        course_id=course.id,
        study_unit_id=unit.id,
        mode="QUESTION_FIRST",
        current_state="QUESTION",
    )
    db.add_all([user, course, session])
    db.flush()

    questions = []
    for index in range(question_count):
        question = m.Question(
            id=f"practice-q{index + 1}",
            course_id=course.id,
            type="SINGLE_CHOICE",
            content=f"Question {index + 1}",
            options=["A. Correct", "B. Wrong"],
            answer="A",
        )
        db.add(question)
        db.flush()
        db.add(m.QuestionStudyUnit(
            question_id=question.id,
            study_unit_id=unit.id,
            is_primary=True,
            relevance_score=1.0,
        ))
        questions.append(question)
    db.flush()
    return user, course, unit, session, questions


def test_next_question_returns_unanswered_questions_in_order(db):
    user, _, unit, session, questions = _make_practice_session(db)

    assert practice.next_question(db, user, session).id == questions[0].id
    db.add(m.PracticeRecord(
        id="practice-record-1",
        session_id=session.id,
        question_id=questions[0].id,
        user_id=user.id,
        study_unit_id=unit.id,
        answer="A",
        correct=True,
    ))
    db.flush()
    assert practice.next_question(db, user, session).id == questions[1].id


def test_next_question_never_returns_answered_question_again(db):
    user, _, unit, session, questions = _make_practice_session(db)
    for index, question in enumerate(questions[:2], start=1):
        db.add(m.PracticeRecord(
            id=f"practice-record-{index}",
            session_id=session.id,
            question_id=question.id,
            user_id=user.id,
            study_unit_id=unit.id,
            answer="A",
            correct=True,
        ))
    db.flush()

    assert practice.next_question(db, user, session).id == questions[2].id


def test_final_answer_completes_session_and_next_question_returns_terminal_state(db):
    user, _, unit, session, questions = _make_practice_session(db, question_count=2)

    first = practice.answer_question(db, user, session, questions[0].id, "A", 1)
    assert first["correct"] is True
    assert first["next_action"] == "NEXT_QUESTION"
    assert session.completed_at is None

    final = practice.answer_question(db, user, session, questions[1].id, "A", 1)
    assert final["correct"] is True
    assert final["next_action"] == "COMPLETE"
    assert final["next_question_id"] is None
    assert session.current_state == "COMPLETED"
    assert session.completed_at is not None
    assert unit.mastery_status == "MASTERED"

    terminal = learning.next_question(session.id, db, user)
    assert terminal["data"]["status"] == "COMPLETE"
    assert terminal["data"]["question"] is None


def test_session_without_available_questions_terminates_safely(db):
    user, _, _, session, _ = _make_practice_session(db, question_count=0)

    terminal = learning.next_question(session.id, db, user)
    assert terminal["data"]["status"] == "COMPLETE"
    assert terminal["data"]["question"] is None
    assert session.current_state == "COMPLETED"
    assert session.completed_at is not None


# --------------------------------------------------------------------------- #
# Question extraction (Course Brain input)


def test_heuristic_extracts_only_gradeable_questions():
    text = (
        "# 网络基础\n"
        "1. TCP建立连接的正确描述是？\n"
        "A. 需要四次挥手\n"
        "B. 需要三次握手\n"
        "C. 不需要握手\n"
        "D. 以上都不对\n"
        "答案：B\n"
        "2. 简述ARP的作用。\n"  # no answer key -> must be dropped
        "3. 判断：TCP提供可靠的面向连接服务。\n"
        "答案：对\n"
    )
    provider = HeuristicProvider()
    result = provider.analyze_material(text, "REAL_EXAM")
    questions = result["questions"]
    answers = {q["content"][:8]: q for q in questions}
    assert "TCP建立连接的正确描述是？" in "".join(q["content"] for q in questions)
    assert any(q["type"] == "SINGLE_CHOICE" and q["answer"] == "B" for q in questions)
    assert any(q["type"] == "TRUE_FALSE" and q["answer"] == "T" for q in questions)
    # Unanswerable short-answer question must not be emitted as fake data.
    assert not any(q["type"] == "SHORT_ANSWER" and not q["answer"] for q in questions)


def test_heuristic_does_not_merge_unrelated_lines_into_one_question():
    text = (
        "1. 以太网的CSMA/CD协议原理。\n"  # declarative numbered line, no key
        "IP地址的分类与子网划分。\n"
        "ARP协议的作用是把IP地址解析为MAC地址。\n"
    )
    provider = HeuristicProvider()
    result = provider.analyze_material(text, "REAL_EXAM")
    assert result["questions"] == [], result["questions"]
    # Unstructured declarative lines are evidence, not automatically titles.
    assert result["study_units"] == []


def test_knowledge_units_are_traceable_and_question_stems_are_not_titles():
    text = (
        "# 数据库系统\n"
        "## 事务管理\n"
        "事务的ACID特性用于保证数据库操作的正确性。\n"
        "1. 关于事务隔离性的说法正确的是？\n"
        "A. 可以读取未提交数据\nB. 不会产生并发问题\n答案：A\n"
    )
    result = HeuristicProvider().analyze_material(text, "REAL_EXAM")
    units = result["study_units"]
    assert any(unit["title"] == "事务管理" for unit in units)
    assert all(unit.get("evidence") for unit in units)
    assert not any("关于事务隔离性" in unit["title"] for unit in units)


def test_one_off_exam_target_is_not_invented_as_a_knowledge_point():
    text = (
        "1. 关于事务隔离性的说法正确的是？\n"
        "A. 可以读取未提交数据\nB. 不会产生并发问题\n答案：A\n"
    )
    result = HeuristicProvider().analyze_material(text, "REAL_EXAM")
    assert result["study_units"] == []
    assert result["questions"] and result["questions"][0]["knowledge_titles"]


def test_heuristic_filters_exam_metadata_and_english_fragments_with_trace():
    text = (
        "# 数据库系统\n"
        "考试时间：120分钟\n"
        "版权所有：某平台\n"
        "收集\n制作\n属性\n"
        "## 事务管理\n"
        "list as: columns\n"
        "needed is: required\n"
        "query as follows: ...\n"
        "are defined as follows: ...\n"
        "Global Publisher: x\n"
        "## SQL 查询\n"
    )
    result = HeuristicProvider().analyze_material(text, "REAL_EXAM")
    titles = [unit["title"] for unit in result["study_units"]]

    assert titles == ["事务管理", "SQL 查询"]
    assert result["trace"]["raw_text_sample"]
    assert "事务管理" in result["trace"]["cleaned_text_sample"]
    filtered = {item["candidate"]: item["reason"] for item in result["trace"]["filtered_candidates"]}
    assert filtered["考试时间：120分钟"] == "exam-or-copyright-metadata"
    assert filtered["list as"] == "english-sentence-fragment"
    assert filtered["Global Publisher"] == "non-technical-english-phrase"


def test_heuristic_deduplicates_near_duplicate_concepts():
    result = HeuristicProvider().analyze_material(
        "## 关系模式\n## 关系  模式\n## 事务管理\n## 事务管理\n",
        "TEXTBOOK",
    )
    assert [unit["title"] for unit in result["study_units"]] == ["关系模式", "事务管理"]
    assert any(item["reason"] == "duplicate-or-near-duplicate" for item in result["trace"]["filtered_candidates"])


def test_legacy_material_path_resolves_to_managed_upload_dir(monkeypatch, tmp_path):
    import app.services.course_brain as brain

    managed = tmp_path / "data" / "materials"
    managed.mkdir(parents=True)
    uploaded = managed / "source.pdf"
    uploaded.write_bytes(b"%PDF-1.7")
    monkeypatch.setattr(brain.os.path, "dirname", lambda _: str(tmp_path / "app" / "services"))
    assert _resolve_material_path("/mnt/d/old/backend/data/materials/source.pdf") == str(uploaded)
