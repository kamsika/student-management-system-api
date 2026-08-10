from datetime import datetime, timedelta
from sqlalchemy.orm import joinedload
from app.extensions import db
from app.models import Institution, InstitutionFeedback
from app.models.institution_feedback_model import RATING_FIELDS

LABELS = {"overall_rating":"Overall Experience","ui_rating":"UI / Design","ease_of_use_rating":"Ease of Use","attendance_rating":"Attendance","payment_rating":"Fee Management / Payment","performance_rating":"Performance","support_rating":"Support"}

def submit(user, data):
    if not user or not user.institution_id: return {"errors":["Authenticated institution is required"]}, 403
    values, errors = {}, []
    for field in RATING_FIELDS:
        try:
            values[field] = int(data.get(field))
            if not 1 <= values[field] <= 5: raise ValueError
        except (ValueError, TypeError): errors.append(f"{field} must be from 1 to 5")
    recommend = data.get("recommend_status")
    if recommend not in ("Yes","Maybe","No"): errors.append("recommend_status must be Yes, Maybe, or No")
    if errors: return {"errors":errors}, 400
    cutoff = datetime.utcnow() - timedelta(seconds=30)
    duplicate = InstitutionFeedback.query.filter_by(institution_id=user.institution_id).filter(InstitutionFeedback.created_at >= cutoff, *[getattr(InstitutionFeedback,k)==v for k,v in values.items()]).first()
    if duplicate: return {"feedback":duplicate.to_dict(),"duplicate":True}, 200
    clean=lambda value: (str(value).strip()[:5000] or None) if value is not None else None
    row=InstitutionFeedback(institution_id=user.institution_id,recommend_status=recommend,improvement_comment=clean(data.get("improvement_comment")),feature_request=clean(data.get("feature_request")),**values)
    try:
        db.session.add(row); db.session.commit()
        return {"feedback":row.to_dict()}, 201
    except Exception:
        db.session.rollback()
        return {"errors":["Failed to submit feedback"]}, 500

def history(user):
    rows=InstitutionFeedback.query.filter_by(institution_id=user.institution_id).order_by(InstitutionFeedback.created_at.desc()).all()
    return {"feedback":[r.to_dict() for r in rows]}, 200

def filtered(args):
    q=InstitutionFeedback.query
    iid=args.get("institution_id",type=int)
    if iid: q=q.filter_by(institution_id=iid)
    try:
        if args.get("start_date"): q=q.filter(InstitutionFeedback.created_at>=datetime.fromisoformat(args["start_date"]))
        if args.get("end_date"): q=q.filter(InstitutionFeedback.created_at<datetime.fromisoformat(args["end_date"])+timedelta(days=1))
    except ValueError: return None
    rating=args.get("rating",type=int)
    if rating: q=q.filter_by(overall_rating=rating)
    issue=args.get("issue")
    issue_fields = {"overall":"overall_rating", "ui":"ui_rating", "ease":"ease_of_use_rating", "attendance":"attendance_rating", "payment":"payment_rating", "performance":"performance_rating", "support":"support_rating"}
    if issue=="low": q=q.filter(InstitutionFeedback.overall_rating<=2)
    elif issue in issue_fields: q=q.filter(getattr(InstitutionFeedback, issue_fields[issue])<=2)
    return q

def analytics(args):
    q=filtered(args)
    if q is None: return {"errors":["Invalid date filter"]},400
    rows=q.options(joinedload(InstitutionFeedback.institution)).all(); n=len(rows)
    avg=lambda field: round(sum(getattr(r,field) for r in rows)/n,2) if n else 0
    satisfied=sum(r.overall_rating>=4 for r in rows); low=sum(r.overall_rating<=2 for r in rows)
    months, institutions, recommendations = {}, {}, {"Yes":0,"Maybe":0,"No":0}
    for r in rows:
        months.setdefault(r.created_at.strftime("%Y-%m"),[]).append(r.overall_rating)
        institutions.setdefault(r.institution.name,[]).append(r.overall_rating); recommendations[r.recommend_status]+=1
    total=Institution.query.count(); responded=len({r.institution_id for r in rows})
    return {"summary":{"total_institutions":total,"institutions_responded":responded,"response_rate":round(100*responded/total,1) if total else 0,"average_overall_rating":avg("overall_rating"),"satisfied_percentage":round(100*satisfied/n,1) if n else 0,"low_rating_count":low},
      "categories":[{"category":LABELS[f],"rating":avg(f)} for f in RATING_FIELDS[1:]],
      "distribution":[{"name":"Satisfied","value":satisfied},{"name":"Neutral","value":sum(r.overall_rating==3 for r in rows)},{"name":"Unsatisfied","value":low}],
      "trend":[{"month":k,"rating":round(sum(v)/len(v),2)} for k,v in sorted(months.items())],
      "institutions":sorted([{"institution":k,"rating":round(sum(v)/len(v),2)} for k,v in institutions.items()],key=lambda x:x["rating"],reverse=True)[:20],
      "recommendations":[{"name":k,"value":v} for k,v in recommendations.items()]},200

def alerts(args):
    q=filtered(args)
    if q is None:return {"errors":["Invalid date filter"]},400
    result=[]
    for r in q.options(joinedload(InstitutionFeedback.institution)).order_by(InstitutionFeedback.created_at.desc()).all():
        for f in RATING_FIELDS:
            if getattr(r,f)<=2: result.append({"feedback_id":r.id,"institution_name":r.institution.name,"category":LABELS[f],"rating":getattr(r,f),"created_at":r.to_dict()["created_at"]})
    return {"alerts":result[:100]},200
