from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app import models
from app.database import Base
from app.services import exam_intelligence


def _db():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    return engine, sessionmaker(bind=engine, autoflush=False)()


def _course_and_material(db, text):
    db.add(models.User(id="user1"))
    db.add(models.Course(id="course1", user_id="user1", name="数据库系统", status="READY"))
    db.add(models.Material(
        id="exam1", course_id="course1", type="REAL_EXAM", source="upload",
        name="2026期末试卷.pdf", parsing_status="PARSED", parser_method="pdf_text",
        extracted_text=text, extracted_char_count=len(text), file_hash="a" * 64,
    ))
    db.add(models.StudyUnit(
        id="u-lock", course_id="course1", title="Two-Phase Locking",
        canonical_name="Two-Phase Locking", source_material_id="teaching1",
        source_type="TEXTBOOK", source_excerpt="Two-phase locking controls serializability.",
    ))
    db.add(models.StudyUnit(
        id="u-acid", course_id="course1", title="Transaction ACID",
        canonical_name="Transaction ACID", source_material_id="teaching1",
        source_type="TEXTBOOK", source_excerpt="Transactions have ACID properties.",
    ))
    db.flush()


def test_segmentation_removes_metadata_and_preserves_provenance():
    result = exam_intelligence.segment_exam_text(
        """2026年数据库系统期末试题
考试时间：120分钟
版权所有：某大学
----- page 2 -----
一、选择题（共2题）
1. 两阶段锁协议可保证（ ）
A. 不发生死锁
B. 形成可串行调度
2. 在事务的 ACID 性质中，I 代表（ ）
A. Integration
B. Isolation
制作团队介绍
"""
    )
    questions = result["questions"]
    assert len(questions) == 2
    assert questions[0].question_number == "1"
    assert questions[0].source_location == "2"
    assert "版权所有" not in questions[0].content
    assert questions[0].options == ["A. 不发生死锁", "B. 形成可串行调度"]


def test_real_exam_creates_questions_but_never_study_units():
    engine, db = _db()
    _course_and_material(db, "----- page 2 -----\n1. 两阶段锁协议可保证（ ）\nA. 不发生死锁\nB. 形成可串行调度\n")
    before = db.query(models.StudyUnit).count()
    result = exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    assert result["status"] == "COMPLETED"
    assert result["created_count"] == 1
    assert db.query(models.StudyUnit).count() == before
    question = db.query(models.Question).one()
    assert question.source_material_id == "exam1"
    assert question.question_number == "1"
    assert question.source_location == "2"
    assert question.mapping_status in {"MATCHED", "AMBIGUOUS", "UNMATCHED"}
    db.close()
    engine.dispose()


def test_exam_persistence_can_skip_mapping_without_creating_evidence(monkeypatch):
    engine, db = _db()
    _course_and_material(db, "----- page 2 -----\n1. 两阶段锁协议可保证（ ）\nA. 不发生死锁\nB. 形成可串行调度\n")
    monkeypatch.setattr(
        exam_intelligence,
        "map_question",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("mapping must be skipped")),
    )

    result = exam_intelligence.process_exam_material(
        db, db.get(models.Material, "exam1"), run_mapping=False
    )

    assert result["created_count"] == 1
    assert result["parser_calls"] == 0
    assert result["ocr_calls"] == 0
    question = db.query(models.Question).one()
    assert question.mapping_status == "PENDING"
    assert question.mapping_confidence is None
    assert db.query(models.QuestionStudyUnit).count() == 0
    assert db.query(models.ExamEvidence).count() == 0
    db.close()
    engine.dispose()


def test_cached_exam_path_does_not_call_material_parser(monkeypatch):
    engine, db = _db()
    _course_and_material(db, "----- page 2 -----\n1. 两阶段锁协议可保证（ ）\nA. 不发生死锁\nB. 形成可串行调度\n")
    monkeypatch.setattr("app.services.course_brain.parse_material", lambda *a, **k: (_ for _ in ()).throw(AssertionError("parser called")))
    result = exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    assert result["parser_calls"] == 0
    assert result["ocr_calls"] == 0
    db.close()
    engine.dispose()


