from datetime import datetime, time, timedelta

from app.extensions import db
from app.models import (
    Attendance,
    BillingRecord,
    Classroom,
    Institution,
    SmsLog,
    Student,
    StudyLog,
    User,
)
from app.utils import utc_now

DEMO_SUBDOMAIN = "uki-demo"
DEFAULT_PASSWORD = "Demo@123"


def seed_demo_data(force=False):
    if force:
        _clear_demo_data()

    if Institution.query.filter_by(subdomain=DEMO_SUBDOMAIN).first():
        print("Demo data already exists. Use --force to reseed.")
        return

    institution = Institution(
        name="UKI Demo Tuition Center",
        subdomain=DEMO_SUBDOMAIN,
        status="Active",
    )
    db.session.add(institution)
    db.session.flush()

    admin = _create_user(
        institution.id,
        "admin@uki-demo.com",
        "institution_admin",
        "Institution Admin",
        "+94770000001",
    )
    teacher_one = _create_user(
        institution.id,
        "teacher1@uki-demo.com",
        "teacher",
        "Mr. Rajesh Kumar",
        "+94770000002",
    )
    teacher_two = _create_user(
        institution.id,
        "teacher2@uki-demo.com",
        "teacher",
        "Ms. Priya Nair",
        "+94770000003",
    )

    classroom_math = Classroom(
        institution_id=institution.id,
        name="Mathematics Grade 10",
        schedule_start_time=time(9, 0),
        teacher_id=teacher_one.id,
    )
    classroom_science = Classroom(
        institution_id=institution.id,
        name="Science Grade 10",
        schedule_start_time=time(10, 30),
        teacher_id=teacher_two.id,
    )
    db.session.add_all([classroom_math, classroom_science])

    students_data = [
        {
            "registration_no": "STU-2026-001",
            "full_name": "Kavisan Selvam",
            "email": "kavisan@test.com",
            "contact": "+94771234567",
            "grade": "10",
            "section": "A",
            "gender": "Male",
            "parent_name": "Selvam Arumugam",
            "parent_phone": "+94777123456",
            "parent_email": "selvam@test.com",
        },
        {
            "registration_no": "STU-2026-002",
            "full_name": "Abiraami Balan",
            "email": "abiraami@test.com",
            "contact": "+94772345678",
            "grade": "10",
            "section": "A",
            "gender": "Female",
            "parent_name": "Balan Rajan",
            "parent_phone": "+94777654321",
            "parent_email": "balan@test.com",
        },
        {
            "registration_no": "STU-2026-003",
            "full_name": "Tharun Wickramasinghe",
            "email": "tharun@test.com",
            "contact": "+94773456789",
            "grade": "10",
            "section": "B",
            "gender": "Male",
            "parent_name": "Wickramasinghe Perera",
            "parent_phone": "+94777888999",
            "parent_email": "wickram@test.com",
        },
        {
            "registration_no": "STU-2026-004",
            "full_name": "Nethmi Fernando",
            "email": "nethmi@test.com",
            "contact": "+94774567890",
            "grade": "10",
            "section": "B",
            "gender": "Female",
            "parent_name": "Fernando Silva",
            "parent_phone": "+94777555666",
            "parent_email": "fernando@test.com",
        },
    ]

    student_records = []
    for item in students_data:
        parent = _create_user(
            institution.id,
            item["parent_email"],
            "parent",
            item["parent_name"],
            item["parent_phone"],
        )
        student_user = _create_user(
            institution.id,
            item["email"],
            "student",
            item["full_name"],
            item.get("contact"),
        )
        student = Student(
            institution_id=institution.id,
            user_id=student_user.id,
            parent_id=parent.id,
            registration_no=item["registration_no"],
            grade=item.get("grade"),
            section=item.get("section"),
            gender=item.get("gender"),
        )
        db.session.add(student)
        student_records.append(student)

    db.session.flush()

    period = datetime.utcnow().strftime("%Y-%m")
    billing = BillingRecord(
        institution_id=institution.id,
        billing_period=period,
        saas_flat_fee=5000.00,
        sms_count=2,
        sms_unit_price=2.50,
        total_amount_due=5005.00,
        payment_status="Pending",
    )
    db.session.add(billing)

    db.session.add(
        SmsLog(
            institution_id=institution.id,
            recipient_phone="+94777123456",
            message_body="Dear Parent, your child has arrived late to class by 12 minutes.",
            status="Delivered",
            sent_at=utc_now() - timedelta(days=1),
        )
    )
    db.session.add(
        SmsLog(
            institution_id=institution.id,
            recipient_phone="+94777654321",
            message_body="Dear Parent, your child is recorded as Absent from today's class session.",
            status="Sent",
            sent_at=utc_now() - timedelta(days=2),
        )
    )

    now = utc_now()
    for index, student in enumerate(student_records):
        for day_offset in range(7, 0, -1):
            start = now - timedelta(days=day_offset, hours=index + 2)
            duration = 45 + (index * 10) + (day_offset * 3)
            end = start + timedelta(minutes=duration)
            db.session.add(
                StudyLog(
                    student_id=student.id,
                    start_time=start,
                    end_time=end,
                    duration_minutes=duration,
                )
            )

    db.session.commit()

    print("Demo data seeded successfully.")
    print("")
    print("Institution : UKI Demo Tuition Center")
    print("Subdomain   : uki-demo")
    print("")
    print("Login credentials (password for all: Demo@123)")
    print("  Super Admin        : superadmin@platform.com / SuperAdmin@123")
    print("  Institution Admin  : admin@uki-demo.com")
    print("  Teacher 1          : teacher1@uki-demo.com")
    print("  Teacher 2          : teacher2@uki-demo.com")
    print("  Student 1          : kavisan@test.com")
    print("  Student 2          : abiraami@test.com")
    print("  Parent 1           : selvam@test.com")
    print("  Parent 2           : balan@test.com")


def _create_user(institution_id, email, role, full_name, phone_number):
    user = User(
        institution_id=institution_id,
        email=email,
        role=role,
        full_name=full_name,
        phone_number=phone_number,
        is_active=True,
    )
    user.set_password(DEFAULT_PASSWORD)
    db.session.add(user)
    db.session.flush()
    return user


def _clear_demo_data():
    institution = Institution.query.filter_by(subdomain=DEMO_SUBDOMAIN).first()
    if not institution:
        return

    institution_id = institution.id
    student_ids = [s.id for s in Student.query.filter_by(institution_id=institution_id).all()]

    if student_ids:
        StudyLog.query.filter(StudyLog.student_id.in_(student_ids)).delete(synchronize_session=False)
        Attendance.query.filter(Attendance.student_id.in_(student_ids)).delete(synchronize_session=False)

    Student.query.filter_by(institution_id=institution_id).delete(synchronize_session=False)
    Classroom.query.filter_by(institution_id=institution_id).delete(synchronize_session=False)
    SmsLog.query.filter_by(institution_id=institution_id).delete(synchronize_session=False)
    BillingRecord.query.filter_by(institution_id=institution_id).delete(synchronize_session=False)

    User.query.filter_by(institution_id=institution_id).delete(synchronize_session=False)
    db.session.delete(institution)
    db.session.commit()
    print("Existing demo data cleared.")
