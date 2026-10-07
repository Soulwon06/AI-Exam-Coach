from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app import models
from app.core.errors import AppError, InternalError, InvalidRequestError
from app.database import get_db
from app.deps import current_user
from app.services import course_service
from app.services import ranking_v1


router = APIRouter()


@router.get("/courses/{course_id}/ranking")
def course_ranking(
    course_id: str,
    limit: int = Query(default=50, ge=1, le=367),
    offset: int = Query(default=0, ge=0),
    exam_evidence_tier: str | None = Query(default=None),
    entity_role: str | None = Query(default=None),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.get_course(db, user, course_id)
    try:
        data = ranking_v1.get_course_ranking(
            course,
            db=db,
            limit=limit,
            offset=offset,
            exam_evidence_tier=exam_evidence_tier,
            entity_role=entity_role,
        )
    except ranking_v1.RankingV1NotAvailableError as exc:
        raise AppError("RANKING_V1_NOT_AVAILABLE_FOR_COURSE", str(exc), status_code=404) from exc
    except ValueError as exc:
        raise InvalidRequestError(str(exc)) from exc
    except ranking_v1.RankingV1ContractError as exc:
        raise InternalError("Ranking v1 artifact validation failed") from exc
    return {"data": data, "error": None}