def test_exam_processing_is_idempotent():
    engine, db = _db()
    _course_and_material(db, "----- page 2 -----\n1. 两阶段锁协议可保证（ ）\nA. 不发生死锁\nB. 形成可串行调度\n")
    material = db.get(models.Material, "exam1")
    first = exam_intelligence.process_exam_material(db, material)
    second = exam_intelligence.process_exam_material(db, material)
    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert second["reused_count"] == 1
    assert db.query(models.Question).count() == 1
    assert db.query(models.ExamEvidence).count() <= 2
    db.close()
    engine.dispose()


def test_mapping_abstains_and_rejects_invalid_study_unit_ids():
    engine, db = _db()
    item = exam_intelligence.segment_exam_text("1. 一个完全无关的天文学问题？")["questions"][0]
    units = [models.StudyUnit(id="u1", course_id="c", title="Two-Phase Locking", canonical_name="Two-Phase Locking", source_type="TEXTBOOK")]
    result = exam_intelligence.map_question(item, units)
    assert result["status"] in {"AMBIGUOUS", "UNMATCHED"}
    assert result["primary"] is None
    try:
        exam_intelligence.validate_mapping_result({"status": "MATCHED", "primary": {"study_unit_id": "missing"}}, {"u1"})
    except ValueError as exc:
        assert "unknown StudyUnit" in str(exc)
    else:
        raise AssertionError("invalid StudyUnit ID was accepted")
    db.close()
    engine.dispose()


def test_chinese_exam_signal_can_match_english_teaching_unit():
    item = exam_intelligence.segment_exam_text("1. 两阶段锁协议可保证（ ）\nA. 不发生死锁\nB. 形成可串行调度")["questions"][0]
    unit = models.StudyUnit(id="u1", course_id="c", title="Lock-Based Protocols", canonical_name="Lock-Based Protocols", source_type="TEXTBOOK")
    result = exam_intelligence.map_question(item, [unit])
    assert result["status"] == "MATCHED"
    assert result["primary"]["study_unit_id"] == "u1"


def test_two_independent_mcqs_do_not_merge():
    result = exam_intelligence.segment_exam_text(
        "1. 两阶段锁协议可保证（ ）\nA. 可串行化\nB. 死锁\n"
        "2. 事务的 I 代表（ ）\nA. Isolation\nB. Index\n"
    )
    assert len(result["questions"]) == 2
    assert all(item.segmentation_status == "PASS" for item in result["questions"])


def test_multiple_sql_subquestions_are_blocked_as_merged():
    result = exam_intelligence.segment_exam_text(
        "2.（7分）查询每个图书室中单价超过50元的图书数量。\n"
        "（10分）数据库模式结构如下。使用 NOT EXISTS 构建查询。\n"
        "select rID from Room; select count(*) from BookPub;"
    )
    assert len(result["questions"]) == 1
    assert result["questions"][0].segmentation_status == "MERGED_MULTIPLE_QUESTIONS"


def test_short_valid_mcq_remains_mapping_eligible():
    item = exam_intelligence.segment_exam_text("2. 两阶段锁协议可保证（ ）\nA. 可串行调度\nB. 一定无死锁")["questions"][0]
    quality = exam_intelligence.assess_question_quality(item)
    assert item.segmentation_status == "PASS"
    assert quality["is_mapping_eligible"] is True


def test_missing_formula_symbols_fail_content_integrity():
    item = exam_intelligence.segment_exam_text("5. 已知关系模式（, , ）及其函数依赖集={ → , → }，求属性集的闭包。")["questions"][0]
    assert item.content_quality == "SOURCE_TEXT_CORRUPTED"
    assert exam_intelligence.assess_question_quality(item)["is_mapping_eligible"] is False


def test_ocr_noise_but_understandable_remains_usable():
    item = exam_intelligence.segment_exam_text("1. E-R图是一种直观示伪¤§※模型的工具（ ）\nA. 概念模型\nB. 关系模型")["questions"][0]
    assert item.content_quality in {"PASS", "OCR_NOISY_BUT_USABLE"}
    assert exam_intelligence.assess_question_quality(item)["is_mapping_eligible"] is True


def test_context_dependent_question_restores_parent_context():
    engine, db = _db()
    _course_and_material(db, "3. 查询每个城市的旅馆数量。\n4. 使用 NOT IN 结构完成题目3的查询要求。\n")
    result = exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    questions = db.query(models.Question).filter(models.Question.source_material_id == "exam1").order_by(models.Question.question_number).all()
    child = next(q for q in questions if q.question_number == "4")
    parent = next(q for q in questions if q.question_number == "3")
    assert child.parent_question_id == parent.id
    assert "查询每个城市" in child.effective_question_context
    assert child.is_mapping_eligible is True
    assert result["parser_calls"] == 0
    db.close()
    engine.dispose()


