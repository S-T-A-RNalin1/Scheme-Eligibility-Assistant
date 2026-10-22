"""Pydantic request models: the first validation layer (the DB validators are the last)."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from .engine.attributes import BY_KEY, EDUCATION, OCCUPATIONS, STATES


class Profile(BaseModel):
    model_config = ConfigDict(extra="forbid")  # unknown attributes are rejected

    age: float | None = Field(None, ge=0, le=120)
    gender: Literal["male", "female", "transgender"] | None = None
    state: str | None = None
    area_type: Literal["rural", "urban"] | None = None
    category: Literal["General", "OBC", "SC", "ST", "EWS"] | None = None
    annual_income: float | None = Field(None, ge=0, le=1e10)
    occupation: str | None = None
    is_student: bool | None = None
    education_level: str | None = None
    marks_percent: float | None = Field(None, ge=0, le=100)
    land_holding_hectares: float | None = Field(None, ge=0, le=10000)
    is_bpl: bool | None = None
    has_disability: bool | None = None
    disability_percent: float | None = Field(None, ge=0, le=100)
    is_income_tax_payer: bool | None = None
    is_citizen: bool | None = None
    marital_status: Literal["unmarried", "married", "widowed", "divorced"] | None = None
    is_minority: bool | None = None

    @field_validator("state")
    @classmethod
    def _state(cls, v):
        if v is not None and v not in STATES:
            raise ValueError("unknown state / UT")
        return v

    @field_validator("occupation")
    @classmethod
    def _occ(cls, v):
        if v is not None and v not in OCCUPATIONS:
            raise ValueError(f"occupation must be one of {OCCUPATIONS}")
        return v

    @field_validator("education_level")
    @classmethod
    def _edu(cls, v):
        if v is not None and v not in EDUCATION:
            raise ValueError(f"education_level must be one of {EDUCATION}")
        return v

    def clean(self) -> dict:
        return {k: v for k, v in self.model_dump().items() if v is not None and k in BY_KEY}


class CheckIn(BaseModel):
    profile: Profile | None = None
    use_saved_profile: bool = False


class RegisterIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    name: str = Field(default="", max_length=80)


class LoginIn(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=128)
    # Which login the person used: the citizen tab or the admin tab. The account's role must match.
    as_role: Literal["citizen", "admin"] | None = None


class ProfileIn(BaseModel):
    attributes: Profile
    consent: bool = Field(description="User agrees to store the profile")


class ChatIn(BaseModel):
    question: str = Field(min_length=3, max_length=500)
    profile: Profile | None = None
    stream: bool = True


class ApproveIn(BaseModel):
    eligibility: dict | None = None  # edited tree; omitted = approve the proposal as-is
    change_note: str = Field(default="Approved from review queue", max_length=300)


GRIEVANCE_CATEGORIES = Literal["eligibility_result", "application_status", "documents", "benefit_not_received",
                               "wrong_information", "portal_issue", "other"]


class GrievanceIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scheme_slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9()\-]+$")
    category: GRIEVANCE_CATEGORIES
    subject: str = Field(min_length=5, max_length=120)
    description: str = Field(min_length=20, max_length=3000)
    run_id: str | None = Field(default=None, max_length=40, pattern=r"^run_[0-9a-f]+$")


class GrievanceCommentIn(BaseModel):
    note: str = Field(min_length=2, max_length=2000)
    reopen: bool = False


class GrievanceStatusIn(BaseModel):
    status: Literal["open", "in_progress", "resolved", "closed"]
    note: str = Field(min_length=2, max_length=2000)
    priority: Literal["low", "normal", "high"] | None = None


class TrackSaveIn(BaseModel):
    scheme_slug: str = Field(min_length=1, max_length=80, pattern=r"^[a-z0-9()\-]+$")


class TrackUpdateIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: Literal["not_started", "applied", "approved", "rejected"] | None = None
    deadline: str | None = Field(default=None, pattern=r"^(\d{4}-\d{2}-\d{2})?$")  # "" clears it
    reminder_days: int | None = Field(default=None, ge=0, le=60)
    notes: str | None = Field(default=None, max_length=2000)
    note: str = Field(default="", max_length=300)  # optional note stored with a status change


class DocAddIn(BaseModel):
    name: str = Field(min_length=2, max_length=160)


class DocDoneIn(BaseModel):
    done: bool


class RecommendIn(BaseModel):
    profile: Profile | None = None
    use_saved_profile: bool = False
