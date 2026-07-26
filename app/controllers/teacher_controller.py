from app.models import Attendance, Classroom, Student, StudentPayment, User
from app.utils import parse_attendance_date, to_iso

STATUS_INDICATORS = {
    "Present": "🟢",
    "Absent": "🔴",
    "Late": "🟡",
}


def get_teacher_attendance_overview(user, date_str=None, classroom_id=None):
    """Return today's (or filtered) attendance overview for a teacher's classrooms."""
    if user.role != "teacher":
        return {"errors": ["Only teachers can access this overview"]}, 403
    if not user.institution_id:
        return {"errors": ["Teacher is not linked to a center"]}, 400

    attendance_date, date_error = parse_attendance_date(date_str)
    if date_error:
        return {"errors": [date_error]}, 400

    classroom_query = Classroom.query.filter_by(
        teacher_id=user.id,
        institution_id=user.institution_id,
    )

    resolved_classroom_id = None
    if classroom_id is not None and str(classroom_id).strip() != "":
        try:
            resolved_classroom_id = int(classroom_id)
        except (TypeError, ValueError):
            return {"errors": ["classroomId must be an integer"]}, 400

        classroom = classroom_query.filter_by(id=resolved_classroom_id).first()
        if not classroom:
            return {"errors": ["Classroom not found"]}, 404
        classrooms = [classroom]
    else:
        classrooms = classroom_query.order_by(Classroom.name.asc(), Classroom.id.asc()).all()
        if not classrooms:
            return {
                "errors": ["No classroom assigned. Ask your center admin to create one."],
            }, 400

    classroom_ids = [classroom.id for classroom in classrooms]
    classroom_by_id = {classroom.id: classroom for classroom in classrooms}

    # Center roster (no per-classroom enrollment table yet).
    students = (
        Student.query.join(User, Student.user_id == User.id)
        .filter(
            Student.institution_id == user.institution_id,
            User.is_active.is_(True),
        )
        .order_by(User.full_name.asc(), Student.registration_no.asc())
        .all()
    )
    payment_period = attendance_date.strftime("%Y-%m")
    payments = StudentPayment.query.filter(
        StudentPayment.student_id.in_([student.id for student in students]),
        StudentPayment.billing_period == payment_period,
    ).all() if students else []
    payment_by_student = {payment.student_id: payment for payment in payments}

    attendance_rows = (
        Attendance.query.filter(
            Attendance.classroom_id.in_(classroom_ids),
            Attendance.date == attendance_date,
        )
        .order_by(Attendance.id.asc())
        .all()
    )

    # Prefer Present/Late over Absent when a student has multiple classroom rows.
    attendance_by_student = {}
    status_rank = {"Present": 3, "Late": 2, "Absent": 1}
    for record in attendance_rows:
        current = attendance_by_student.get(record.student_id)
        if current is None or status_rank.get(record.status, 0) > status_rank.get(current.status, 0):
            attendance_by_student[record.student_id] = record

    present_count = 0
    absent_count = 0
    late_count = 0
    student_list = []

    for student in students:
        record = attendance_by_student.get(student.id)
        status = record.status if record else "Absent"
        if status not in STATUS_INDICATORS:
            status = "Absent"

        if status == "Present":
            present_count += 1
        elif status == "Late":
            late_count += 1
        else:
            absent_count += 1

        classroom = classroom_by_id.get(record.classroom_id) if record else None
        if classroom is None and len(classrooms) == 1:
            classroom = classrooms[0]

        student_list.append(
            {
                "studentId": student.id,
                "fullName": student.user.full_name if student.user else None,
                "registrationNo": student.registration_no,
                "grade": student.grade,
                "section": student.section,
                "status": status,
                "statusIndicator": STATUS_INDICATORS[status],
                "timestamp": to_iso(record.arrival_time) if record else None,
                "classroomId": classroom.id if classroom else None,
                "classroomName": classroom.name if classroom else None,
                "attendanceId": record.id if record else None,
                "monthlyPayment": (
                    payment_by_student[student.id].to_dict()
                    if student.id in payment_by_student
                    else {
                        "billing_period": payment_period,
                        "payment_status": "Pending",
                        "amount_due": None,
                        "paid_at": None,
                    }
                ),
                "monthlyPaymentStatus": payment_by_student[student.id].payment_status
                if student.id in payment_by_student
                else "Pending",
            }
        )

    total_students = len(students)

    return {
        "date": attendance_date.isoformat(),
        "classroomId": resolved_classroom_id,
        "classrooms": [classroom.to_dict() for classroom in classrooms],
        "summary": {
            "totalStudents": total_students,
            "presentCount": present_count,
            "absentCount": absent_count,
            "lateCount": late_count,
        },
        "students": student_list,
    }, 200