def test_repeated_question_number_reference_prefers_latest_local_block():
    engine, db = _db()
    _course_and_material(
        db,
        "----- page 1 -----\n"
        "3. First local block parent question.\n"
        "----- page 2 -----\n"
        "1. Second local block setup question.\n"
        "2. Second local block another question.\n"
        "3. Second local block parent question.\n"
        "4. 使用 NOT IN 结构完成题目3的查询要求。\n",
    )
    exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    questions = db.query(models.Question).filter(models.Question.source_material_id == "exam1").all()
    old_parent = next(q for q in questions if "First local block parent" in q.content)
    local_parent = next(q for q in questions if "Second local block parent" in q.content)
    child = next(q for q in questions if q.question_number == "4")

    assert old_parent.id != local_parent.id
    assert child.parent_question_id == local_parent.id
    assert "Second local block parent" in child.effective_question_context
    db.close()
    engine.dispose()


def test_explicit_reference_never_resolves_to_a_future_question():
    engine, db = _db()
    _course_and_material(
        db,
        "4. 使用 NOT IN 结构完成题目5的查询要求。\n"
        "5. Future question that must not become the parent.\n",
    )
    exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    child = db.query(models.Question).filter(models.Question.question_number == "4").one()

    assert child.parent_question_id is None
    assert child.effective_question_context is None
    assert child.content_quality == "CONTEXT_MISSING"
    db.close()
    engine.dispose()


def test_explicit_reference_abstains_when_matching_parent_is_outside_lookback():
    engine, db = _db()
    filler = "".join(f"{number}. Filler question {number}.\n" for number in range(10, 23))
    _course_and_material(
        db,
        "3. Old local block parent question.\n"
        f"{filler}"
        "4. 使用 NOT IN 结构完成题目3的查询要求。\n",
    )
    exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    child = db.query(models.Question).filter(models.Question.question_number == "4").one()

    assert child.parent_question_id is None
    assert child.effective_question_context is None
    assert child.content_quality == "CONTEXT_MISSING"
    db.close()
    engine.dispose()


def test_unresolved_parent_is_context_missing_and_ineligible():
    engine, db = _db()
    _course_and_material(db, "4. 使用 NOT IN 结构完成题目3的查询要求。\n")
    exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    question = db.query(models.Question).one()
    assert question.content_quality == "CONTEXT_MISSING"
    assert question.is_mapping_eligible is False
    db.close()
    engine.dispose()


def test_merged_question_cannot_create_exam_evidence():
    engine, db = _db()
    _course_and_material(db, "2.（7分）查询每个图书室中的图书数量。\n（10分）使用 NOT EXISTS 构建查询。\nselect rID from Room; select count(*) from BookPub;\n")
    exam_intelligence.process_exam_material(db, db.get(models.Material, "exam1"))
    question = db.query(models.Question).one()
    assert question.segmentation_status == "MERGED_MULTIPLE_QUESTIONS"
    assert question.is_mapping_eligible is False
    assert db.query(models.ExamEvidence).filter(models.ExamEvidence.question_id == question.id, models.ExamEvidence.is_active.isnot(False)).count() == 0
    db.close()
    engine.dispose()


def test_quality_gate_invalidation_is_non_destructive_and_rerunnable():
    engine, db = _db()
    _course_and_material(db, "1. 两阶段锁协议可保证（ ）\nA. 可串行调度\nB. 一定无死锁\n")
    material = db.get(models.Material, "exam1")
    first = exam_intelligence.process_exam_material(db, material)
    question = db.query(models.Question).one()
    link_count = db.query(models.QuestionStudyUnit).filter(models.QuestionStudyUnit.question_id == question.id).count()
    second = exam_intelligence.process_exam_material(db, material)
    assert first["created_count"] == 1
    assert second["created_count"] == 0
    assert db.query(models.QuestionStudyUnit).filter(models.QuestionStudyUnit.question_id == question.id).count() == link_count
    assert db.query(models.QuestionStudyUnit).filter(models.QuestionStudyUnit.question_id == question.id, models.QuestionStudyUnit.is_active.isnot(False)).count() <= 1
    assert question.segmentation_is_current is True
    db.close()
    engine.dispose()
