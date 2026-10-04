"""Educational PDF to audio/video pipeline.

Integrations are deliberately explicit: provider errors are raised to callers
instead of being replaced with fabricated educational content.
"""

from __future__ import annotations

import base64
import json
import logging
import os
import re
import shutil
import tempfile
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

from config import GEMINI_MODEL, get_google_api_key

from .models import AccountStatus

VISUAL_STYLE_INSTRUCTIONS = {
    "whiteboard": (
        "Use a clean 2D whiteboard drawing style: hand-drawn minimalist lines, "
        "simple diagrams, and clear color-coded arrows. Keep the composition "
        "uncluttered and focused on step-by-step understanding."
    ),
    "cinematic": (
        "Use realistic cinematic animation styling with detailed 3D subjects, "
        "immersive environments, and thoughtful camera framing. Keep every visual "
        "fact faithful to the source document."
    ),
    "infographic": (
        "Use a kinetic infographic style with clean charts, visual comparisons, "
        "flow diagrams, and data-focused layouts. Do not invent numbers or data."
    ),
}


class PipelineError(RuntimeError):
    """Base class for a user-visible pipeline failure."""


class ProviderError(PipelineError):
    """A configured third-party provider failed or returned invalid data."""


class InvalidPdfError(PipelineError):
    """The uploaded bytes are not a readable PDF document."""


class NoExtractableTextError(PipelineError):
    """The PDF is readable but contains no locally extractable text."""

    def __init__(self, page_count: int) -> None:
        super().__init__("The PDF contains no extractable text.")
        self.page_count = page_count


class PlanLimitError(PipelineError):
    """The selected account plan does not permit the requested operation."""


FREE_LANGUAGES = frozenset({"en", "sw", "fr", "es", "de"})
MAX_EXTRACTED_PDF_CHARACTERS = 1_000_000
logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PlanLimits:
    max_pages: int | None
    video: bool
    languages: frozenset[str] | None

    @classmethod
    def for_account(cls, account: AccountStatus) -> "PlanLimits":
        if account.is_premium:
            return cls(None, True, None)
        return cls(5, False, FREE_LANGUAGES)

    def check(
        self,
        pages: int,
        language: str,
        output_format: str,
        background_music: bool = False,
    ) -> None:
        if self.max_pages is not None and pages > self.max_pages:
            raise PlanLimitError("Free accounts can process up to 5 PDF pages.")
        if self.languages is not None and language.casefold() not in self.languages:
            raise PlanLimitError(
                f"Language '{language}' is not supported on the free tier. "
                "Free languages: en, sw, fr, es, de."
            )
        if output_format == "mp4" and not self.video:
            raise PlanLimitError("MP4 output is a premium-only feature.")
        if background_music and not self.video:
            raise PlanLimitError("Background music is a Premium feature.")


