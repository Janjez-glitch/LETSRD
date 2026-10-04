# Lines 1 to 6 can be your standard green description notes:
"""Shared HTTP API for translation and structured note taking.

Run locally with:
    uvicorn api:app --reload
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import sqlite3
import tempfile
from contextlib import closing
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Literal
from urllib.parse import urlencode, urlsplit

from fastapi import FastAPI, HTTPException, Query, File, Form, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, EmailStr, Field, ValidationError

from config import GEMINI_MODEL, OPENAI_API_KEY, MODEL, get_google_api_key
from letsrd_backend.educational_pipeline import (
    InvalidPdfError,
    PipelineError,
    PlanLimitError,
    ProviderError,
    VISUAL_STYLE_INSTRUCTIONS,
    GeminiImageGenerator,
)
from letsrd_backend.engine import MediaGeneratorEngine
from letsrd_backend.models import (
    AccountStatus,
    MediaGenerationRequest,
    StudentVerificationToken,
    TrendingBook,
    UserProfile,
)
from letsrd_backend.parsers import MAX_INPUT_BYTES
from letsrd_backend.search import FreeEbookSearch
from letsrd_backend.services import (
    FlashcardService,
    IntegrationError,
    SandboxTranslationService,
    SmtpVerificationMailer,
)
from letsrd_backend.telegram_webhook import router as telegram_router


app = FastAPI(title="LETSRD Language AI", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
USAGE_DATABASE = Path("letsrd_usage.sqlite3")
_AUDIO_DIRECTORY = Path("letsrd_audio")
_PAYMENT_ACCOUNTS: dict[str, AccountStatus] = {}
ACADEMIC_EMAIL_SUFFIXES = (".edu", ".ac.uk", ".edu.ke", ".edu.co")
app.include_router(telegram_router)


def _stage_pdf_upload(source: BinaryIO) -> Path:
    """Copy FastAPI's spooled upload to disk without loading the whole PDF."""
    upload_dir = Path("letsrd_generated") / ".uploads"
    upload_dir.mkdir(parents=True, exist_ok=True)
    staged_path: Path | None = None
    try:
        source.seek(0)
        with tempfile.NamedTemporaryFile(
            mode="wb", suffix=".pdf", prefix="upload-", dir=upload_dir, delete=False
        ) as staged:
            staged_path = Path(staged.name)
            total = 0
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > MAX_INPUT_BYTES:
                    raise HTTPException(
                        status_code=413,
                        detail="PDF uploads are limited to 24 MiB.",
                    )
                staged.write(chunk)
    except Exception:
        if staged_path is not None:
            staged_path.unlink(missing_ok=True)
        raise
    if staged_path is None:
        raise RuntimeError("PDF upload could not be staged.")
    return staged_path


def _student_verification_base_url() -> str:
    value = os.getenv("LETSRD_PUBLIC_BASE_URL", "http://127.0.0.1:8000").strip()
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        raise HTTPException(
            status_code=500,
            detail="LETSRD_PUBLIC_BASE_URL must be a valid HTTP(S) URL.",
        ) from exc
    is_production = os.getenv("LETSRD_ENV", "development").casefold() == "production"
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.netloc
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or (is_production and parsed.scheme != "https")
    ):
        raise HTTPException(
            status_code=500,
            detail="LETSRD_PUBLIC_BASE_URL must be a valid public HTTPS URL in production.",
        )
    return value.rstrip("/")


class TransformRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    target_language: str = Field(default="English", min_length=1, max_length=80)
    source_language: str = Field(default="auto", min_length=1, max_length=80)
    output_format: Literal["translation", "notes", "letter", "report"] = "translation"
    user_id: str = Field(default="anonymous", min_length=1, max_length=120)
    duration_minutes: int = Field(default=1, ge=1, le=60)


class TransformResponse(BaseModel):
    result: str
    detected_language: str | None = None
    output_format: str
    remaining_free_minutes: int | None = None


class NarrationRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    language: str = Field(default="en", min_length=2, max_length=8)


class FlashcardRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    limit: int = Field(default=20, ge=1, le=50)


class Flashcard(BaseModel):
    id: int
    question: str
    answer: str


class FlashcardResponse(BaseModel):
    flashcards: list[Flashcard]


class VideoBlueprintRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    language: str = Field(default="English", min_length=1, max_length=80)
    subject_and_cast: str = Field(
        default=(
            "Maya, a 20-year-old student with warm brown skin, short natural black "
            "hair, round glasses, a teal cardigan, white shirt, and dark trousers. "
            "Keep her age, face, hair, clothing, and proportions identical in every scene."
        ),
        min_length=1,
        max_length=1_000,
    )
    action_guidance: str = Field(
        default=(
            "Give each scene exactly one simple physical movement with a clearly "
            "described starting position and ending position."
        ),
        min_length=1,
        max_length=1_000,
    )
    camera_movement: str = Field(
        default="One stable medium shot with a gentle, smooth push-in; no cuts or shake.",
        min_length=1,
        max_length=500,
    )
    lighting_environment: str = Field(
        default=(
            "A single warm desk-lamp source in a quiet study room at evening; "
            "calm, focused mood."
        ),
        min_length=1,
        max_length=1_000,
    )
    constraints_negative_prompt: str = Field(
        default=(
            "Clean rendering, no garbled text, no floating artifacts, consistent "
            "anatomy, smooth motion, no extra limbs."
        ),
        min_length=1,
        max_length=1_000,
    )


