from app.extensions import db
from app.models import Classroom, FaceData, Student
from app.utils import utc_now
from app.utils.face_embedding_utils import average_embeddings, find_best_face_match


def _authorize_student(student, user):
    from app.controllers.student_controller import _authorize_student_access

    return _authorize_student_access(student, user)


def _parse_descriptor(data):
    descriptor = data.get("descriptor") or data.get("face_embedding") or data.get("embedding")
    if isinstance(descriptor, list) and len(descriptor) == 128:
        try:
            return [float(v) for v in descriptor]
        except (TypeError, ValueError):
            return None
    return None


def _parse_descriptor_list(data):
    raw = data.get("embeddings") or data.get("descriptors") or data.get("samples")
    if isinstance(raw, list) and raw:
        if all(isinstance(item, list) for item in raw):
            return average_embeddings(raw)
        return None
    return _parse_descriptor(data)


def upsert_student_face_embedding(
    student: Student,
    embedding: list[float],
    *,
    registered_by=None,
) -> FaceData:
    row = FaceData.query.filter_by(student_id=student.id).first()
    now = utc_now()
    if row:
        row.face_embedding = embedding
        row.updated_at = now
        row.institution_id = student.institution_id
        if registered_by is not None:
            row.registered_by = registered_by
    else:
        row = FaceData(
            student_id=student.id,
            institution_id=student.institution_id,
            face_embedding=embedding,
            registered_by=registered_by,
            created_at=now,
            updated_at=now,
        )
        db.session.add(row)
    student.face_descriptor = embedding
    return row


def register_face(data, user):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student_id = data.get("studentId") or data.get("student_id")
    try:
        student_id = int(student_id)
    except (TypeError, ValueError):
        return {"errors": ["studentId is required"]}, 400

    student = Student.query.get(student_id)
    denied = _authorize_student(student, user)
    if denied:
        return denied

    embedding = _parse_descriptor_list(data)
    if not embedding:
        return {"errors": ["Provide descriptor or embeddings (128-d vectors)"]}, 400

    try:
        row = upsert_student_face_embedding(student, embedding, registered_by=user.id)
        db.session.commit()
        db.session.refresh(student)
        return {
            "success": True,
            "message": "Face profile registered",
            "face": row.to_dict(),
            "student": student.to_dict(),
        }, 200
    except Exception as exc:
        db.session.rollback()
        print(f"[FACE] register failed student_id={student_id}: {exc}")
        return {"errors": ["Failed to register face profile"]}, 500


def delete_student_face_embedding(student: Student) -> bool:
    """Remove FaceData row and clear legacy student.face_descriptor. Returns True if something was removed."""
    row = FaceData.query.filter_by(student_id=student.id).first()
    removed = False
    if row:
        db.session.delete(row)
        removed = True
    if student.face_descriptor:
        student.face_descriptor = None
        removed = True
    return removed


def get_student_face(student_id, user):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    student = Student.query.get(student_id)
    denied = _authorize_student(student, user)
    if denied:
        return denied

    row = FaceData.query.filter_by(student_id=student.id).first()
    embedding = row.face_embedding if row else student.face_descriptor
    return {
        "student_id": student.id,
        "registration_no": student.registration_no,
        "full_name": student.user.full_name if student.user else None,
        "has_face": bool(embedding),
        "descriptor": embedding,
        "face_embedding": embedding,
        "updated_at": row.to_dict().get("updated_at") if row else None,
    }, 200


def recognize_face(data, user):
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    embedding = _parse_descriptor(data)
    if not embedding:
        return {"errors": ["embedding descriptor is required (128 numbers)"]}, 400

    try:
        threshold = float(data.get("threshold") or 0.55)
    except (TypeError, ValueError):
        threshold = 0.55
    threshold = max(0.2, min(threshold, 1.2))

    query = Student.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)

    students = query.all()
    candidates = []
    for student in students:
        row = FaceData.query.filter_by(student_id=student.id).first()
        vector = row.face_embedding if row else student.face_descriptor
        if not vector:
            continue
        classroom_name = None
        classroom_id = None
        grade = student.grade
        classrooms = Classroom.query.filter_by(institution_id=student.institution_id).all()
        for classroom in classrooms:
            if classroom.grade and student.grade and classroom.grade == student.grade:
                classroom_name = classroom.name
                classroom_id = classroom.id
                break
        if not classroom_name and classrooms:
            classroom_name = classrooms[0].name
            classroom_id = classrooms[0].id

        candidates.append(
            {
                "student_id": student.id,
                "embedding": vector,
                "registration_no": student.registration_no,
                "full_name": student.user.full_name if student.user else None,
                "grade": grade,
                "classroom_id": classroom_id,
                "classroom_name": classroom_name,
            }
        )

    match = find_best_face_match(embedding, candidates, threshold)
    if not match:
        return {"matched": False, "status": "unknown", "message": "Unknown Student"}, 200

    return {
        "matched": True,
        "status": "recognized",
        "student_id": match["student_id"],
        "registration_no": match.get("registration_no"),
        "full_name": match.get("full_name"),
        "grade": match.get("grade"),
        "classroom_id": match.get("classroom_id"),
        "classroom_name": match.get("classroom_name"),
        "distance": match.get("distance"),
        "confidence": match.get("confidence"),
    }, 200


def list_institution_face_embeddings(user):
    """Return embeddings for client-side caching (same tenant scope as face-profiles)."""
    if user.role not in ("institution_admin", "teacher", "super_admin"):
        return {"errors": ["Access denied"]}, 403

    query = Student.query
    if user.role != "super_admin":
        query = query.filter_by(institution_id=user.institution_id)

    profiles = []
    for student in query.order_by(Student.id.asc()).all():
        row = FaceData.query.filter_by(student_id=student.id).first()
        embedding = row.face_embedding if row else student.face_descriptor
        profiles.append(
            {
                "id": student.id,
                "registration_no": student.registration_no,
                "full_name": student.user.full_name if student.user else None,
                "grade": student.grade,
                "enrolled_subjects": student.get_enrolled_subjects(),
                "enrolledSubjects": student.get_enrolled_subjects(),
                "descriptor": embedding,
                "has_face_descriptor": bool(embedding),
            }
        )
    return {"profiles": profiles}, 200
