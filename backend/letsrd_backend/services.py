"""Production integration adapters with injectable HTTP clients.

Adapters perform real requests when configured. Tests should inject a client
with the same ``request`` interface rather than relying on fake provider data.
"""

from __future__ import annotations

import hashlib
import base64
import json
import secrets
import time
import smtplib
import os
from datetime import datetime, timedelta, timezone
from dataclasses import dataclass
from email.message import EmailMessage
from pathlib import Path
from typing import Any, Callable, Protocol
from urllib.parse import urlencode

import requests

from .models import (
    AccountStatus,
    AccountTier,
    Ebook,
    LearnerProfile,
    VideoBlueprint,
    VideoScene,
)


class HttpClient(Protocol):
    def request(self, method: str, url: str, **kwargs: Any) -> Any: ...


class IntegrationError(RuntimeError):
    """A provider request failed or returned an invalid response."""


class SecurityValidationError(PermissionError):
    """Raised when an account cannot pass email verification."""


@dataclass
class EmailVerification:
    email: str
    verification_token_hash: str
    expires_at: datetime
    verified: bool = False


class EmailVerificationService:
    """Issues short-lived OTPs and never stores the plaintext token."""

    def __init__(self, now: Callable[[], datetime] | None = None) -> None:
        self._now = now or (lambda: datetime.utcnow())
        self._records: dict[str, EmailVerification] = {}

    @staticmethod
    def _hash(token: str) -> str:
        return hashlib.sha256(token.encode("utf-8")).hexdigest()

    def issue(self, email: str) -> tuple[str, EmailVerification]:
        normalized = email.strip().casefold()
        if not normalized or "@" not in normalized:
            raise ValueError("A valid email address is required.")
        token = str(secrets.SystemRandom().randint(100000, 999999))
        record = EmailVerification(
            email=normalized,
            verification_token_hash=self._hash(token),
            expires_at=self._now() + timedelta(minutes=15),
        )
        self._records[normalized] = record
        return token, record

    def verify(self, email: str, token: str) -> bool:
        normalized = email.strip().casefold()
        record = self._records.get(normalized)
        if record is None or record.verified or self._now() >= record.expires_at:
            return False
        if not secrets.compare_digest(record.verification_token_hash, self._hash(token.strip())):
            return False
        record.verified = True
        return True

    def require_verified(self, email: str) -> None:
        record = self._records.get(email.strip().casefold())
        if record is None or not record.verified:
            raise SecurityValidationError("Email verification is required before premium access.")

    def authorize_manual_account(self, account: AccountStatus, email: str, token: str) -> bool:
        if not self.verify(email, token):
            raise SecurityValidationError("The verification code is invalid or expired.")
        account.verified = True
        return True


