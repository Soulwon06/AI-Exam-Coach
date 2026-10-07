import os

from fastapi import APIRouter, Depends, File, Form, UploadFile
from sqlalchemy.orm import Session

from app import models
from app.core.errors import InvalidRequestError, NotFoundError
from app.database import get_db
from app.deps import current_user
from app.services import course_service
from app.services.material_service import (
    change_material_type,
    create_material,
    delete_material,
    material_out,
    upload_file_hash,
)
from app.worker import enqueue_material

router = APIRouter()

VALID_TYPES = {
    "REAL_EXAM", "EXAM_SCOPE", "TEACHER_PPT", "TEXTBOOK",
    "BILIBILI", "CLASS_NOTES", "HOMEWORK", "LAB", "OTHER",
}


@router.post("/courses/{course_id}/materials")
def upload_material(
    course_id: str,
    file: UploadFile = File(...),
    type: str = Form("OTHER"),
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.get_course(db, user, course_id)
    if type not in VALID_TYPES:
        raise InvalidRequestError(f"Invalid material type: {type}")

    upload_dir = os.path.join(os.getcwd(), "data", "materials")
    file_hash = upload_file_hash(file)
    existing = (
        db.query(models.Material)
        .filter(
            models.Material.course_id == course.id,
            models.Material.file_hash == file_hash,
        )
        .order_by(models.Material.created_at.asc())
        .first()
    )
    if existing is not None:
        data = material_out(existing)
        data.update({"upload_status": "REUSED", "duplicate": True, "reused": True})
        return {"data": data, "error": None}

    material = create_material(
        db, course, type, file=file, upload_dir=upload_dir, file_hash=file_hash
    )
    db.commit()
    # course moves to ANALYZING while material processes
    course.status = "ANALYZING"
    db.commit()

    enqueue_material(material.id)
    data = material_out(material)
    data.update({"upload_status": "UPLOADED", "duplicate": False, "reused": False})
    return {"data": data, "error": None}


@router.post("/courses/{course_id}/materials/url")
def upload_url(
    course_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.get_course(db, user, course_id)
    mtype = payload.get("type", "OTHER")
    url = payload.get("url", "").strip()
    if mtype not in VALID_TYPES:
        raise InvalidRequestError(f"Invalid material type: {mtype}")
    if not url:
        raise InvalidRequestError("url is required")

    material = create_material(db, course, mtype, url=url)
    db.commit()
    course.status = "ANALYZING"
    db.commit()

    enqueue_material(material.id)
    data = material_out(material)
    data.update({"upload_status": "UPLOADED", "duplicate": False, "reused": False})
    return {"data": data, "error": None}


@router.patch("/courses/{course_id}/materials/{material_id}")
def update_material_type(
    course_id: str,
    material_id: str,
    payload: dict,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.get_course(db, user, course_id)
    new_type = (payload.get("type") or "").strip()
    if new_type not in VALID_TYPES:
        raise InvalidRequestError(f"Invalid material type: {new_type}")

    type_change = change_material_type(db, course, material_id, new_type)
    db.commit()
    material = db.get(models.Material, material_id)
    data = material_out(material)
    data["type_change"] = type_change
    return {"data": data, "error": None}


@router.delete("/courses/{course_id}/materials/{material_id}")
def delete_material_route(
    course_id: str,
    material_id: str,
    db: Session = Depends(get_db),
    user: models.User = Depends(current_user),
):
    course = course_service.get_course(db, user, course_id)
    delete_material(db, course, material_id)
    db.commit()
    return {"data": {"id": material_id, "deleted": True}, "error": None}


@router.get("/materials/{material_id}")
def material_status(material_id: str, db: Session = Depends(get_db), user: models.User = Depends(current_user)):
    m = db.get(models.Material, material_id)
    if m is None:
        raise NotFoundError("Material not found")
    course = course_service.get_course(db, user, m.course_id)
    return {"data": material_out(m), "error": None}