class VideoBlueprintResponse(BaseModel):
    analogy_concept: str
    video_scenes: list[dict[str, str | int]]
    provider: str


class EducationalSlideshowScene(BaseModel):
    heading: str
    narration: str
    visual_prompt: str
    image_url: str
    recall_question: str | None = None
    recall_choices: list[str] | None = None
    recall_answer_index: int | None = Field(default=None, ge=0, le=2)


class EducationalSlideshowResponse(BaseModel):
    job_id: str
    title: str
    summary: str
    audio_url: str
    scenes: list[EducationalSlideshowScene]


class EducationalTextSlideshowRequest(BaseModel):
    text: str = Field(min_length=1, max_length=50_000)
    language: str = Field(default="en", min_length=2, max_length=8)
    account_tier: Literal["free", "premium"] = "free"
    visual_style: Literal["whiteboard", "cinematic", "infographic"] = "whiteboard"


class IllustrationStyleRequest(BaseModel):
    visual_style: Literal["whiteboard", "cinematic", "infographic"]


class IllustrationStyleResponse(BaseModel):
    image_url: str


class LearningStyleResultRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    visual_style: Literal["whiteboard", "cinematic", "infographic"]
    correct: int = Field(ge=0, le=50)
    total: int = Field(ge=1, le=50)


class LearningStylePerformance(BaseModel):
    correct: int
    total: int


class LearningStyleRecommendations(BaseModel):
    styles: dict[str, LearningStylePerformance]
    recommended_style: Literal["whiteboard", "cinematic", "infographic"] | None


class ProfileRequest(BaseModel):
    user_id: str = Field(min_length=1, max_length=120)
    given_name: str = Field(min_length=1, max_length=80)
    email: str = Field(min_length=3, max_length=254)
    subject: str = Field(default="General learning", max_length=120)


class ProfileResponse(BaseModel):
    user_id: str
    given_name: str
    email: str
    subject: str


class MpesaCallbackResponse(BaseModel):
    acknowledged: bool
    successful: bool
    result_code: int
    message: str
    receipt: str | None = None
    account_tier: str | None = None