class PdfExtractor:
    """Extracts readable text, preferring pdfplumber's layout-aware words."""

    def __init__(self, page_cap: int | None = None) -> None:
        self.page_cap = page_cap

    def extract(self, source: str | Path | bytes) -> tuple[str, int]:
        try:
            import pypdf
        except ImportError as exc:
            raise ProviderError("pypdf is required for PDF extraction.") from exc
        try:
            reader = self._reader(pypdf, source)
        except (pypdf.errors.PdfReadError, OSError, ValueError) as exc:
            raise InvalidPdfError("The uploaded file is not a readable PDF.") from exc
        total = len(reader.pages)
        if self.page_cap is not None and total > self.page_cap:
            raise PlanLimitError(f"This plan supports at most {self.page_cap} PDF pages.")
        count = min(total, self.page_cap) if self.page_cap else total
        if count == 0:
            raise PipelineError("The PDF contains no readable pages.")
        pages: list[str] = []
        extracted_characters = 0
        plumber = None
        try:
            import pdfplumber
            if isinstance(source, bytes):
                from io import BytesIO
                plumber = pdfplumber.open(BytesIO(source))
            else:
                plumber = pdfplumber.open(source)
        except (ImportError, OSError, ValueError):
            plumber = None
        try:
            for index in range(count):
                text = self._plumber_page(plumber, index) if plumber else ""
                if not text.strip():
                    text = reader.pages[index].extract_text() or ""
                text = text.strip()
                extracted_characters += len(text)
                if extracted_characters > MAX_EXTRACTED_PDF_CHARACTERS:
                    raise PipelineError(
                        "Extracted PDF text exceeds the 1,000,000-character processing "
                        "limit. Split the PDF into smaller documents."
                    )
                pages.append(text)
        finally:
            if plumber:
                plumber.close()
        result = "\n\n".join(page for page in pages if page)
        if not result:
            raise NoExtractableTextError(count)
        return result, count

    @staticmethod
    def _reader(pypdf: Any, source: str | Path | bytes) -> Any:
        if isinstance(source, bytes):
            from io import BytesIO
            return pypdf.PdfReader(BytesIO(source))
        return pypdf.PdfReader(str(source))

    @staticmethod
    def _plumber_page(pdf: Any, index: int) -> str:
        if pdf is None:
            return ""
        words = pdf.pages[index].extract_words()
        if not words:
            return ""
        # Group words by approximate columns, then restore top-to-bottom order.
        columns: dict[int, list[Any]] = {}
        for word in words:
            key = round(float(word["x0"]) / 80)
            columns.setdefault(key, []).append(word)
        lines: list[str] = []
        for column in sorted(columns):
            grouped: dict[int, list[str]] = {}
            for word in columns[column]:
                grouped.setdefault(round(float(word["top"]) / 4), []).append(word["text"])
            lines.extend(" ".join(grouped[row]) for row in sorted(grouped))
        return "\n".join(lines)


