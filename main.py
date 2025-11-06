import os
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, EmailStr
from typing import Optional, List
from bson import ObjectId

from database import db, create_document, get_documents
from schemas import User, Course, Enrollment, Progress, Certificate

app = FastAPI(title="GetaiCertified API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def root():
    return {"name": "GetaiCertified API", "status": "ok"}


@app.get("/test")
def test_database():
    response = {
        "backend": "✅ Running",
        "database": "❌ Not Available",
        "database_url": "❌ Not Set",
        "database_name": "❌ Not Set",
        "connection_status": "Not Connected",
        "collections": [],
    }
    try:
        if db is not None:
            response["database"] = "✅ Available"
            response["database_url"] = "✅ Set" if os.getenv("DATABASE_URL") else "❌ Not Set"
            response["database_name"] = db.name if hasattr(db, "name") else "Unknown"
            response["connection_status"] = "Connected"
            try:
                response["collections"] = db.list_collection_names()[:10]
                response["database"] = "✅ Connected & Working"
            except Exception as e:
                response["database"] = f"⚠️ Connected but Error: {str(e)[:60]}"
    except Exception as e:
        response["database"] = f"❌ Error: {str(e)[:60]}"
    return response


# ---------- Auth (minimal) ----------
class SignupRequest(BaseModel):
    name: str
    email: EmailStr


@app.post("/api/auth/signup")
def signup(payload: SignupRequest):
    # If user exists, return existing minimal profile
    existing = db["user"].find_one({"email": payload.email}) if db else None
    if existing:
        return {
            "name": existing.get("name"),
            "email": existing.get("email"),
            "points": existing.get("points", 0),
            "badges": existing.get("badges", []),
            "is_admin": existing.get("is_admin", False),
        }

    user = User(name=payload.name, email=payload.email)
    user_id = create_document("user", user)
    return {"id": user_id, **user.model_dump()}


# ---------- Courses ----------
@app.get("/api/courses", response_model=List[Course])
def list_courses():
    docs = get_documents("course") if db else []
    # Provide default 3-week course if DB empty for demo
    if not docs:
        return [
            Course(
                title="GetaiCertified 3-Week AI Program",
                slug="3-week-ai",
                description="Learn AI fundamentals, master 14+ tools, and ship a capstone.",
                tools=[
                    "ChatGPT",
                    "Midjourney",
                    "Runway",
                    "Notion AI",
                    "Claude",
                    "LangChain",
                ],
            )
        ]
    return [Course(**{k: v for k, v in d.items() if k != "_id"}) for d in docs]


# ---------- Enrollment / Progress ----------
class EnrollRequest(BaseModel):
    email: EmailStr
    course_slug: str


@app.post("/api/enroll")
def enroll(payload: EnrollRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    # upsert enrollment
    db["enrollment"].update_one(
        {"user_email": payload.email, "course_slug": payload.course_slug},
        {"$setOnInsert": {"status": "enrolled"}},
        upsert=True,
    )
    # ensure progress doc
    db["progress"].update_one(
        {"user_email": payload.email, "course_slug": payload.course_slug},
        {"$setOnInsert": {"lessons_completed": [], "week_unlocked": 1, "xp": 0}},
        upsert=True,
    )
    return {"ok": True}


class ProgressUpdate(BaseModel):
    email: EmailStr
    course_slug: str
    lesson_id: str
    xp: int = 10


@app.post("/api/progress/complete")
def complete_lesson(body: ProgressUpdate):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    db["progress"].update_one(
        {"user_email": body.email, "course_slug": body.course_slug},
        {
            "$addToSet": {"lessons_completed": body.lesson_id},
            "$inc": {"xp": body.xp},
        },
        upsert=True,
    )
    # simple weekly unlock rule: every 4 lessons unlock next week
    prog = db["progress"].find_one({"user_email": body.email, "course_slug": body.course_slug})
    lcount = len(prog.get("lessons_completed", [])) if prog else 0
    week_unlocked = min(3, 1 + lcount // 4)
    db["progress"].update_one(
        {"user_email": body.email, "course_slug": body.course_slug},
        {"$set": {"week_unlocked": week_unlocked}},
    )
    return {"ok": True, "week_unlocked": week_unlocked}


@app.get("/api/dashboard")
def dashboard(email: EmailStr, course_slug: str = "3-week-ai"):
    # summarize student dashboard
    user = db["user"].find_one({"email": email}) if db else None
    progress = db["progress"].find_one({"user_email": email, "course_slug": course_slug}) if db else None
    leaderboard = (
        db["progress"].find({}, {"_id": 0, "user_email": 1, "xp": 1}).sort("xp", -1).limit(10)
        if db
        else []
    )
    lb = list(leaderboard) if leaderboard else []
    return {
        "user": {
            "name": (user or {}).get("name", "Learner"),
            "email": email,
            "points": (user or {}).get("points", (progress or {}).get("xp", 0)),
            "badges": (user or {}).get("badges", []),
        },
        "progress": {
            "lessons_completed": (progress or {}).get("lessons_completed", []),
            "week_unlocked": (progress or {}).get("week_unlocked", 1),
            "xp": (progress or {}).get("xp", 0),
        },
        "leaderboard": lb,
    }


# ---------- Certificate (stub) ----------
class CertRequest(BaseModel):
    email: EmailStr
    course_slug: str


@app.post("/api/certificate")
def issue_certificate(body: CertRequest):
    if db is None:
        raise HTTPException(status_code=500, detail="Database not configured")
    cert_id = str(ObjectId())
    db["certificate"].update_one(
        {"user_email": body.email, "course_slug": body.course_slug},
        {"$set": {"certificate_id": cert_id, "verified": True}},
        upsert=True,
    )
    return {"certificate_id": cert_id}


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
