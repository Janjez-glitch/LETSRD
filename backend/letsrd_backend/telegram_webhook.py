"""Telegram webhook adapter for turning message text, URLs, and book files into audio."""

from __future__ import annotations

import asyncio
import hmac
import logging
import os
import uuid
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Request

from config import get_google_api_key

from .engine import MediaGeneratorEngine
from .parsers import (
    TextExtractionError,
    extract_text_from_file,
    extract_text_from_image,
    extract_text_from_input,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/v1/telegram", tags=["telegram"])
MAX_TELEGRAM_FILE_BYTES = 20 * 1024 * 1024
SUPPORTED_TELEGRAM_FILES = {
    ".pdf",
    ".epub",
    ".txt",
    ".md",
    ".markdown",
    ".jpg",
    ".jpeg",
    ".png",
    ".webp",
}


def _configured_secret_matches(request: Request) -> bool:
    expected = os.getenv("TELEGRAM_WEBHOOK_SECRET", "")
    received = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
    return bool(expected and received and hmac.compare_digest(expected, received))


async def _telegram_json(client: httpx.AsyncClient, method_url: str, **kwargs: Any) -> dict[str, Any]:
    try:
        response = await client.post(method_url, **kwargs)
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise RuntimeError(f"Telegram API request failed: {exc}") from exc
    if not isinstance(payload, dict) or not payload.get("ok"):
        raise RuntimeError("Telegram API rejected the request.")
    result = payload.get("result")
    return result if isinstance(result, dict) else {}


async def _download_telegram_document(
    client: httpx.AsyncClient, token: str, document: dict[str, Any]
) -> tuple[bytes, str, str]:
    file_id = document.get("file_id")
    file_name = str(document.get("file_name", "book.pdf"))
    if not isinstance(file_id, str):
        raise TextExtractionError("Telegram document metadata is missing its file ID.")
    mime_type = str(document.get("mime_type", ""))
    suffix = Path(file_name).suffix.casefold()
    image_mimes = {"image/jpeg", "image/png", "image/webp"}
    if suffix not in SUPPORTED_TELEGRAM_FILES:
        raise TextExtractionError(
            "Telegram uploads must be PDF, EPUB, TXT, Markdown, JPEG, PNG, or WebP."
        )
    if suffix in {".jpg", ".jpeg", ".png", ".webp"} and mime_type not in image_mimes:
        raise TextExtractionError("The Telegram image MIME type is not supported.")
    if suffix in {".pdf", ".epub", ".txt", ".md", ".markdown"} and mime_type.startswith("image/"):
        raise TextExtractionError("Image uploads must use a matching image file extension.")
    file_size = document.get("file_size")
    if isinstance(file_size, int) and file_size > MAX_TELEGRAM_FILE_BYTES:
        raise TextExtractionError("Telegram book uploads are limited to 20 MB.")
    metadata = await _telegram_json(
        client,
        f"https://api.telegram.org/bot{token}/getFile",
        data={"file_id": file_id},
    )
    path = metadata.get("file_path")
    if (
        not isinstance(path, str)
        or not path.startswith(("documents/", "photos/"))
        or ".." in Path(path).parts
    ):
        raise TextExtractionError("Telegram returned an invalid document file path.")
    try:
        async with client.stream(
            "GET",
            f"https://api.telegram.org/file/bot{token}/{path}",
            follow_redirects=False,
        ) as response:
            response.raise_for_status()
            content_length = response.headers.get("content-length")
            if content_length and int(content_length) > MAX_TELEGRAM_FILE_BYTES:
                raise TextExtractionError("Telegram book uploads are limited to 20 MB.")
            content = bytearray()
            async for chunk in response.aiter_bytes():
                content.extend(chunk)
                if len(content) > MAX_TELEGRAM_FILE_BYTES:
                    raise TextExtractionError(
                        "Telegram book uploads are limited to 20 MB."
                    )
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Telegram document download failed: {exc}") from exc
    return bytes(content), file_name, mime_type


@router.post("/webhook")
async def telegram_webhook(request: Request) -> dict[str, str]:
    """Handle Telegram text, public webpage links, and supported book documents."""
    if not _configured_secret_matches(request):
        raise HTTPException(status_code=403, detail="Invalid Telegram webhook secret.")
    token = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if not token:
        raise HTTPException(status_code=503, detail="Telegram bot token is not configured.")
    try:
        update = await request.json()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Invalid Telegram update JSON.") from exc
    if not isinstance(update, dict):
        raise HTTPException(status_code=400, detail="Telegram update must be a JSON object.")
    message = update.get("business_message") or update.get("message")
    if not isinstance(message, dict):
        return {"status": "ignored"}
    chat = message.get("chat")
    chat_id = chat.get("id") if isinstance(chat, dict) else None
    if not isinstance(chat_id, (int, str)):
        return {"status": "ignored"}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0)) as client:
            document = message.get("document")
            if isinstance(document, dict):
                data, filename, mime_type = await _download_telegram_document(
                    client, token, document
                )
                if mime_type.startswith("image/"):
                    text = await asyncio.to_thread(
                        extract_text_from_image,
                        data,
                        mime_type,
                        get_google_api_key(),
                    )
                else:
                    text = extract_text_from_file(data, filename)
            elif isinstance(message.get("photo"), list) and any(
                isinstance(item, dict) for item in message["photo"]
            ):
                photo_sizes = [
                    item for item in message["photo"] if isinstance(item, dict)
                ]
                photo = max(
                    photo_sizes,
                    key=lambda item: int(item.get("file_size", 0)),
                )
                data, _, _ = await _download_telegram_document(
                    client,
                    token,
                    {
                        **photo,
                        "file_name": "telegram-photo.jpg",
                        "mime_type": "image/jpeg",
                    },
                )
                text = await asyncio.to_thread(
                    extract_text_from_image,
                    data,
                    "image/jpeg",
                    get_google_api_key(),
                )
            else:
                message_text = message.get("text") or message.get("caption")
                if not isinstance(message_text, str) or not message_text.strip():
                    return {"status": "ignored"}
                text = await extract_text_from_input(message_text)

            audio_path = Path("letsrd_audio") / f"telegram-{uuid.uuid4().hex}.mp3"
            audio_path.parent.mkdir(parents=True, exist_ok=True)
            try:
                await asyncio.to_thread(
                    MediaGeneratorEngine().generate_audio_gtts,
                    text,
                    audio_path,
                    "en",
                )
                with audio_path.open("rb") as audio:
                    data_fields: dict[str, str | int] = {"chat_id": chat_id}
                    business_connection_id = message.get("business_connection_id")
                    if isinstance(business_connection_id, str):
                        data_fields["business_connection_id"] = business_connection_id
                    await _telegram_json(
                        client,
                        f"https://api.telegram.org/bot{token}/sendAudio",
                        data=data_fields,
                        files={"audio": (audio_path.name, audio, "audio/mpeg")},
                    )
            finally:
                audio_path.unlink(missing_ok=True)
    except (TextExtractionError, RuntimeError) as exc:
        logger.warning("Telegram media request failed: %s", exc)
        return {"status": "error", "detail": str(exc)}
    return {"status": "audio_sent"}