class GeminiEducationalGenerator:
    """Generates a strict JSON narration/slides document with Gemini."""

    SYSTEM_INSTRUCTION = (
        "You are an elite, empathetic local educator. Translate and adapt this dense "
        "educational text into a highly engaging, conversational script tailored for an "
        "auditory and visual learner in the requested target language. Break complex "
        "concepts down into simple, localized analogies. Use only the supplied source and "
        "never invent facts. Return valid JSON only, with no markdown fences, using exactly "
        'the keys "title", "summary", and "slides". slides is an array of objects with '
        '"heading", "narration", and "visual_prompt".'
    )
    SLIDESHOW_SYSTEM_INSTRUCTION = (
        "You are an elite high-school and campus tutor. Analyze the entire attached "
        "student document and create a simplified, engaging narration script divided "
        "into 5 to 10 sequential visual scenes. Use only facts stated in the document. "
        "When foundational reasoning is needed to connect ideas, explain it simply and "
        "do not present it as a fact from the document. Never invent examples, names, "
        "numbers, or claims. Each scene must have a concise heading, natural spoken "
        "narration, a highly descriptive illustration prompt faithful to the source, "
        "and a source-grounded multiple-choice recall question with exactly "
        "three answer choices and a zero-based correct answer index. "
        "Return valid JSON only, without markdown fences, using exactly the keys "
        '"title", "summary", and "slides". Each slides item must use exactly the keys '
        '"heading", "narration", "visual_prompt", "recall_question", '
        '"recall_choices", and "recall_answer_index".'
    )
    MAP_INSTRUCTION = (
        "Extract a concise, faithful study summary from this document excerpt. "
        "Preserve key definitions, relationships, examples, and facts. Do not add "
        "information that is not present in the excerpt."
    )
    DIRECT_GENERATION_LIMIT = 30_000
    CHUNK_CHARACTER_LIMIT = 18_000

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.api_key = api_key.strip()
        self.model = model or GEMINI_MODEL

    def generate(self, text: str, language: str) -> dict[str, Any]:
        if not self.api_key:
            raise ProviderError(
                "Gemini API key is not configured. Set GEMINI_API_KEY "
                "(GOOGLE_API_KEY is also supported)."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("google-genai is required for Gemini generation.") from exc
        try:
            client = genai.Client(api_key=self.api_key)
            if len(text) > self.DIRECT_GENERATION_LIMIT:
                summaries = [
                    self._generate_text(
                        client,
                        f"{self.MAP_INSTRUCTION}\n\nExcerpt {index}:\n{chunk}",
                    )
                    for index, chunk in enumerate(self._split_text(text), start=1)
                ]
                source = "\n\n".join(
                    f"Excerpt summary {index}:\n{summary}"
                    for index, summary in enumerate(summaries, start=1)
                )
            else:
                source = text
            response = client.models.generate_content(
                model=self.model,
                contents=f"Language: {language}\nSource:\n{source}",
                config={
                    "system_instruction": self.SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json",
                },
            )
            payload = json.loads(response.text or "")
        except Exception as exc:
            raise ProviderError(f"Gemini generation failed: {exc}") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("slides"), list):
            raise ProviderError("Gemini returned invalid educational JSON.")
        return payload

    def generate_from_pdf(self, pdf_path: str | Path, language: str) -> dict[str, Any]:
        """Generate narration and slides from a scanned PDF through Files API."""
        if not self.api_key:
            raise ProviderError(
                "Gemini API key is not configured. Set GEMINI_API_KEY "
                "(GOOGLE_API_KEY is also supported)."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("google-genai is required for Gemini generation.") from exc

        uploaded_file = None
        client = None
        try:
            client = genai.Client(api_key=self.api_key)
            uploaded_file = client.files.upload(file=str(pdf_path))
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    uploaded_file,
                    f"Language: {language}\nAnalyze this complete PDF and create the "
                    "educational narration and slides described by the system instruction.",
                ],
                config={
                    "system_instruction": self.SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json",
                },
            )
            payload = json.loads(response.text or "")
        except Exception as exc:
            raise ProviderError(f"Gemini PDF analysis failed: {exc}") from exc
        finally:
            if uploaded_file is not None and client is not None:
                try:
                    client.files.delete(name=uploaded_file.name)
                except Exception:
                    logger.warning(
                        "Could not delete temporary Gemini file %s",
                        uploaded_file.name,
                        exc_info=True,
                    )
        if not isinstance(payload, dict) or not isinstance(payload.get("slides"), list):
            raise ProviderError("Gemini returned invalid educational JSON for the PDF.")
        return payload

    def generate_slideshow_from_pdf(
        self, pdf_path: str | Path, language: str, visual_style: str = "whiteboard"
    ) -> dict[str, Any]:
        """Generate and validate a source-grounded, illustrated-slideshow script."""
        style_instruction = VISUAL_STYLE_INSTRUCTIONS.get(visual_style)
        if style_instruction is None:
            raise ValueError(f"Unsupported visual style: {visual_style}")
        if not self.api_key:
            raise ProviderError(
                "Gemini API key is not configured. Set GEMINI_API_KEY "
                "(GOOGLE_API_KEY is also supported)."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("google-genai is required for Gemini generation.") from exc

        uploaded_file = None
        client = None
        try:
            client = genai.Client(api_key=self.api_key)
            uploaded_file = client.files.upload(file=str(pdf_path))
            response = client.models.generate_content(
                model=self.model,
                contents=[
                    uploaded_file,
                    f"Target narration language: {language}. Analyze the complete "
                    "attached student document and follow the slideshow system "
                    f"instruction exactly.\nSelected illustration style: {style_instruction}",
                ],
                config={
                    "system_instruction": self.SLIDESHOW_SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json",
                },
            )
            payload = json.loads(response.text or "")
        except Exception as exc:
            raise ProviderError(f"Gemini slideshow generation failed: {exc}") from exc
        finally:
            if uploaded_file is not None and client is not None:
                try:
                    client.files.delete(name=uploaded_file.name)
                except Exception:
                    logger.warning(
                        "Could not delete temporary Gemini file %s",
                        uploaded_file.name,
                        exc_info=True,
                    )
        return self._validate_slideshow_payload(payload)

    def generate_slideshow_from_text(
        self, text: str, language: str, visual_style: str = "whiteboard"
    ) -> dict[str, Any]:
        """Create a source-grounded slideshow directly from learner-provided text."""
        style_instruction = VISUAL_STYLE_INSTRUCTIONS.get(visual_style)
        if style_instruction is None:
            raise ValueError(f"Unsupported visual style: {visual_style}")
        if not self.api_key:
            raise ProviderError(
                "Gemini API key is not configured. Set GEMINI_API_KEY "
                "(GOOGLE_API_KEY is also supported)."
            )
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("google-genai is required for Gemini generation.") from exc
        try:
            client = genai.Client(api_key=self.api_key)
            response = client.models.generate_content(
                model=self.model,
                contents=(
                    f"Target narration language: {language}.\n"
                    f"Selected illustration style: {style_instruction}\n"
                    f"Analyze this complete student text:\n{text}"
                ),
                config={
                    "system_instruction": self.SLIDESHOW_SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json",
                },
            )
            payload = json.loads(response.text or "")
        except Exception as exc:
            raise ProviderError(f"Gemini text slideshow generation failed: {exc}") from exc
        return self._validate_slideshow_payload(payload)

    @staticmethod
    def _validate_slideshow_payload(payload: Any) -> dict[str, Any]:
        if not isinstance(payload, dict) or not isinstance(payload.get("slides"), list):
            raise ProviderError("Gemini returned invalid educational slideshow JSON.")
        if any(
            not isinstance(payload.get(key), str) or not payload[key].strip()
            for key in ("title", "summary")
        ):
            raise ProviderError("Gemini slideshow is missing its title or summary.")
        slides = payload["slides"]
        if not 5 <= len(slides) <= 10:
            raise ProviderError(
                "Gemini must return between 5 and 10 educational slideshow scenes."
            )
        for index, slide in enumerate(slides, start=1):
            if not isinstance(slide, dict) or any(
                not isinstance(slide.get(key), str) or not slide[key].strip()
                for key in ("heading", "narration", "visual_prompt")
            ):
                raise ProviderError(
                    f"Gemini slideshow scene {index} is missing its heading, "
                    "narration, or visual prompt."
                )
            recall_fields = (
                slide.get("recall_question"),
                slide.get("recall_choices"),
                slide.get("recall_answer_index"),
            )
            if any(value is not None for value in recall_fields) and (
                not isinstance(recall_fields[0], str)
                or not recall_fields[0].strip()
                or not isinstance(recall_fields[1], list)
                or len(recall_fields[1]) != 3
                or any(not isinstance(choice, str) or not choice.strip() for choice in recall_fields[1])
                or not isinstance(recall_fields[2], int)
                or isinstance(recall_fields[2], bool)
                or not 0 <= recall_fields[2] < 3
            ):
                raise ProviderError(
                    f"Gemini slideshow scene {index} has an invalid recall question."
                )
        return payload

    @classmethod
    def _split_text(cls, text: str) -> list[str]:
        """Split long text into bounded chunks, preferring newline boundaries."""
        chunks: list[str] = []
        current = ""
        for paragraph in text.splitlines():
            remaining = paragraph
            while remaining:
                available = cls.CHUNK_CHARACTER_LIMIT - len(current) - 1
                if available <= 0:
                    chunks.append(current)
                    current = ""
                    available = cls.CHUNK_CHARACTER_LIMIT
                piece, remaining = remaining[:available], remaining[available:]
                current = f"{current}\n{piece}".strip()
                if remaining:
                    chunks.append(current)
                    current = ""
        if current:
            chunks.append(current)
        return chunks

    def _generate_text(self, client: Any, prompt: str) -> str:
        response = client.models.generate_content(model=self.model, contents=prompt)
        text = (response.text or "").strip()
        if not text:
            raise ProviderError("Gemini returned an empty document summary.")
        return text


class GttsNarrator:
    def generate(self, text: str, language: str, output: str | Path) -> Path:
        try:
            from gtts import gTTS
            gTTS(text=text, lang=language).save(str(output))
        except Exception as exc:
            raise ProviderError(f"gTTS narration failed: {exc}") from exc
        return Path(output)


class GeminiImageGenerator:
    """Generate one illustration per scene using the configured Gemini image model."""

    def __init__(self, api_key: str, model: str | None = None) -> None:
        self.model = model or os.getenv(
            "GEMINI_IMAGE_MODEL", "gemini-2.5-flash-image"
        ).strip()
        try:
            from google import genai
        except ImportError as exc:
            raise ProviderError("google-genai is required for image generation.") from exc
        try:
            self.client = genai.Client(api_key=api_key)
        except Exception as exc:
            raise ProviderError(f"Gemini image client initialization failed: {exc}") from exc

    def generate(self, prompt: str, output: str | Path) -> Path:
        try:
            response = self.client.models.generate_content(
                model=self.model,
                contents=(
                    "Create one high-quality educational illustration for a student "
                    "slideshow. Follow the visual description faithfully, add no text, "
                    "labels, or facts not present in it, and return an image.\n\n"
                    f"Visual description:\n{prompt}"
                ),
                config={"response_modalities": ["TEXT", "IMAGE"]},
            )
            image_data = None
            mime_type = ""
            for candidate in response.candidates or []:
                for part in candidate.content.parts or []:
                    inline_data = part.inline_data
                    if inline_data and inline_data.data:
                        image_data = inline_data.data
                        mime_type = inline_data.mime_type or ""
                        break
                if image_data:
                    break
            if isinstance(image_data, str):
                image_data = base64.b64decode(image_data, validate=True)
            extensions = {
                "image/png": ".png",
                "image/jpeg": ".jpg",
                "image/webp": ".webp",
            }
            extension = extensions.get(mime_type)
            if not image_data or not extension:
                raise ProviderError(
                    "Gemini image generation returned no supported PNG, JPEG, or WebP image."
                )
            output_path = Path(output).with_suffix(extension)
            output_path.write_bytes(image_data)
        except ProviderError:
            raise
        except Exception as exc:
            raise ProviderError(f"Gemini image generation failed: {exc}") from exc
        return output_path


class BackgroundMusicMixer:
    def mix(self, narration: str | Path, music: str | Path, output: str | Path) -> Path:
        try:
            from pydub import AudioSegment
            voice = AudioSegment.from_file(narration)
            track = AudioSegment.from_file(music)
            if len(track) < len(voice):
                track *= (len(voice) // len(track)) + 1
            mixed = voice.overlay(track[: len(voice)].apply_gain(-18))
            mixed.export(output, format="mp3")
        except Exception as exc:
            raise ProviderError(f"Background music mixing failed: {exc}") from exc
        return Path(output)


class MoviePySlideRenderer:
    def render(
        self,
        slides: Iterable[dict[str, Any]],
        audio: str | Path,
        output: str | Path,
        subtitles: bool = False,
    ) -> Path:
        audio_clip = None
        final = None
        try:
            from moviepy.editor import AudioFileClip, ColorClip, CompositeVideoClip, TextClip
            audio_clip = AudioFileClip(str(audio))
            items = list(slides)
            duration = audio_clip.duration / max(1, len(items))
            clips = []
            for index, slide in enumerate(items):
                background = ColorClip((1280, 720), color=(22, 33, 54), duration=duration)
                text = TextClip(
                    str(slide.get("heading", "")),
                    fontsize=54,
                    color="white",
                    method="caption",
                    size=(1100, 500),
                    align="center",
                )
                slide_layers = [background, text.set_position("center")]
                if subtitles:
                    caption_text = str(slide.get("narration", "")).strip()
                    if caption_text:
                        caption_width, caption_height = 1120, 140
                        caption_y = 720 - caption_height - 28
                        caption_backing = (
                            ColorClip(
                                (caption_width, caption_height),
                                color=(0, 0, 0),
                                duration=duration,
                            )
                            .set_opacity(0.82)
                            .set_position(("center", caption_y))
                        )
                        caption = TextClip(
                            caption_text,
                            fontsize=30,
                            color="white",
                            method="caption",
                            size=(caption_width - 36, caption_height - 20),
                            align="center",
                        ).set_position(("center", caption_y + 10))
                        slide_layers.extend((caption_backing, caption))
                clips.append(
                    CompositeVideoClip(slide_layers, size=(1280, 720)).set_start(index * duration)
                )
            final = CompositeVideoClip(clips, size=(1280, 720)).set_duration(
                audio_clip.duration
            ).set_audio(audio_clip)
            final.write_videofile(
                str(output),
                fps=24,
                codec="libx264",
                audio_codec="aac",
                ffmpeg_params=["-movflags", "+faststart"],
                logger=None,
            )
        except Exception as exc:
            raise ProviderError(f"MoviePy rendering failed: {exc}") from exc
        finally:
            if final is not None:
                final.close()
            if audio_clip is not None:
                audio_clip.close()
        return Path(output)


class AccessibleVideoRenderer:
    """Compose a still visual with time-aligned high-contrast captions."""

    def render(
        self,
        audio_path: str | Path,
        output_video_path: str | Path,
        slide_image_path: str | Path,
        transcript_lines: Iterable[dict[str, Any]],
    ) -> Path:
        audio_clip = None
        final = None
        try:
            from moviepy.editor import (
                AudioFileClip,
                ColorClip,
                CompositeVideoClip,
                ImageClip,
                TextClip,
            )

            audio_clip = AudioFileClip(str(audio_path))
            base_video = ImageClip(str(slide_image_path)).set_duration(audio_clip.duration)
            layers = [base_video]
            for line in transcript_lines:
                start, end = float(line["start"]), float(line["end"])
                start = max(0.0, start)
                end = min(audio_clip.duration, end)
                text = str(line["text"]).strip()
                if not text or end <= start:
                    continue
                caption_width = int(base_video.w * 0.85)
                caption_height = min(150, int(base_video.h * 0.22))
                caption_y = base_video.h - caption_height - int(base_video.h * 0.04)
                duration = end - start
                backing = (
                    ColorClip(
                        (caption_width, caption_height),
                        color=(0, 0, 0),
                        duration=duration,
                    )
                    .set_opacity(0.82)
                    .set_start(start)
                    .set_position(("center", caption_y))
                )
                subtitle = (
                    TextClip(
                        text,
                        fontsize=32,
                        color="white",
                        font="Arial-Bold",
                        method="caption",
                        size=(caption_width - 36, caption_height - 20),
                        align="center",
                    )
                    .set_start(start)
                    .set_duration(duration)
                    .set_position(("center", caption_y + 10))
                )
                layers.extend((backing, subtitle))
            final = CompositeVideoClip(layers).set_audio(audio_clip)
            final.write_videofile(
                str(output_video_path),
                fps=24,
                codec="libx264",
                audio_codec="aac",
                ffmpeg_params=["-movflags", "+faststart"],
                logger=None,
            )
        except Exception as exc:
            raise ProviderError(f"Accessible video rendering failed: {exc}") from exc
        finally:
            if final is not None:
                final.close()
            if audio_clip is not None:
                audio_clip.close()
        return Path(output_video_path)


class EducationalPipeline:
    def __init__(
        self,
        output_dir: str | Path = "letsrd_generated",
        api_key: str | None = None,
    ) -> None:
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.api_key = api_key

    def run(
        self, pdf: bytes | str | Path, account: AccountStatus, language: str = "en",
        output_format: str = "mp3", background_music: bytes | None = None,
        accessibility: dict[str, bool] | None = None,
    ) -> Path:
        accessibility = accessibility or {}
        limits = PlanLimits.for_account(account)
        extractor = PdfExtractor(limits.max_pages)
        scanned_pdf = False
        try:
            text, pages = extractor.extract(pdf)
        except NoExtractableTextError as exc:
            text, pages = "", exc.page_count
            scanned_pdf = True
        language = language.casefold().replace("_", "-")
        limits.check(pages, language, output_format, background_music is not None)
        job = self.output_dir / uuid.uuid4().hex
        job.mkdir()
        try:
            api_key = self.api_key
            if api_key is None:
                api_key = get_google_api_key()
            generator = GeminiEducationalGenerator(api_key)
            if scanned_pdf:
                source_path = Path(pdf) if not isinstance(pdf, bytes) else job / "source.pdf"
                if isinstance(pdf, bytes):
                    source_path.write_bytes(pdf)
                try:
                    content = generator.generate_from_pdf(source_path, language)
                finally:
                    if isinstance(pdf, bytes):
                        source_path.unlink(missing_ok=True)
            else:
                content = generator.generate(text, language)
            slides = content["slides"]
            if accessibility.get("is_blind_mode"):
                for slide in slides:
                    visual_description = str(slide.get("visual_prompt", "")).strip()
                    if visual_description:
                        slide["narration"] = (
                            f"{slide.get('narration', '').strip()} "
                            f"Visual description: {visual_description}"
                        ).strip()
            narration = job / "narration.mp3"
            GttsNarrator().generate(
                "\n\n".join(str(slide.get("narration", "")) for slide in slides),
                language,
                narration,
            )
            if background_music:
                music = job / "music.mp3"
                music.write_bytes(background_music)
                narration = BackgroundMusicMixer().mix(narration, music, job / "mixed.mp3")
            if output_format == "mp3":
                return narration
            return MoviePySlideRenderer().render(
                slides,
                narration,
                job / "slides.mp4",
                subtitles=bool(accessibility.get("is_deaf_mode")),
            )
        except Exception:
            shutil.rmtree(job, ignore_errors=True)
            raise

    def run_slideshow(
        self,
        pdf: bytes | str | Path,
        account: AccountStatus,
        language: str = "en",
        visual_style: str = "whiteboard",
    ) -> dict[str, Any]:
        """Create a narrated slideshow package with one generated image per scene."""
        try:
            import pypdf
        except ImportError as exc:
            raise ProviderError("pypdf is required for PDF processing.") from exc
        try:
            reader = PdfExtractor._reader(pypdf, pdf)
            page_count = len(reader.pages)
        except (pypdf.errors.PdfReadError, OSError, ValueError) as exc:
            raise InvalidPdfError("The uploaded file is not a readable PDF.") from exc
        if page_count == 0:
            raise PipelineError("The PDF contains no readable pages.")

        language = language.casefold().replace("_", "-")
        PlanLimits.for_account(account).check(page_count, language, "mp3")
        job = self.output_dir / "slideshows" / uuid.uuid4().hex
        job.mkdir(parents=True)
        try:
            api_key = self.api_key
            if api_key is None:
                api_key = get_google_api_key()
            generator = GeminiEducationalGenerator(api_key)
            content = generator.generate_slideshow_from_pdf(
                pdf, language, visual_style
            )
            return self._build_slideshow_assets(content, api_key, language, job)
        except Exception:
            shutil.rmtree(job, ignore_errors=True)
            raise

    def run_slideshow_from_text(
        self,
        text: str,
        account: AccountStatus,
        language: str = "en",
        visual_style: str = "whiteboard",
    ) -> dict[str, Any]:
        """Create a narrated slideshow package directly from learner text."""
        normalized = text.strip()
        if not normalized:
            raise ValueError("Study text is required.")
        language = language.casefold().replace("_", "-")
        limits = PlanLimits.for_account(account)
        limits.check(1, language, "mp3")
        if limits.max_pages is not None and len(normalized) > 12_500:
            raise PlanLimitError("Free accounts can process up to 12,500 characters of study text.")
        job = self.output_dir / "slideshows" / uuid.uuid4().hex
        job.mkdir(parents=True)
        try:
            api_key = self.api_key
            if api_key is None:
                api_key = get_google_api_key()
            generator = GeminiEducationalGenerator(api_key)
            content = generator.generate_slideshow_from_text(
                normalized, language, visual_style
            )
            return self._build_slideshow_assets(content, api_key, language, job)
        except Exception:
            shutil.rmtree(job, ignore_errors=True)
            raise

    @staticmethod
    def _build_slideshow_assets(
        content: dict[str, Any], api_key: str, language: str, job: Path
    ) -> dict[str, Any]:
        images = GeminiImageGenerator(api_key)
        scenes: list[dict[str, Any]] = []
        for index, scene in enumerate(content["slides"], start=1):
            image = images.generate(
                scene["visual_prompt"], job / f"scene-{index:02}.png"
            )
            rendered_scene: dict[str, Any] = {
                "heading": scene["heading"],
                "narration": scene["narration"],
                "visual_prompt": scene["visual_prompt"],
                "image_filename": image.name,
            }
            for key in ("recall_question", "recall_choices", "recall_answer_index"):
                if key in scene:
                    rendered_scene[key] = scene[key]
            scenes.append(rendered_scene)
        (job / "scene-prompts.json").write_text(
            json.dumps(
                [scene["visual_prompt"] for scene in content["slides"]],
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )
        audio = GttsNarrator().generate(
            "\n\n".join(scene["narration"] for scene in scenes),
            language,
            job / "narration.mp3",
        )
        return {
            "job_id": job.name,
            "title": content["title"],
            "summary": content["summary"],
            "audio_filename": audio.name,
            "scenes": scenes,
        }
