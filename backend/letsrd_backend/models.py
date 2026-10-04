"""Typed state models with JSON-safe serialization."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from enum import Enum
import secrets
from typing import Any, Literal

from pydantic import BaseModel, EmailStr, Field, ConfigDict, model_validator

class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


class AccountTier(str, Enum):
    FREE = "free"
    PREMIUM = "premium"
    STUDENT_PREMIUM = "student_premium"
    PREMIUM_TRIAL = "premium_trial"
    PREMIUM_PAID = "premium_paid"


class Account(BaseModel):
    """API-facing account model compatible with LETSRD's plan limits."""

    model_config = ConfigDict(validate_assignment=True)

    id: str = Field(min_length=1, max_length=120)
    email: EmailStr
    tier: Literal["free", "premium"] = "free"
    max_pages_allowed: int = Field(default=5, ge=1)

    @model_validator(mode="after")
    def apply_tier_page_limit(self) -> "Account":
        object.__setattr__(
            self,
            "max_pages_allowed",
            999_999 if self.tier == AccountTier.PREMIUM.value else 5,
        )
        return self

    def update_tier(self, new_tier: str) -> None:
        if new_tier not in {AccountTier.FREE.value, AccountTier.PREMIUM.value}:
            raise ValueError(f"Unsupported account tier: {new_tier}")
        self.tier = new_tier
        self.max_pages_allowed = 999_999 if new_tier == AccountTier.PREMIUM.value else 5


class MediaGenerationRequest(BaseModel):
    """Validated fields shared by media-generation API clients."""

    ebook_id: str = Field(min_length=1, max_length=200)
    format: Literal["mp3", "mp4"] = "mp3"
    language: str = Field(default="en", min_length=2, max_length=16)
    background_music: bool = False
    # Development-only seam; production must derive this from authenticated account state.
    account_tier_dev_override: Literal[
        "free", "premium", "premium_trial", "premium_paid"
    ] = "free"


class AccessibilityProfile(BaseModel):
    is_blind_mode: bool = False
    is_deaf_mode: bool = False


class UserProfile(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    email: EmailStr
    account_tier: Literal["free", "premium", "student_premium"] = "free"
    is_student_verified: bool = False
    daily_goal_minutes: int = Field(default=30, ge=1, le=1440)
    current_daily_minutes_listened: float = Field(default=0.0, ge=0.0)
    accessibility: AccessibilityProfile = Field(default_factory=AccessibilityProfile)


class TrendingBook(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    author: str = Field(default="Unknown", max_length=300)
    conversion_count: int = Field(default=1, ge=0)


class StudentVerificationToken(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    institutional_email: EmailStr
    token: str
    expires_at: datetime
    is_used: bool = False

    @classmethod
    def generate(
        cls,
        user_id: str,
        email: str,
        now: datetime | None = None,
    ) -> "StudentVerificationToken":
        issued_at = now or datetime.now(timezone.utc)
        return cls(
            user_id=user_id,
            institutional_email=email,
            token=secrets.token_urlsafe(32),
            expires_at=issued_at + timedelta(minutes=15),
        )


@dataclass
class LearnerProfile:
    provider: str
    subject: str
    email: str
    given_name: str
    picture_url: str = ""
    email_verified: bool = False

    def to_json(self) -> dict[str, str]:
        return {
            "provider": self.provider,
            "subject": self.subject,
            "email": self.email,
            "given_name": self.given_name,
            "picture_url": self.picture_url,
            "email_verified": self.email_verified,
        }


@dataclass
class AccountStatus:
    current_tier: AccountTier = AccountTier.FREE
    days_left: int = 0
    verified: bool = False

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AccountStatus":
        tier = AccountTier(str(data.get("current_tier", data.get("tier", "free"))))
        days_left = max(0, min(14, int(data.get("days_left", data.get("trial_days_remaining", 0)))))
        return cls(tier, days_left, bool(data.get("verified", data.get("email_verified", False))))

    def to_json(self) -> dict[str, Any]:
        return {
            "current_tier": self.current_tier.value,
            "days_left": self.days_left,
            "verified": self.verified,
        }

    @property
    def is_premium(self) -> bool:
        return self.current_tier in {
            AccountTier.PREMIUM,
            AccountTier.STUDENT_PREMIUM,
            AccountTier.PREMIUM_TRIAL,
            AccountTier.PREMIUM_PAID,
        }

    def activate_paid(self) -> None:
        self.current_tier = AccountTier.PREMIUM_PAID
        self.days_left = 0

    def start_trial(self) -> None:
        if self.current_tier == AccountTier.FREE:
            self.current_tier = AccountTier.PREMIUM_TRIAL
            self.days_left = 14


@dataclass(frozen=True)
class Ebook:
    book_id: int | str
    title: str
    author: str
    genre: str
    raw_text_source_url: str

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.book_id,
            "title": self.title,
            "author": self.author,
            "genre": self.genre,
            "download_url": self.raw_text_source_url,
        }


@dataclass(frozen=True)
class VideoScene:
    scene_number: int
    visual_prompt: str
    narration_text: str


@dataclass
class VideoBlueprint:
    generation_triggered: bool = False
    analogy_concept: str = ""
    video_scenes: list[VideoScene] = field(default_factory=list)

    def to_json(self) -> dict[str, Any]:
        return {
            "generation_triggered": self.generation_triggered,
            "analogy_concept": self.analogy_concept,
            "video_scenes": [asdict(scene) for scene in self.video_scenes],
        }


@dataclass
class AppState:
    theme: ThemeMode = ThemeMode.LIGHT
    account: AccountStatus = field(default_factory=AccountStatus)
    reading_position: dict[str, int] = field(default_factory=dict)
    selected_book_id: int | str | None = None
    learner_profile: LearnerProfile | None = None

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "AppState":
        theme = ThemeMode(str(data.get("theme", ThemeMode.LIGHT.value)))
        account = AccountStatus.from_json(data.get("account", data.get("account_status", {})))
        positions = {
            str(book_id): max(0, int(position))
            for book_id, position in data.get("reading_position", {}).items()
        }
        profile_data = data.get("learner_profile")
        profile = LearnerProfile(**profile_data) if profile_data else None
        return cls(theme, account, positions, data.get("selected_book_id"), profile)

    def to_json(self) -> dict[str, Any]:
        return {
            "theme": self.theme.value,
            "account": self.account.to_json(),
            "reading_position": dict(self.reading_position),
            "selected_book_id": self.selected_book_id,
            "learner_profile": self.learner_profile.to_json() if self.learner_profile else None,
        }

    def toggle_theme(self) -> None:
        self.theme = ThemeMode.DARK if self.theme == ThemeMode.LIGHT else ThemeMode.LIGHT
