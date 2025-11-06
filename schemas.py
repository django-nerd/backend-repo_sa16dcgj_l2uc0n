"""
Database Schemas for GetaiCertified

Each Pydantic model corresponds to a MongoDB collection (lowercased class name).
"""
from typing import List, Optional
from pydantic import BaseModel, Field, EmailStr
from datetime import datetime


class User(BaseModel):
    name: str = Field(..., description="Full name")
    email: EmailStr = Field(..., description="Email address")
    avatar_url: Optional[str] = Field(None, description="Profile image URL")
    referred_by: Optional[str] = Field(None, description="Referral code of the inviter")
    referral_code: Optional[str] = Field(None, description="User's unique referral code")
    points: int = Field(0, description="Gamified XP points")
    badges: List[str] = Field(default_factory=list, description="List of earned badges")
    is_admin: bool = Field(False, description="Admin access flag")


class Course(BaseModel):
    title: str
    slug: str
    description: Optional[str] = None
    weeks: int = Field(3, description="Number of weeks in the course")
    tools: List[str] = Field(default_factory=list)
    is_active: bool = True


class Lesson(BaseModel):
    course_slug: str
    week: int
    title: str
    content: Optional[str] = None
    video_url: Optional[str] = None
    quiz: Optional[dict] = None  # { questions: [{q, options, answer}], passing_score }


class Enrollment(BaseModel):
    user_email: EmailStr
    course_slug: str
    status: str = Field("enrolled", description="enrolled|completed|cancelled")
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None


class Progress(BaseModel):
    user_email: EmailStr
    course_slug: str
    lessons_completed: List[str] = Field(default_factory=list)
    week_unlocked: int = 1
    xp: int = 0


class Certificate(BaseModel):
    user_email: EmailStr
    course_slug: str
    certificate_id: str
    pdf_url: Optional[str] = None
    verified: bool = False


class Referral(BaseModel):
    code: str
    owner_email: EmailStr
    redemptions: int = 0