@app.post("/v1/educational/pdf")
@app.post("/api/v1/media/generate")
async def educational_pdf(
    file: UploadFile = File(...),
    user_id: str = Form("anonymous"),
    language: str = Form("en"),
    output_format: Literal["mp3", "mp4"] = Form("mp3"),
    account_tier: str = Form("free"),
    background_music: UploadFile | None = File(None),
    ebook_id: str | None = Form(None),
    format: Literal["mp3", "mp4"] | None = Form(None),
    account_tier_dev_override: str | None = Form(None),
    background_music_enabled: bool = Form(False),
    is_blind_mode: bool = Form(False),
    is_deaf_mode: bool = Form(False),
    book_title: str | None = Form(None, max_length=300),
    book_author: str | None = Form(None, max_length=300),
) -> FileResponse:
    """Turn a PDF into localized MP3, or Premium-only synced MP4 slides.

    ``account_tier`` is retained for the existing route; the alias route accepts
    ``account_tier_dev_override``. Production integrations must load the tier
    from authenticated, server-side account state.
    """
    if (
        file.content_type not in {"application/pdf", "application/octet-stream"}
        or Path(file.filename or "").suffix.casefold() != ".pdf"
    ):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    staged_pdf: Path | None = None
    try:
        request = MediaGenerationRequest(
            ebook_id=ebook_id or file.filename or "uploaded-pdf",
            format=format or output_format,
            language=language,
            background_music=background_music_enabled or background_music is not None,
            account_tier_dev_override=account_tier_dev_override or account_tier,
        )
        if background_music_enabled and background_music is None:
            raise HTTPException(
                status_code=422,
                detail="Upload a background_music file when background_music_enabled is true.",
            )
        account = AccountStatus.from_json(
            {"current_tier": request.account_tier_dev_override}
        )
        engine = MediaGeneratorEngine(api_key=get_google_api_key())

        engine.validate_tier_limits(
            account.current_tier.value,
            0,
            request.format,
            request.language.casefold().replace("_", "-"),
            request.background_music,
        )
        staged_pdf = await asyncio.to_thread(_stage_pdf_upload, file.file)
        music = (
            await background_music.read()
            if request.background_music and background_music
            else None
        )
        path = await asyncio.to_thread(
            engine.generate_from_pdf,
            staged_pdf,
            account.current_tier.value,
            request.language,
            request.format,
            music,
            {
                "is_blind_mode": is_blind_mode,
                "is_deaf_mode": is_deaf_mode,
            },
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except PlanLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (PipelineError, ProviderError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if staged_pdf is not None:
            staged_pdf.unlink(missing_ok=True)
    _track_conversion_metric(
        (book_title or request.ebook_id).strip(),
        (book_author or "Unknown").strip(),
    )
    media = "video/mp4" if request.format == "mp4" else "audio/mpeg"
    safe_ebook_id = re.sub(r"[^A-Za-z0-9._-]", "_", request.ebook_id)[:100]
    extension = ".mp4" if request.format == "mp4" else ".mp3"
    return FileResponse(
        path,
        media_type=media,
        filename=f"{safe_ebook_id}{extension}",
    )


@app.post(
    "/v1/educational/slideshow",
    response_model=EducationalSlideshowResponse,
)
async def educational_slideshow(
    file: UploadFile = File(...),
    language: str = Form("en"),
    account_tier: str = Form("free"),
    visual_style: Literal["whiteboard", "cinematic", "infographic"] = Form("whiteboard"),
) -> EducationalSlideshowResponse:
    """Create source-grounded slide text, per-scene images, and a narration track."""
    if (
        file.content_type not in {"application/pdf", "application/octet-stream"}
        or Path(file.filename or "").suffix.casefold() != ".pdf"
    ):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")
    staged_pdf: Path | None = None
    try:
        staged_pdf = await asyncio.to_thread(_stage_pdf_upload, file.file)
        engine = MediaGeneratorEngine(api_key=get_google_api_key())
        result = await asyncio.to_thread(
            engine.generate_slideshow_from_pdf,
            staged_pdf,
            account_tier,
            language,
            visual_style,
        )
    except HTTPException:
        raise
    except PlanLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except InvalidPdfError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except (PipelineError, ProviderError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    finally:
        if staged_pdf is not None:
            staged_pdf.unlink(missing_ok=True)

    return _educational_slideshow_response(result)


@app.post(
    "/v1/educational/slideshow/text",
    response_model=EducationalSlideshowResponse,
)
async def educational_text_slideshow(
    request: EducationalTextSlideshowRequest,
) -> EducationalSlideshowResponse:
    """Create source-grounded scenes, illustrations, and narration from pasted text."""
    try:
        engine = MediaGeneratorEngine(api_key=get_google_api_key())
        result = await asyncio.to_thread(
            engine.generate_slideshow_from_text,
            request.text,
            request.account_tier,
            request.language,
            request.visual_style,
        )
    except PlanLimitError as exc:
        raise HTTPException(status_code=403, detail=str(exc)) from exc
    except (PipelineError, ProviderError) as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return _educational_slideshow_response(result)


def _educational_slideshow_response(
    result: dict[str, Any],
) -> EducationalSlideshowResponse:
    job_id = result["job_id"]
    return EducationalSlideshowResponse(
        job_id=job_id,
        title=result["title"],
        summary=result["summary"],
        audio_url=f"/v1/educational/slideshows/{job_id}/assets/narration.mp3",
        scenes=[
            EducationalSlideshowScene(
                heading=scene["heading"],
                narration=scene["narration"],
                visual_prompt=scene["visual_prompt"],
                recall_question=scene.get("recall_question"),
                recall_choices=scene.get("recall_choices"),
                recall_answer_index=scene.get("recall_answer_index"),
                image_url=(
                    f"/v1/educational/slideshows/{job_id}/assets/"
                    f"{scene['image_filename']}"
                ),
            )
            for scene in result["scenes"]
        ],
    )


@app.get("/v1/educational/slideshows/{job_id}/assets/{asset_name}")
def educational_slideshow_asset(job_id: str, asset_name: str) -> FileResponse:
    """Serve only known generated assets for a valid slideshow job."""
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not re.fullmatch(
        r"(?:scene-\d{2}(?:-(?:cinematic|infographic|whiteboard))?\.(?:png|jpg|webp)|narration\.mp3)",
        asset_name,
    ):
        raise HTTPException(status_code=404, detail="Slideshow asset not found.")
    path = Path("letsrd_generated") / "slideshows" / job_id / asset_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Slideshow asset not found.")
    media_type = "audio/mpeg" if asset_name == "narration.mp3" else {
        ".png": "image/png",
        ".jpg": "image/jpeg",
        ".webp": "image/webp",
    }[path.suffix]
    return FileResponse(path, media_type=media_type)


@app.post(
    "/v1/educational/slideshows/{job_id}/scenes/{scene_index}/style",
    response_model=IllustrationStyleResponse,
)
async def restyle_slideshow_scene(
    job_id: str,
    scene_index: int,
    request: IllustrationStyleRequest,
) -> IllustrationStyleResponse:
    if not re.fullmatch(r"[0-9a-f]{32}", job_id) or not 1 <= scene_index <= 10:
        raise HTTPException(status_code=404, detail="Slideshow scene not found.")
    job_dir = Path("letsrd_generated") / "slideshows" / job_id
    prompts_path = job_dir / "scene-prompts.json"
    if not prompts_path.is_file():
        raise HTTPException(status_code=404, detail="Slideshow scene not found.")
    try:
        prompts = json.loads(prompts_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=500, detail="Slideshow scene metadata could not be read."
        ) from exc
    if (
        not isinstance(prompts, list)
        or scene_index > len(prompts)
        or not isinstance(prompts[scene_index - 1], str)
    ):
        raise HTTPException(status_code=404, detail="Slideshow scene not found.")

    style = request.visual_style
    image_name = f"scene-{scene_index:02}-{style}.png"
    image_path = job_dir / image_name
    if not image_path.is_file():
        try:
            image_generator = GeminiImageGenerator(get_google_api_key())
            await asyncio.to_thread(
                image_generator.generate,
                f"{prompts[scene_index - 1]}\n\n{VISUAL_STYLE_INSTRUCTIONS[style]}",
                image_path,
            )
        except ProviderError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
    return IllustrationStyleResponse(
        image_url=(
            f"/v1/educational/slideshows/{job_id}/assets/{image_name}"
        )
    )


@app.get("/v1/ebooks/search")
@app.get("/api/v1/ebooks/search")
async def search_free_ebooks(
    query: str = Query(..., min_length=1, max_length=200),
    limit: int = Query(10, ge=1, le=50),
) -> dict[str, object]:
    try:
        results = await FreeEbookSearch().search(query, limit)
    except ProviderError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"query": query, "count": len(results), "results": results}


@app.post("/api/v1/billing/verify-student")
async def verify_student_tier(
    user_id: str = Query(..., min_length=1, max_length=120),
    institutional_email: EmailStr = Query(...),
) -> dict[str, str | bool]:
    """Send an expiring verification link to an eligible academic email."""
    domain = str(institutional_email).rsplit("@", 1)[-1].casefold().rstrip(".")
    is_academic = any(
        domain.endswith(suffix) and domain != suffix.lstrip(".")
        for suffix in ACADEMIC_EMAIL_SUFFIXES
    )
    if not is_academic:
        raise HTTPException(
            status_code=400,
            detail="Provided email does not belong to a recognized academic email domain.",
        )
    base_url = _student_verification_base_url()
    token_record = StudentVerificationToken.generate(user_id, str(institutional_email))
    token_hash = hashlib.sha256(token_record.token.encode("utf-8")).hexdigest()
    _ensure_student_tables()
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            "DELETE FROM student_verification_tokens WHERE user_id = ?",
            (user_id,),
        )
        connection.execute(
            """
            INSERT INTO student_verification_tokens
                (token_hash, user_id, institutional_email, expires_at, is_used)
            VALUES (?, ?, ?, ?, 0)
            """,
            (
                token_hash,
                user_id,
                str(token_record.institutional_email),
                token_record.expires_at.isoformat(),
            ),
        )
        connection.commit()

    confirmation_url = (
        f"{base_url}/api/v1/billing/confirm-student?"
        f"{urlencode({'token': token_record.token})}"
    )
    try:
        mailer = SmtpVerificationMailer.from_environment()
        await asyncio.to_thread(
            mailer.send_student_verification_link,
            str(token_record.institutional_email),
            confirmation_url,
        )
    except (IntegrationError, OSError) as exc:
        with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
            connection.execute(
                "DELETE FROM student_verification_tokens WHERE token_hash = ?",
                (token_hash,),
            )
            connection.commit()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "status": "pending_verification",
        "user_id": user_id,
        "message": (
            "A student verification link was sent to the academic email address. "
            "The link expires in 15 minutes."
        ),
        "provisional_tier": "student_premium",
        "is_student_verified": False,
    }


