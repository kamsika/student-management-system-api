from app.extensions import db
from app.models import Classroom, User


def list_classrooms(user):
    query = Classroom.query

    if user.role == "teacher":
        query = query.filter_by(teacher_id=user.id, institution_id=user.institution_id)
    elif user.role == "institution_admin":
        query = query.filter_by(institution_id=user.institution_id)
    elif user.role == "super_admin":
        pass
    else:
        return {"errors": ["Access denied"]}, 403

    classrooms = query.order_by(Classroom.name).all()
    return {"classrooms": [c.to_dict() for c in classrooms]}, 200


def create_classroom(data, user):
    name = (data.get("name") or "").strip()
    schedule_start_time = data.get("schedule_start_time")
    teacher_id = data.get("teacher_id")

    if not name or not schedule_start_time or not teacher_id:
        return {"errors": ["Name, schedule_start_time, and teacher_id are required"]}, 400

    teacher = User.query.filter_by(id=teacher_id, institution_id=user.institution_id, role="teacher").first()
    if not teacher:
        return {"errors": ["Teacher not found in institution"]}, 404

    try:
        from datetime import datetime as dt
        parsed_time = dt.strptime(schedule_start_time, "%H:%M").time() if len(schedule_start_time) == 5 else dt.strptime(schedule_start_time, "%H:%M:%S").time()

        classroom = Classroom(
            institution_id=user.institution_id,
            name=name,
            schedule_start_time=parsed_time,
            teacher_id=teacher_id,
        )
        db.session.add(classroom)
        db.session.commit()
        return {"classroom": classroom.to_dict()}, 201
    except ValueError:
        return {"errors": ["Invalid schedule_start_time format. Use HH:MM"]}, 400
    except Exception:
        db.session.rollback()
        return {"errors": ["Failed to create classroom"]}, 500
