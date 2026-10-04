"""Extract bounded plain text from URLs and common educational book formats."""

from __future__ import annotations

import ipaddress
import os
import socket
import zipfile
from io import BytesIO
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from bs4 import BeautifulSoup

from config import GEMINI_MODEL, get_google_api_key

MAX_TEXT_CHARACTERS = 50_000
MAX_INPUT_BYTES = 24 * 1024 * 1024
MAX_WEBPAGE_BYTES = 2 * 1024 * 1024
MAX_EPUB_EXPANDED_BYTES = 50 * 1024 * 1024


class TextExtractionError(RuntimeError):
    """An input could not be safely fetched or converted into readable text."""


def _validate_public_url(url: str) -> None:
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise ValueError("The webpage URL is malformed.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.port not in {None, 80, 443}
    ):
        raise ValueError("Only public HTTP or HTTPS webpage URLs are supported.")
    host = parsed.hostname.rstrip(".").casefold()
    if host == "localhost" or host.endswith(".localhost") or host.endswith(".local"):
        raise ValueError("Private and local webpage addresses are not allowed.")
    try:
        addresses = {ipaddress.ip_address(host)}
    except ValueError:
        try:
            addresses = {
                ipaddress.ip_address(item[4][0])
                for item in socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
            }
        except OSError as exc:
            raise TextExtractionError(f"Could not resolve webpage host: {exc}") from exc
    if not addresses or any(not address.is_global for address in addresses):
        raise ValueError("Private and local webpage addresses are not allowed.")


def _clean_html(html: str) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for element in soup(
        ["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]
    ):
        element.decompose()
    main = soup.find("article") or soup.find("main") or soup.body or soup
    text = main.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)[:MAX_TEXT_CHARACTERS]


async def extract_text_from_url(url: str) -> str:
    """Fetch a public webpage and extract its readable article text.

    Redirects are intentionally not followed: each destination would need a
    separate public-address validation to prevent SSRF.
    """
    try:
        _validate_public_url(url)
    except ValueError as exc:
        raise TextExtractionError(str(exc)) from exc
    try:
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=httpx.Timeout(10.0),
            headers={"User-Agent": "LETSRD/1.0 educational text extractor"},
        ) as client:
            async with client.stream("GET", url) as response:
                if response.status_code != 200:
                    raise TextExtractionError(
                        f"Could not access the requested webpage (HTTP {response.status_code})."
                    )
                content_type = response.headers.get("content-type", "")
                if "text/html" not in content_type.casefold():
                    raise TextExtractionError(
                        "The requested URL did not return an HTML webpage."
                    )
                content_length = response.headers.get("content-length")
                if content_length and int(content_length) > MAX_WEBPAGE_BYTES:
                    raise TextExtractionError("The webpage exceeds the 2 MB download limit.")
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > MAX_WEBPAGE_BYTES:
                        raise TextExtractionError(
                            "The webpage exceeds the 2 MB download limit."
                        )
                html = bytes(body).decode(response.encoding or "utf-8", errors="replace")
        text = _clean_html(html)
        if not text:
            raise TextExtractionError("No readable article text was found on the webpage.")
        return text
    except httpx.HTTPError as exc:
        raise TextExtractionError(f"Webpage request failed: {exc}") from exc


def _pdf_text(data: bytes) -> str:
    try:
        from pypdf import PdfReader

        reader = PdfReader(BytesIO(data))
        pages: list[str] = []
        for page in reader.pages[:100]:
            page_text = page.extract_text() or ""
            if page_text:
                pages.append(page_text)
            if sum(map(len, pages)) >= MAX_TEXT_CHARACTERS:
                break
        text = "\n\n".join(pages)[:MAX_TEXT_CHARACTERS]
    except Exception as exc:
        raise TextExtractionError(f"PDF text extraction failed: {exc}") from exc
    if not text.strip():
        raise TextExtractionError("The PDF does not contain extractable text.")
    return text


def _epub_text(data: bytes) -> str:
    try:
        with zipfile.ZipFile(BytesIO(data)) as archive:
            html_names = [
                info.filename
                for info in archive.infolist()
                if info.filename.casefold().endswith((".html", ".htm", ".xhtml"))
            ]
            expanded_size = sum(archive.getinfo(name).file_size for name in html_names)
            if expanded_size > MAX_EPUB_EXPANDED_BYTES:
                raise TextExtractionError("The EPUB expands beyond the permitted size.")
            chunks = []
            total = 0
            for name in html_names:
                chunk = _clean_html(archive.read(name).decode("utf-8", errors="replace"))
                chunks.append(chunk)
                total += len(chunk)
                if total >= MAX_TEXT_CHARACTERS:
                    break
            text = "\n\n".join(chunk for chunk in chunks if chunk)[:MAX_TEXT_CHARACTERS]
    except TextExtractionError:
        raise
    except (OSError, zipfile.BadZipFile, KeyError) as exc:
        raise TextExtractionError(f"EPUB text extraction failed: {exc}") from exc
    if not text.strip():
        raise TextExtractionError("The EPUB does not contain readable text.")
    return text


def extract_text_from_file(data: bytes, filename: str) -> str:
    """Extract bounded text from PDF, EPUB, Markdown, or plain-text uploads."""
    if not data:
        raise TextExtractionError("The uploaded file is empty.")
    if len(data) > MAX_INPUT_BYTES:
        raise TextExtractionError("The uploaded file exceeds the 25 MB limit.")
    suffix = Path(filename).suffix.casefold()
    if suffix == ".pdf":
        return _pdf_text(data)
    if suffix == ".epub":
        return _epub_text(data)
    if suffix in {".txt", ".md", ".markdown"}:
        return data.decode("utf-8-sig", errors="replace")[:MAX_TEXT_CHARACTERS]
    raise TextExtractionError("Supported uploads are PDF, EPUB, TXT, and Markdown.")


def extract_text_from_image(
    data: bytes,
    mime_type: str,
    api_key: str | None = None,
) -> str:
    """Use Gemini vision to transcribe readable educational text from an image."""
    if not data or len(data) > MAX_INPUT_BYTES:
        raise TextExtractionError("Image input must be non-empty and no larger than 25 MB.")
    if mime_type not in {"image/jpeg", "image/png", "image/webp"}:
        raise TextExtractionError("Supported image types are JPEG, PNG, and WebP.")
    key = api_key or get_google_api_key()
    if not key.strip():
        raise TextExtractionError(
            "Gemini API key is required to extract text from images. "
            "Set GEMINI_API_KEY (GOOGLE_API_KEY is also supported)."
        )
    try:
        from google import genai
        from google.genai import types

        client = genai.Client(api_key=key)
        image_part = types.Part.from_bytes(data=data, mime_type=mime_type)
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                image_part,
                "Transcribe all readable educational text in this image. "
                "Preserve headings, lists, formulas, and reading order. "
                "Return only the transcription; do not describe the image.",
            ],
        )
        text = (response.text or "").strip()[:MAX_TEXT_CHARACTERS]
    except Exception as exc:
        raise TextExtractionError(f"Image text extraction failed: {exc}") from exc
    if not text:
        raise TextExtractionError("No readable text was found in the image.")
    return text


async def extract_text_from_input(text: str) -> str:
    """Return capped raw text, or fetch it when input is an HTTP(S) URL."""
    value = text.strip()
    if not value:
        raise TextExtractionError("Input text cannot be empty.")
    if value.startswith(("https://", "http://")):
        return await extract_text_from_url(value)
    return value[:MAX_TEXT_CHARACTERS]