@app.get("/api/v1/billing/confirm-student")
async def confirm_student_tier(
    token: str = Query(..., min_length=32, max_length=128),
) -> dict[str, str]:
    """Consume a valid verification token and persist the student account tier."""
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    now = datetime.now(timezone.utc)
    _ensure_student_tables()
    with closing(sqlite3.connect(USAGE_DATABASE, timeout=10)) as connection:
        connection.execute("BEGIN IMMEDIATE")
        record = connection.execute(
            """
            SELECT user_id, institutional_email, expires_at, is_used
            FROM student_verification_tokens
            WHERE token_hash = ?
            """,
            (token_hash,),
        ).fetchone()
        if record is None or record[3]:
            connection.rollback()
            raise HTTPException(
                status_code=400,
                detail="Invalid, missing, or previously consumed verification link.",
            )
        expires_at = datetime.fromisoformat(record[2])
        if expires_at.tzinfo is None:
            expires_at = expires_at.replace(tzinfo=timezone.utc)
        if now >= expires_at:
            connection.execute(
                "UPDATE student_verification_tokens SET is_used = 1 WHERE token_hash = ?",
                (token_hash,),
            )
            connection.commit()
            raise HTTPException(
                status_code=400,
                detail="Verification link has expired. Please request a new link.",
            )
        profile = UserProfile(
            user_id=record[0],
            email=record[1],
            account_tier="student_premium",
            is_student_verified=True,
        )
        connection.execute(
            "UPDATE student_verification_tokens SET is_used = 1 WHERE token_hash = ?",
            (token_hash,),
        )
        connection.execute(
            """
            INSERT INTO student_profiles (user_id, email, account_tier, is_student_verified)
            VALUES (?, ?, 'student_premium', 1)
            ON CONFLICT(user_id) DO UPDATE SET
                email = excluded.email,
                account_tier = 'student_premium',
                is_student_verified = 1
            """,
            (
                profile.user_id,
                str(profile.email),
            ),
        )
        connection.commit()
    return {
        "status": "success",
        "message": "Student email verified and Student Premium activated.",
    }