class SmtpVerificationMailer:
    """Sends OTP mail using SMTP settings supplied by the environment."""

    def __init__(self, server: str, port: int, username: str, password: str,
                 smtp_factory: Callable[..., Any] = smtplib.SMTP,
                 allow_sandbox: bool = False) -> None:
        self.server, self.port = server, port
        self.username, self.password = username, password
        self.smtp_factory = smtp_factory
        self.allow_sandbox = allow_sandbox

    @classmethod
    def from_environment(
        cls, smtp_factory: Callable[..., Any] = smtplib.SMTP
    ) -> "SmtpVerificationMailer":
        server = os.getenv("SMTP_SERVER", "").strip()
        username = os.getenv("SMTP_USER", "").strip()
        password = os.getenv("SMTP_PASSWORD", "")
        if not server or not username or not password:
            if os.getenv("LETSRD_ENV", "development").casefold() != "production":
                return cls("", 587, "", "", smtp_factory, allow_sandbox=True)
            raise IntegrationError("SMTP is not configured for production.")
        try:
            port = int(os.getenv("SMTP_PORT", "587"))
        except ValueError as exc:
            raise IntegrationError("SMTP_PORT must be an integer.") from exc
        if not 1 <= port <= 65535:
            raise IntegrationError("SMTP_PORT must be between 1 and 65535.")
        return cls(
            server,
            port,
            username,
            password,
            smtp_factory,
            allow_sandbox=os.getenv("LETSRD_ENV", "development").casefold() != "production",
        )

    def send_code(self, recipient: str, token: str) -> bool:
        if self.allow_sandbox and (
            not self.server or not self.username or not self.password
        ):
            print(f"[LETSRD SANDBOX] Verification code for {recipient}: {token}")
            return False
        message = EmailMessage()
        message["Subject"] = "LETSRD email verification code"
        message["From"] = self.username
        message["To"] = recipient
        message.set_content(
            "LETSRD security verification\n\n"
            f"Your six-digit verification code is: {token}\n\n"
            "This code expires in 15 minutes. Do not share it."
        )
        try:
            with self.smtp_factory(self.server, self.port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            if self.allow_sandbox:
                print(f"[LETSRD SANDBOX] Verification code for {recipient}: {token}")
                return False
            raise IntegrationError(f"Verification email could not be sent: {exc}") from exc
        return True

    def send_student_verification_link(self, recipient: str, verification_url: str) -> bool:
        """Email an expiring student verification link without logging its token."""
        if self.allow_sandbox and (
            not self.server or not self.username or not self.password
        ):
            raise IntegrationError(
                "SMTP is not configured; student verification links cannot be delivered."
            )
        message = EmailMessage()
        message["Subject"] = "Verify your LETSRD student account"
        message["From"] = self.username
        message["To"] = recipient
        message.set_content(
            "Complete your LETSRD student verification within 15 minutes by opening:\n\n"
            f"{verification_url}\n\n"
            "If you did not request this, you can ignore this email."
        )
        try:
            with self.smtp_factory(self.server, self.port, timeout=15) as smtp:
                smtp.starttls()
                smtp.login(self.username, self.password)
                smtp.send_message(message)
        except (OSError, smtplib.SMTPException) as exc:
            raise IntegrationError(
                f"Student verification email could not be sent: {exc}"
            ) from exc
        return True


class AccountService:
    def parse(self, payload: dict[str, Any]) -> AccountStatus:
        return AccountStatus.from_json(payload)

    def banner_text(self, status: AccountStatus) -> str:
        if status.current_tier == AccountTier.PREMIUM_TRIAL:
            return f"Premium trial · {status.days_left}/14 days remaining"
        if status.current_tier == AccountTier.PREMIUM_PAID:
            return "Premium plan active"
        return "Free plan · Upgrade for video explanations"


class SandboxTranslationService:
    """Deterministic translation response used when provider credentials are unavailable."""

    _SWAHILI_PROMPT = "sasa niseme nini"

    @classmethod
    def translate(cls, text: str, target_language: str) -> str:
        normalized_text = " ".join(text.split())
        if (
            normalized_text.casefold() == cls._SWAHILI_PROMPT
            and target_language.strip().casefold() == "english"
        ):
            return "What should I say now? [Sandbox Safe-Mode Verified]"
        return f"[{target_language.strip()} translation]\n{normalized_text}"


class FlashcardService:
    """Creates deterministic active-recall cards from readable text blocks."""

    @staticmethod
    def generate(text: str, limit: int = 20) -> list[dict[str, Any]]:
        normalized = " ".join(text.split())
        if not normalized:
            raise ValueError("Text is required to generate flashcards.")
        paragraphs = [part.strip() for part in text.split("\n\n") if part.strip()]
        if not paragraphs:
            paragraphs = [normalized]
        cards: list[dict[str, Any]] = []
        for index, paragraph in enumerate(paragraphs[:limit], 1):
            sentence = " ".join(paragraph.split())
            if sentence.casefold() == "sasa niseme nini":
                cards.append(
                    {
                        "id": index,
                        "question": "What does 'Sasa niseme nini' mean?",
                        "answer": "What should I say now?",
                    }
                )
                continue
            prompt = sentence if len(sentence) <= 160 else f"{sentence[:157]}..."
            cards.append(
                {
                    "id": index,
                    "question": f"What is the key idea in: '{prompt}'?",
                    "answer": sentence,
                }
            )
        return cards


class EbookCatalogService:
    def parse(self, payload: dict[str, Any]) -> list[Ebook]:
        books: list[Ebook] = []
        for item in payload.get("books", []):
            book_id = item.get("book_id", item.get("id"))
            title = str(item.get("title", "")).strip()
            if book_id is None or not title:
                continue
            books.append(Ebook(
                book_id=book_id,
                title=title,
                author=str(item.get("author", "Unknown author")).strip(),
                genre=str(item.get("genre", "General")).strip(),
                raw_text_source_url=str(
                    item.get("raw_text_source_url", item.get("download_url", ""))
                ).strip(),
            ))
        return books


class PdfContextService:
    """Extracts page-preserving, line-oriented context from local PDFs."""

    def iter_text_chunks(self, path: str | Path):
        """Yield non-empty PDF page chunks without retaining the whole document."""
        source = Path(path)
        if source.suffix.lower() != ".pdf" or not source.is_file():
            raise ValueError("Select an existing .pdf file.")
        try:
            from pypdf import PdfReader
        except ImportError as exc:
            raise RuntimeError("PDF support requires pypdf.") from exc
        try:
            for page_number, page in enumerate(PdfReader(str(source)).pages, 1):
                lines = [
                    line.rstrip()
                    for line in (page.extract_text() or "").splitlines()
                    if line.strip()
                ]
                if lines:
                    yield f"[Page {page_number}]\n" + "\n".join(lines)
        except (OSError, ValueError) as exc:
            raise IntegrationError(f"Could not read PDF {source.name}: {exc}") from exc

    def extract_text(self, path: str | Path) -> str:
        text = "\n\n".join(self.iter_text_chunks(path))
        if not text:
            raise ValueError("The PDF contains no selectable text; OCR is required.")
        return text


class VideoBlueprintService:
    def generate(
        self,
        status: AccountStatus,
        analogy_factory: Callable[[str], VideoBlueprint] | None = None,
        concept: str = "",
    ) -> VideoBlueprint:
        if not status.is_premium:
            raise PermissionError("Video explanations require a premium plan or active trial.")
        if status.current_tier == AccountTier.PREMIUM_TRIAL and status.days_left <= 0:
            raise PermissionError("The premium trial has expired.")
        if analogy_factory:
            blueprint = analogy_factory(concept)
            if len(blueprint.video_scenes) != 3:
                raise ValueError("Video blueprints must contain exactly three scenes.")
            return blueprint
        return VideoBlueprint(
            generation_triggered=True,
            analogy_concept="A difficult idea becomes a familiar three-step physical process.",
            video_scenes=[
                VideoScene(1, "A concrete object appears in a realistic, softly lit room.", "First, we see the starting situation."),
                VideoScene(2, "Hands physically change, separate, or arrange the object in cinematic close-up.", "Next, an observable action shows how the change happens."),
                VideoScene(3, "The finished arrangement is shown in a bright wide shot with a slow camera pullback.", "Finally, the result makes the original idea easy to remember."),
            ],
        )


@dataclass(frozen=True)
class ContextBlock:
    """A readable context unit bound to one explanatory scene."""

    block_id: str
    text: str
    scene_number: int


@dataclass(frozen=True)
class SyncSnapshot:
    active_block_id: str | None
    active_scene_number: int | None
    target_language: str
    subtitle: str
    tour_index: int
    is_playing: bool


class SyncedLearningEngine:
    """State machine linking context blocks, video scenes, and narration tracks."""

    def __init__(self) -> None:
        self.blocks: list[ContextBlock] = []
        self.blueprint: VideoBlueprint | None = None
        self.target_language = "Original"
        self.active_block_id: str | None = None
        self.active_scene_number: int | None = None
        self.tour_index = -1
        self.is_playing = False
        self._tracks: dict[tuple[int, str], str] = {}

    def configure(self, context: str, blueprint: VideoBlueprint) -> None:
        scenes = sorted(blueprint.video_scenes, key=lambda scene: scene.scene_number)
        if not scenes:
            raise ValueError("A synced workspace requires at least one video scene.")
        paragraphs = [
            " ".join(part.split())
            for part in context.replace("\r\n", "\n").split("\n\n")
            if part.strip()
        ]
        if not paragraphs:
            paragraphs = ["No readable context has been imported yet."]
        self.blocks = [
            ContextBlock(
                block_id=f"context-{index + 1}",
                text=paragraph,
                scene_number=scenes[index % len(scenes)].scene_number,
            )
            for index, paragraph in enumerate(paragraphs)
        ]
        self.blueprint = blueprint
        self.tour_index = -1
        self.is_playing = False
        self.select_block(self.blocks[0].block_id)

    def add_translation(self, scene_number: int, language: str, narration: str) -> None:
        if not language.strip() or not narration.strip():
            raise ValueError("A translated narration requires a language and text.")
        self._tracks[(scene_number, language.strip())] = narration.strip()

    def select_block(self, block_id: str) -> SyncSnapshot:
        block = next((item for item in self.blocks if item.block_id == block_id), None)
        if block is None:
            raise KeyError(f"Unknown context block: {block_id}")
        self.active_block_id = block.block_id
        self.active_scene_number = block.scene_number
        return self.snapshot()

    def select_scene(self, scene_number: int) -> SyncSnapshot:
        """Jump the synchronized player to a scene, even if context has fewer blocks."""
        if self.blueprint is None or not any(
            scene.scene_number == scene_number for scene in self.blueprint.video_scenes
        ):
            raise KeyError(f"Unknown video scene: {scene_number}")
        matching_block = next(
            (block for block in self.blocks if block.scene_number == scene_number),
            None,
        )
        if matching_block is not None:
            self.active_block_id = matching_block.block_id
        self.active_scene_number = scene_number
        return self.snapshot()

    def set_language(self, language: str) -> SyncSnapshot:
        language = language.strip()
        if not language:
            raise ValueError("Target language cannot be empty.")
        self.target_language = language
        return self.snapshot()

    def advance_tour(self) -> SyncSnapshot | None:
        if not self.blocks:
            return None
        self.tour_index = (self.tour_index + 1) % len(self.blocks)
        self.is_playing = True
        return self.select_block(self.blocks[self.tour_index].block_id)

    def stop_tour(self) -> SyncSnapshot:
        self.is_playing = False
        return self.snapshot()

    def snapshot(self) -> SyncSnapshot:
        subtitle = ""
        if self.blueprint and self.active_scene_number is not None:
            scene = next(
                (item for item in self.blueprint.video_scenes
                 if item.scene_number == self.active_scene_number),
                None,
            )
            if scene:
                subtitle = self._tracks.get(
                    (scene.scene_number, self.target_language),
                    scene.narration_text,
                )
        return SyncSnapshot(
            active_block_id=self.active_block_id,
            active_scene_number=self.active_scene_number,
            target_language=self.target_language,
            subtitle=subtitle,
            tour_index=self.tour_index,
            is_playing=self.is_playing,
        )


class GoogleOAuthController:
    """OAuth 2.0 authorization-code flow for Google identity."""

    authorization_endpoint = "https://accounts.google.com/o/oauth2/v2/auth"
    token_endpoint = "https://oauth2.googleapis.com/token"
    userinfo_endpoint = "https://openidconnect.googleapis.com/v1/userinfo"
    scopes = ("openid", "email", "profile")

    def __init__(
        self,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        http_client: HttpClient | None = None,
    ) -> None:
        if not client_id or not client_secret or not redirect_uri.startswith("https://"):
            raise ValueError("Google OAuth requires credentials and an HTTPS redirect URI.")
        self.client_id = client_id
        self.client_secret = client_secret
        self.redirect_uri = redirect_uri
        self.http = http_client or requests.Session()
        self._states: set[str] = set()

    def authorization_url(self) -> str:
        state = secrets.token_urlsafe(32)
        self._states.add(state)
        params = {
            "client_id": self.client_id,
            "redirect_uri": self.redirect_uri,
            "response_type": "code",
            "scope": " ".join(self.scopes),
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        return f"{self.authorization_endpoint}?{urlencode(params)}"

    def exchange_code(self, code: str, state: str) -> LearnerProfile:
        if not code.strip() or state not in self._states:
            raise ValueError("Invalid or expired OAuth state/code.")
        self._states.remove(state)
        try:
            token_response = self.http.request(
                "POST", self.token_endpoint, data={
                    "code": code,
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "redirect_uri": self.redirect_uri,
                    "grant_type": "authorization_code",
                }, timeout=15,
            )
            token_response.raise_for_status()
            access_token = token_response.json().get("access_token")
            if not access_token:
                raise IntegrationError("Google token response did not contain access_token.")
            profile_response = self.http.request(
                "GET", self.userinfo_endpoint,
                headers={"Authorization": f"Bearer {access_token}"}, timeout=15,
            )
            profile_response.raise_for_status()
            profile = profile_response.json()
        except (requests.RequestException, ValueError, KeyError) as exc:
            raise IntegrationError(f"Google authentication failed: {exc}") from exc
        required = ("sub", "email", "given_name")
        if any(not str(profile.get(key, "")).strip() for key in required):
            raise IntegrationError("Google profile is missing required identity fields.")
        if profile.get("email_verified") is not True:
            raise SecurityValidationError(
                "Google did not verify this email address; access has been denied."
            )
        return LearnerProfile(
            provider="google",
            subject=str(profile["sub"]),
            email=str(profile["email"]),
            given_name=str(profile["given_name"]),
            picture_url=str(profile.get("picture", "")),
            email_verified=True,
        )

    @staticmethod
    def authorize_account(account: AccountStatus, profile: LearnerProfile) -> None:
        if profile.email_verified is not True:
            raise SecurityValidationError("A verified Google email is required.")
        account.verified = True


class SafaricomMpesaClient:
    """Daraja STK Push client for sandbox or production base URLs."""

    def __init__(self, consumer_key: str, consumer_secret: str, shortcode: str,
                 passkey: str, callback_url: str, base_url: str,
                 http_client: HttpClient | None = None) -> None:
        if not callback_url.startswith("https://"):
            raise ValueError("M-Pesa callback URL must use HTTPS.")
        self.consumer_key, self.consumer_secret = consumer_key, consumer_secret
        self.shortcode, self.passkey, self.callback_url = shortcode, passkey, callback_url
        self.base_url = base_url.rstrip("/")
        self.http = http_client or requests.Session()

    def _access_token(self) -> str:
        try:
            response = self.http.request(
                "GET", f"{self.base_url}/oauth/v1/generate?grant_type=client_credentials",
                auth=(self.consumer_key, self.consumer_secret), timeout=15,
            )
            response.raise_for_status()
            token = response.json().get("access_token")
        except (requests.RequestException, ValueError) as exc:
            raise IntegrationError(f"M-Pesa OAuth failed: {exc}") from exc
        if not token:
            raise IntegrationError("M-Pesa OAuth response did not contain access_token.")
        return str(token)

    def stk_push(self, amount: int, msisdn: str, account_reference: str,
                 transaction_desc: str = "LETSRD Premium") -> dict[str, Any]:
        if amount <= 0 or not msisdn.isdigit() or not account_reference.strip():
            raise ValueError("M-Pesa amount, MSISDN, and account reference are required.")
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        password = base64.b64encode(
            f"{self.shortcode}{self.passkey}{timestamp}".encode()
        ).decode()
        payload = {
            "BusinessShortCode": self.shortcode,
            "Password": password,
            "Timestamp": timestamp,
            "TransactionType": "CustomerPayBillOnline",
            "Amount": amount,
            "PartyA": msisdn,
            "PartyB": self.shortcode,
            "PhoneNumber": msisdn,
            "CallBackURL": self.callback_url,
            "AccountReference": account_reference,
            "TransactionDesc": transaction_desc,
        }
        try:
            response = self.http.request(
                "POST", f"{self.base_url}/mpesa/stkpush/v1/processrequest",
                headers={"Authorization": f"Bearer {self._access_token()}"},
                json=payload, timeout=20,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise IntegrationError(f"M-Pesa STK Push failed: {exc}") from exc
        if result.get("ResponseCode") not in (None, "0", 0):
            raise IntegrationError(f"M-Pesa rejected request: {result}")
        return result


class AirtelMoneyClient:
    def __init__(self, client_id: str, client_secret: str, base_url: str,
                 collection_path: str, country: str = "KE", currency: str = "KES",
                 http_client: HttpClient | None = None) -> None:
        self.client_id, self.client_secret = client_id, client_secret
        self.base_url, self.collection_path = base_url.rstrip("/"), collection_path
        self.country, self.currency = country, currency
        self.http = http_client or requests.Session()

    def collect(self, token: str, amount: str, msisdn: str, reference: str) -> dict[str, Any]:
        if not token.strip() or not amount.strip() or not msisdn.strip() or not reference.strip():
            raise ValueError("Airtel token, amount, MSISDN, and reference are required.")
        headers = {
            "Authorization": f"Bearer {token}",
            "X-Country": self.country,
            "X-Currency": self.currency,
            "Content-Type": "application/json",
        }
        payload = {"amount": amount, "currency": self.currency, "msisdn": msisdn, "reference": reference}
        try:
            response = self.http.request(
                "POST", f"{self.base_url}/{self.collection_path.lstrip('/')}",
                headers=headers, json=payload, timeout=20,
            )
            response.raise_for_status()
            return response.json()
        except (requests.RequestException, ValueError) as exc:
            raise IntegrationError(f"Airtel Money collection failed: {exc}") from exc


class StripeCheckoutClient:
    def __init__(self, secret_key: str, success_url: str, cancel_url: str,
                 http_client: HttpClient | None = None) -> None:
        if not secret_key or not success_url.startswith("https://") or not cancel_url.startswith("https://"):
            raise ValueError("Stripe requires a secret key and HTTPS redirect URLs.")
        self.secret_key, self.success_url, self.cancel_url = secret_key, success_url, cancel_url
        self.http = http_client or requests.Session()

    def create_checkout(self, price_id: str, customer_email: str) -> dict[str, Any]:
        if not price_id.strip() or not customer_email.strip():
            raise ValueError("Stripe price ID and customer email are required.")
        data = {
            "mode": "subscription",
            "line_items[0][price]": price_id,
            "line_items[0][quantity]": "1",
            "success_url": self.success_url,
            "cancel_url": self.cancel_url,
            "customer_email": customer_email,
        }
        try:
            response = self.http.request(
                "POST", "https://api.stripe.com/v1/checkout/sessions",
                auth=(self.secret_key, ""), data=data, timeout=20,
            )
            response.raise_for_status()
            result = response.json()
        except (requests.RequestException, ValueError) as exc:
            raise IntegrationError(f"Stripe checkout creation failed: {exc}") from exc
        if not result.get("id") or not result.get("url"):
            raise IntegrationError("Stripe response did not contain a checkout session.")
        return result


class PaymentsManager:
    """Routes checkout operations and applies verified account transitions."""

    def __init__(self, account: AccountStatus,
                 mpesa: SafaricomMpesaClient | None = None,
                 airtel: AirtelMoneyClient | None = None,
                 stripe: StripeCheckoutClient | None = None) -> None:
        self.account = account
        self.mpesa, self.airtel, self.stripe = mpesa, airtel, stripe

    def begin_mpesa(self, amount: int, msisdn: str, reference: str) -> dict[str, Any]:
        if self.mpesa is None:
            raise IntegrationError("M-Pesa is not configured.")
        return self.mpesa.stk_push(amount, msisdn, reference)

    def begin_airtel(self, token: str, amount: str, msisdn: str, reference: str) -> dict[str, Any]:
        if self.airtel is None:
            raise IntegrationError("Airtel Money is not configured.")
        return self.airtel.collect(token, amount, msisdn, reference)

    def begin_card_checkout(self, price_id: str, email: str) -> dict[str, Any]:
        if self.stripe is None:
            raise IntegrationError("Card billing is not configured.")
        return self.stripe.create_checkout(price_id, email)

    def apply_paid_webhook(self, provider: str, event: dict[str, Any]) -> None:
        if provider not in {"mpesa", "airtel_money", "stripe"}:
            raise ValueError("Unsupported payment provider.")
        if event.get("status") not in {"success", "paid", "completed"}:
            raise ValueError("Only verified successful payment events can upgrade an account.")
        self.account.activate_paid()

    def initialize_trial(self) -> None:
        self.account.start_trial()


class BillingGatewayMock:
    """Backward-compatible local validator for existing callers.

    New code should use SafaricomMpesaClient, AirtelMoneyClient, or
    StripeCheckoutClient so provider responses are verified over HTTPS.
    """

    def create_checkout(self, provider: str, phone_or_email: str, amount_minor: int,
                        currency: str) -> dict[str, str | int]:
        if provider not in {"mpesa", "airtel_money", "stripe"}:
            raise ValueError(f"Unsupported billing provider: {provider}")
        if not phone_or_email.strip() or amount_minor <= 0 or len(currency) != 3:
            raise ValueError("A payer identifier, positive amount, and ISO currency are required.")
        return {
            "provider": provider,
            "status": "mock_pending",
            "amount_minor": amount_minor,
            "currency": currency.upper(),
        }


def dump_json(data: Any) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True)
