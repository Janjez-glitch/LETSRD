"""High-level facade for educational PDF audio/video generation."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from config import get_google_api_key

from .educational_pipeline import (
    AccessibleVideoRenderer,
    EducationalPipeline,
    MoviePySlideRenderer,
    PlanLimitError,
    PlanLimits,
    PdfExtractor,
    GttsNarrator,
)
from .models import AccountStatus


class MediaGeneratorEngine:
    """Expose the existing media pipeline through a small service interface."""

    def __init__(
        self,
        api_key: str | None = None,
        output_dir: str | Path = "letsrd_generated",
    ) -> None:
        self.api_key = api_key if api_key is not None else get_google_api_key()
        self.output_dir = Path(output_dir)

    @staticmethod
    def _account(tier: str) -> AccountStatus:
        return AccountStatus.from_json({"current_tier": tier})

    def validate_tier_limits(
        self,
        tier: str,
        page_count: int,
        file_format: str,
        lang: str,
        background_music: bool = False,
    ) -> bool:
        """Raise PlanLimitError when an account exceeds its available features."""
        limits = PlanLimits.for_account(self._account(tier))
        limits.check(
            page_count,
            lang.casefold(),
            file_format.casefold(),
            background_music,
        )
        return True

    def extract_text(self, pdf_path: str | Path, max_pages: int | None = None) -> str:
        text, _ = PdfExtractor(page_cap=max_pages).extract(pdf_path)
        return text

    def generate_audio_gtts(
        self, text: str, output_audio_path: str | Path, lang: str
    ) -> Path:
        return GttsNarrator().generate(text, lang, output_audio_path)

    def convert_to_mp4(
        self,
        audio_path: str | Path,
        output_video_path: str | Path,
        slides: list[dict[str, Any]],
        deaf_mode: bool = False,
    ) -> Path:
        # The renderer allocates slide durations across the full narration duration,
        # then attaches the complete audio track to the composed sequence.
        return MoviePySlideRenderer().render(
            slides, audio_path, output_video_path, subtitles=deaf_mode
        )

    def convert_to_accessible_mp4(
        self,
        audio_path: str | Path,
        output_video_path: str | Path,
        slide_image_path: str | Path,
        transcript_lines: list[dict[str, Any]],
    ) -> Path:
        """Render timed, high-contrast burned-in subtitles over a slide image."""
        return AccessibleVideoRenderer().render(
            audio_path,
            output_video_path,
            slide_image_path,
            transcript_lines,
        )

    def compile_styled_accessible_mp4(
        self,
        audio_path: str | Path,
        slide_image_path: str | Path,
        output_path: str | Path,
        subtitle_segments: list[dict[str, Any]],
    ) -> Path:
        """Render timed, padded captions over an image with mobile fast-start."""
        return self.convert_to_accessible_mp4(
            audio_path,
            output_path,
            slide_image_path,
            subtitle_segments,
        )

    def generate_from_pdf(
        self,
        pdf: bytes | str | Path,
        tier: str,
        language: str = "en",
        file_format: str = "mp3",
        background_music: bytes | None = None,
        accessibility: dict[str, bool] | None = None,
    ) -> Path:
        account = self._account(tier)
        return EducationalPipeline(self.output_dir, api_key=self.api_key).run(
            pdf,
            account,
            language,
            file_format,
            background_music,
            accessibility,
        )

    def generate_slideshow_from_pdf(
        self,
        pdf: bytes | str | Path,
        tier: str,
        language: str = "en",
        visual_style: str = "whiteboard",
    ) -> dict[str, Any]:
        """Generate a narrated, illustrated slideshow package from an uploaded PDF."""
        return EducationalPipeline(self.output_dir, api_key=self.api_key).run_slideshow(
            pdf, self._account(tier), language, visual_style
        )

    def generate_slideshow_from_text(
        self,
        text: str,
        tier: str,
        language: str = "en",
        visual_style: str = "whiteboard",
    ) -> dict[str, Any]:
        """Generate a narrated slideshow from pasted study text."""
        return EducationalPipeline(self.output_dir, api_key=self.api_key).run_slideshow_from_text(
            text, self._account(tier), language, visual_style
        )


__all__ = ["MediaGeneratorEngine", "PlanLimitError"]