@app.get("/studio", response_class=HTMLResponse, include_in_schema=False)
def ebook_media_studio() -> FileResponse:
    studio_path = Path(__file__).parent / "letsrd_backend" / "static" / "index.html"
    return FileResponse(studio_path, media_type="text/html")


def _ensure_usage_table() -> None:
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS note_usage (
                user_id TEXT NOT NULL,
                usage_date TEXT NOT NULL,
                minutes INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, usage_date)
            )
            """
        )
        connection.commit()


def _ensure_student_tables() -> None:
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS student_verification_tokens (
                token_hash TEXT PRIMARY KEY,
                user_id TEXT NOT NULL,
                institutional_email TEXT NOT NULL,
                expires_at TEXT NOT NULL,
                is_used INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS student_profiles (
                user_id TEXT PRIMARY KEY,
                email TEXT NOT NULL,
                account_tier TEXT NOT NULL,
                is_student_verified INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.execute(
            "CREATE INDEX IF NOT EXISTS idx_student_tokens_user_id "
            "ON student_verification_tokens(user_id)"
        )
        connection.commit()


def _ensure_trending_table() -> None:
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS trending_books (
                normalized_key TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                author TEXT NOT NULL,
                conversion_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        connection.commit()


def _track_conversion_metric(title: str, author: str) -> None:
    normalized_title = " ".join(title.split()) or "Unknown title"
    normalized_author = " ".join(author.split()) or "Unknown"
    normalized_key = (
        f"{normalized_title.casefold()}_{normalized_author.casefold()}"
    )
    _ensure_trending_table()
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            """
            INSERT INTO trending_books
                (normalized_key, title, author, conversion_count)
            VALUES (?, ?, ?, 1)
            ON CONFLICT(normalized_key) DO UPDATE SET
                conversion_count = trending_books.conversion_count + 1
            """,
            (normalized_key, normalized_title, normalized_author),
        )
        connection.commit()


@app.get("/api/v1/analytics/trending")
def get_trending_catalog() -> dict[str, list[dict[str, str | int]]]:
    _ensure_trending_table()
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        rows = connection.execute(
            """
            SELECT title, author, conversion_count
            FROM trending_books
            ORDER BY conversion_count DESC, title COLLATE NOCASE ASC,
                     author COLLATE NOCASE ASC
            LIMIT 5
            """
        ).fetchall()
    books = [
        TrendingBook(title=row[0], author=row[1], conversion_count=row[2]).model_dump()
        for row in rows
    ]
    return {"trending": books}


def _consume_note_minutes(user_id: str, minutes: int) -> int:
    _ensure_usage_table()
    today = date.today().isoformat()
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        row = connection.execute(
            "SELECT minutes FROM note_usage WHERE user_id = ? AND usage_date = ?",
            (user_id, today),
        ).fetchone()
        used = int(row[0]) if row else 0
        if used + minutes > 60:
            raise HTTPException(
                status_code=429,
                detail="The free note-taking limit is one hour per day. Upgrade to continue.",
            )
        connection.execute(
            """
            INSERT INTO note_usage (user_id, usage_date, minutes) VALUES (?, ?, ?)
            ON CONFLICT(user_id, usage_date)
            DO UPDATE SET minutes = excluded.minutes
            """,
            (user_id, today, used + minutes),
        )
        connection.commit()
    return 60 - used - minutes


def _gemini_video_blueprint(request: VideoBlueprintRequest) -> VideoBlueprintResponse:
    api_key = get_google_api_key()
    if not api_key or api_key.casefold().startswith("replace-"):
        raise HTTPException(
            status_code=503,
            detail=(
                "Gemini API key is not configured. Set GEMINI_API_KEY "
                "(GOOGLE_API_KEY is also supported) in the server environment."
            ),
        )
    try:
        from google import genai
    except ImportError as exc:
        raise HTTPException(
            status_code=503,
            detail="Install google-genai to enable Gemini video prompt generation.",
        ) from exc

    prompt = (
        "Create a JSON educational video blueprint with exactly three chronological "
        "scenes. Use only the supplied learning source for facts. Keep the supplied "
        "subject and cast identical in all scenes. Each scene must show exactly one "
        "clear physical movement and state its starting position and ending position. "
        "Preserve the requested camera movement, lighting, environment, mood, and "
        "negative constraints. Do not add visible text. Return only JSON with keys "
        '"analogy_concept" and "video_scenes". Each scene must contain "title", '
        '"action_start", "action_end", and "narration_text". The start and end '
        "positions must describe exactly one movement, not a sequence of actions. "
        f"Write narration in {request.language}.\n"
        f"Subject and cast (keep consistent): {request.subject_and_cast}\n"
        f"Action guidance: {request.action_guidance}\n"
        f"Camera movement: {request.camera_movement}\n"
        f"Lighting and environment: {request.lighting_environment}\n"
        f"Negative prompt: {request.constraints_negative_prompt}\n"
        f"Learning source:\n{request.text}"
    )
    try:
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=prompt,
            config={"response_mime_type": "application/json"},
        )
        payload = json.loads(response.text or "")
        if not isinstance(payload, dict):
            raise ValueError("Gemini must return a JSON object.")
        raw_scenes = payload.get("video_scenes")
        if (
            not isinstance(payload, dict)
            or not isinstance(raw_scenes, list)
            or len(raw_scenes) != 3
        ):
            raise ValueError("Gemini must return exactly three video scenes.")
        constraints = request.constraints_negative_prompt.strip()
        for required_constraint in (
            "No garbled text",
            "no floating artifacts",
            "consistent anatomy",
            "smooth motion",
            "no extra limbs",
        ):
            if required_constraint.casefold() not in constraints.casefold():
                constraints = f"{constraints} {required_constraint}."
        scenes: list[dict[str, str | int]] = []
        for index, raw_scene in enumerate(raw_scenes, start=1):
            if not isinstance(raw_scene, dict):
                raise ValueError(f"Gemini scene {index} is not a JSON object.")
            action_start = raw_scene.get("action_start")
            action_end = raw_scene.get("action_end")
            narration = raw_scene.get("narration_text")
            if (
                not isinstance(action_start, str)
                or not action_start.strip()
                or not isinstance(action_end, str)
                or not action_end.strip()
                or not isinstance(narration, str)
                or not narration.strip()
            ):
                raise ValueError(f"Gemini scene {index} is missing its action or narration.")
            action = (
                f"One movement: start at {action_start.strip()} and end at {action_end.strip()}."
            )
            title = str(raw_scene.get("title") or f"Scene {index}").strip()
            if not title:
                title = f"Scene {index}"
            narration = narration.strip()
            visual_prompt = "\n".join(
                (
                    f"SUBJECT & CAST: {request.subject_and_cast.strip()}",
                    f"ACTION: {action}",
                    f"CAMERA MOVEMENT: {request.camera_movement.strip()}",
                    f"LIGHTING & ENVIRONMENT: {request.lighting_environment.strip()}",
                    f"CONSTRAINTS / NEGATIVE PROMPT: {constraints}",
                )
            )
            scenes.append(
                {
                    "scene_number": index,
                    "title": title,
                    "subtitle": narration,
                    "detail": action,
                    "subject_and_cast": request.subject_and_cast.strip(),
                    "action": action,
                    "camera_movement": request.camera_movement.strip(),
                    "lighting_environment": request.lighting_environment.strip(),
                    "constraints_negative_prompt": constraints,
                    "visual_prompt": visual_prompt,
                    "narration_text": narration,
                }
            )
    except HTTPException:
        raise
    except Exception as exc:
        message = str(exc).replace(api_key, "[redacted]")
        raise HTTPException(
            status_code=502,
            detail=f"Gemini video prompt generation failed: {message}",
        ) from exc
    return VideoBlueprintResponse(
        analogy_concept=str(payload.get("analogy_concept") or "").strip(),
        video_scenes=scenes,
        provider="google-ai-studio",
    )


def _fallback_transform(request: TransformRequest) -> str:
    text = " ".join(request.text.split())
    if request.output_format == "translation":
        return SandboxTranslationService.translate(text, request.target_language)
    if request.output_format == "letter":
        return (
            "Subject: Summary\n\n"
            f"Dear Reader,\n\n{text}\n\n"
            "Kind regards,"
        )
    if request.output_format == "report":
        return f"# Report\n\n## Overview\n{text}\n\n## Key points\n- Review the source material for details."
    return f"# Notes\n\n## Main idea\n{text}\n\n## Key takeaway\nReview the source material and confirm the important details."


def _ai_transform(request: TransformRequest) -> str:
    placeholder_keys = {
        "",
        "your-openai-api-key-here",
        "replace-with-openai-api-key",
    }
    if (
        not OPENAI_API_KEY
        or OPENAI_API_KEY.casefold() in placeholder_keys
        or OPENAI_API_KEY.casefold().startswith("replace-")
    ):
        return _fallback_transform(request)

    try:
        from openai import APIError, AuthenticationError, OpenAI
    except ImportError as exc:
        raise RuntimeError("OpenAI support requires the openai package.") from exc

    if request.output_format == "translation":
        instruction = (
            f"Translate from {request.source_language} to {request.target_language}. "
            "Preserve meaning, names, symbols, emojis, formatting, and line breaks. "
            "Return only the translation."
        )
    else:
        instruction = (
            f"Convert the source into a clear {request.output_format} in "
            f"{request.target_language}. Preserve facts, symbols, names, and numbers. "
            "Use headings and concise language. Return only the finished output."
        )

    client = OpenAI(api_key=OPENAI_API_KEY)
    try:
        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": instruction},
                {"role": "user", "content": request.text},
            ],
            temperature=0.2,
            max_tokens=4_000,
        )
    except (AuthenticationError, APIError) as exc:
        raise RuntimeError(f"AI translation provider request failed: {exc}") from exc
    result = response.choices[0].message.content
    if not result or not result.strip():
        raise RuntimeError("The AI provider returned an empty result.")
    return result.strip()


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/v1/transform", response_model=TransformResponse)
def transform(request: TransformRequest) -> TransformResponse:
    try:
        remaining = None
        if request.output_format == "notes":
            remaining = _consume_note_minutes(request.user_id, request.duration_minutes)
        result = _ai_transform(request)
    except HTTPException as exc:
        if exc.status_code != 429:
            raise
        result = _fallback_transform(request)
        remaining = None
    except (RuntimeError, ValueError):
        result = _fallback_transform(request)
        remaining = None
    return TransformResponse(
        result=result,
        output_format=request.output_format,
        remaining_free_minutes=remaining,
    )


@app.post("/v1/narrate", response_class=FileResponse)
async def narrate(request: NarrationRequest) -> FileResponse:
    """Generate a cached MP3 that mobile clients can play over the LAN."""
    return await _narrate_file(request.text, request.language)


async def _narrate_file(text: str, language_value: str) -> FileResponse:
    language = language_value.strip().casefold().replace("_", "-")
    if not language.replace("-", "").isalpha():
        raise HTTPException(status_code=422, detail="language must contain letters only.")
    try:
        from letsrd_core import AudioCache

        cache = AudioCache(_AUDIO_DIRECTORY)
        audio_path = await asyncio.to_thread(
            cache.generate_mp3,
            text,
            f"{language}:{text}",
            language,
        )
    except (ImportError, RuntimeError, ValueError, TypeError, OSError):
        try:
            from letsrd_core import AudioCache

            audio_path = await asyncio.to_thread(
                AudioCache(_AUDIO_DIRECTORY).generate_sandbox_mp3,
                text,
                f"{language}:{text}",
            )
        except (ImportError, ValueError, OSError, TypeError) as exc:
            raise HTTPException(
                status_code=503, detail=f"Narration is unavailable: {exc}"
            ) from exc
    return FileResponse(
        audio_path,
        media_type="audio/mpeg",
        filename=audio_path.name,
    )


@app.get("/v1/narrate", response_class=FileResponse)
async def narrate_get(
    text: str = Query(..., min_length=1, max_length=50_000),
    language: str = Query("en", min_length=2, max_length=8),
) -> FileResponse:
    """Serve cached narration to mobile players that can open a URL directly."""
    return await _narrate_file(text, language)


@app.post("/v1/flashcards", response_model=FlashcardResponse)
def flashcards(request: FlashcardRequest) -> FlashcardResponse:
    try:
        cards = FlashcardService.generate(request.text, request.limit)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return FlashcardResponse(flashcards=[Flashcard(**card) for card in cards])


@app.get(
    "/v1/learning-style/results",
    response_model=LearningStyleRecommendations,
)
def get_learning_style_results(
    user_id: str = Query(min_length=1, max_length=120),
) -> LearningStyleRecommendations:
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_style_results (
                user_id TEXT NOT NULL,
                visual_style TEXT NOT NULL,
                correct INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, visual_style)
            )
            """
        )
        rows = connection.execute(
            "SELECT visual_style, correct, total FROM learning_style_results WHERE user_id = ?",
            (user_id,),
        ).fetchall()
    styles = {
        row[0]: LearningStylePerformance(correct=row[1], total=row[2])
        for row in rows
    }
    eligible = [
        (style, performance)
        for style, performance in styles.items()
        if performance.total >= 3
    ]
    recommended = max(
        eligible,
        key=lambda item: (
            item[1].correct / item[1].total,
            item[1].total,
            item[0],
        ),
        default=(None, None),
    )[0]
    return LearningStyleRecommendations(
        styles=styles,
        recommended_style=recommended,
    )


