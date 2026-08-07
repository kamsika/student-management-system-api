from types import SimpleNamespace

from app.controllers import face_controller, teacher_controller


def _user(role, institution_id=1, user_id=10):
    return SimpleNamespace(id=user_id, role=role, institution_id=institution_id)


def _student(institution_id=1, grade="Grade 10"):
    return SimpleNamespace(id=20, institution_id=institution_id, grade=grade)


def test_institution_admin_can_manage_same_institution_student():
    assert teacher_controller._teacher_can_manage_student_face(
        _student(), _user("institution_admin")
    )


def test_institution_admin_cannot_manage_cross_institution_student():
    assert not teacher_controller._teacher_can_manage_student_face(
        _student(institution_id=2), _user("institution_admin")
    )


def test_teacher_assignment_restriction_is_preserved(monkeypatch):
    assigned_class = SimpleNamespace(grade="Grade 9")
    monkeypatch.setattr(
        teacher_controller,
        "_teacher_assigned_classroom_ids",
        lambda _user: [assigned_class],
    )

    teacher = _user("teacher")
    assert teacher_controller._teacher_can_manage_student_face(
        _student(grade="Grade 9"), teacher
    )
    assert not teacher_controller._teacher_can_manage_student_face(
        _student(grade="Grade 10"), teacher
    )


def test_generic_face_authorization_applies_teacher_assignment(monkeypatch):
    monkeypatch.setattr(
        "app.controllers.student_controller._authorize_student_access",
        lambda _student, _user: None,
    )
    monkeypatch.setattr(
        teacher_controller,
        "_teacher_can_manage_student_face",
        lambda _student, _user: False,
    )

    result = face_controller._authorize_student(_student(), _user("teacher"))

    assert result == (
        {"errors": ["Access denied — student is outside your institution or assigned classes"]},
        403,
    )