@app.post("/v1/learning-style/results", response_model=LearningStyleRecommendations)
def record_learning_style_result(
    request: LearningStyleResultRequest,
) -> LearningStyleRecommendations:
    if request.correct > request.total:
        raise HTTPException(
            status_code=422, detail="Correct answers cannot exceed total answers."
        )
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            """
            CREATE TABLE IF NOT EXISTS learning_style_results (
                user_id TEXT NOT NULL,
                visual_style TEXT NOT NULL,
                correct INTEGER NOT NULL DEFAULT 0,
                total INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (user_id, visual_style)
            )
            """
        )
        connection.execute(
            """
            INSERT INTO learning_style_results (user_id, visual_style, correct, total)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id, visual_style) DO UPDATE SET
                correct = correct + excluded.correct,
                total = total + excluded.total
            """,
            (request.user_id, request.visual_style, request.correct, request.total),
        )
        connection.commit()
    return get_learning_style_results(request.user_id)


@app.post("/v1/video/blueprint", response_model=VideoBlueprintResponse)
def video_blueprint(request: VideoBlueprintRequest) -> VideoBlueprintResponse:
    return _gemini_video_blueprint(request)


@app.get("/v1/profile", response_model=ProfileResponse)
def get_profile(user_id: str = Query(min_length=1, max_length=120)) -> ProfileResponse:
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, given_name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT NOT NULL)"
        )
        row = connection.execute(
            "SELECT user_id, given_name, email, subject FROM profiles WHERE user_id = ?",
            (user_id,),
        ).fetchone()
    if row is None:
        return ProfileResponse(user_id=user_id, given_name="Alex", email="", subject="General learning")
    return ProfileResponse(user_id=row[0], given_name=row[1], email=row[2], subject=row[3])


@app.put("/v1/profile", response_model=ProfileResponse)
def save_profile(request: ProfileRequest) -> ProfileResponse:
    with closing(sqlite3.connect(USAGE_DATABASE)) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS profiles (user_id TEXT PRIMARY KEY, given_name TEXT NOT NULL, email TEXT NOT NULL, subject TEXT NOT NULL)"
        )
        connection.execute(
            """
            INSERT INTO profiles (user_id, given_name, email, subject) VALUES (?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET given_name=excluded.given_name, email=excluded.email, subject=excluded.subject
            """,
            (request.user_id, request.given_name.strip(), request.email.strip(), request.subject.strip()),
        )
        connection.commit()
    return ProfileResponse(
        user_id=request.user_id,
        given_name=request.given_name.strip(),
        email=request.email.strip(),
        subject=request.subject.strip(),
    )


def _callback_metadata(callback: dict[str, object]) -> dict[str, object]:
    metadata = callback.get("CallbackMetadata")
    items = metadata.get("Item", []) if isinstance(metadata, dict) else []
    values: dict[str, object] = {}
    if isinstance(items, list):
        for item in items:
            if isinstance(item, dict) and "Name" in item:
                values[str(item["Name"])] = item.get("Value")
    return values


@app.post("/v1/payments/mpesa/callback", response_model=MpesaCallbackResponse)
def mpesa_callback(payload: dict[str, object]) -> MpesaCallbackResponse:
    body = payload.get("Body")
    callback = body.get("stkCallback") if isinstance(body, dict) else None
    if not isinstance(callback, dict):
        raise HTTPException(status_code=400, detail="Invalid M-Pesa callback payload.")
    try:
        result_code = int(callback.get("ResultCode", -1))
    except (TypeError, ValueError):
        result_code = -1
    result_desc = str(callback.get("ResultDesc", "Unknown M-Pesa result"))
    if result_code != 0:
        return MpesaCallbackResponse(
            acknowledged=True,
            successful=False,
            result_code=result_code,
            message=result_desc,
        )

    metadata = _callback_metadata(callback)
    phone = str(metadata.get("PhoneNumber", "")).strip()
    receipt = str(metadata.get("MpesaReceiptNumber", "")).strip() or None
    if not phone or not receipt:
        raise HTTPException(
            status_code=400,
            detail="Successful callback is missing PhoneNumber or receipt.",
        )
    account = _PAYMENT_ACCOUNTS.setdefault(phone, AccountStatus())
    account.activate_paid()
    return MpesaCallbackResponse(
        acknowledged=True,
        successful=True,
        result_code=0,
        message=result_desc,
        receipt=receipt,
        account_tier=account.current_tier.value,
    )
