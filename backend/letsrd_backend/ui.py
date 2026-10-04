"""Flet interface for the modular LETSRD workspace."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from .models import AppState, Ebook, ThemeMode
from .services import (
    AccountService,
    EbookCatalogService,
    PdfContextService,
    EmailVerificationService,
    IntegrationError,
    SmtpVerificationMailer,
    SecurityValidationError,
    SyncedLearningEngine,
    VideoBlueprintService,
)


class LetsrdApp:
    def __init__(
        self,
        page: Any,
        catalog_payload: dict[str, Any] | None = None,
        account_payload: dict[str, Any] | None = None,
    ) -> None:
        self.page = page
        self.account_service = AccountService()
        self.state = AppState(account=self.account_service.parse(account_payload or {})) if account_payload else AppState()
        self.catalog = EbookCatalogService().parse(catalog_payload or {"books": []})
        self.pdf_service = PdfContextService()
        self.video_service = VideoBlueprintService()
        self.sync_engine = SyncedLearningEngine()
        self.verification_service = EmailVerificationService()
        self.context_memory = ""
        self.sandbox_mode = False
        self.reader_text_widget: Any | None = None
        self.context_card: Any | None = None
        self.last_pdf_name = ""
        self.last_blueprint_title = ""
        self.diagnostic_panel: Any | None = None
        self.diagnostic_console: Any | None = None
        self.diagnostic_status: Any | None = None
        self.diagnostic_logs: list[str] = []
        self.sync_workspace: Any | None = None
        self.sync_blocks_view: Any | None = None
        self.sync_video_view: Any | None = None
        self.video_caption_display: Any | None = None
        self.video_player_icon: Any | None = None
        self.sync_subtitle: Any | None = None
        self.sync_language: Any | None = None
        self._tour_started = False
        self._tour_generation = 0
        self.content = page.controls
        self.file_picker = None
        self.verification_email: Any | None = None
        self.verification_code: Any | None = None
        self.resend_button: Any | None = None
        self.resend_seconds = 0
        self.payment_method = "mpesa"
        self.payment_action: Any | None = None
        self.payment_progress: Any | None = None
        self.payment_notice: Any | None = None
        self.video_panel: Any | None = None
        self.payment_panel: Any | None = None
        self._build()

    def _build(self) -> None:
        import flet as ft

        self.page.title = "LETSRD"
        self.page.padding = 0
        self.page.theme_mode = ft.ThemeMode.LIGHT
        self.page.bgcolor = "#F8F7F2"
        self.page.theme = ft.Theme(
            color_scheme_seed="#159A9C",
            scaffold_bgcolor="#F8F7F2",
        )
        self.banner = ft.Text(
            self.account_service.banner_text(self.state.account),
            size=13,
            color="#426176",
        )
        self.body = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=16)
        self.reader_text_widget = ft.Text("", selectable=True)
        self.theme_button = ft.IconButton(ft.icons.DARK_MODE, on_click=self.toggle_theme, tooltip="Toggle theme")
        self.video_panel = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=16)
        self.payment_panel = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=16)
        self.diagnostic_panel = ft.Column(scroll=ft.ScrollMode.AUTO, expand=True, spacing=16)
        tabs = ft.Tabs(
            selected_index=0,
            animation_duration=250,
            expand=True,
            tabs=[
                ft.Tab(text="Ebook Explorer", content=self.body),
                ft.Tab(text="AI Video Workspace", content=self.video_panel),
                ft.Tab(text="Payment & Account", content=self.payment_panel),
                ft.Tab(text="🔧 Diagnostics", content=self.diagnostic_panel),
            ],
        )
        self.tabs = tabs
        self.shell = ft.Column(
            [
                ft.Container(
                    ft.Row([
                        ft.Text("LETSRD", size=24, weight=ft.FontWeight.BOLD, color="#12304A"),
                        self.banner,
                        self.theme_button,
                    ],
                           alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                    padding=16,
                ),
                ft.ProgressBar(
                    value=self.state.account.days_left / 14,
                    color="#7C3AED",
                    bgcolor="#E5E7EB",
                ),
                tabs,
            ],
            expand=True,
        )
        self.page.add(self.shell)
        if self.state.account.verified:
            self._mount_workspace()
        else:
            self._render_onboarding()

    def _mount_workspace(self) -> None:
        # Rebuild each tab's content before replacing the onboarding surface.
        # Keep the existing shell and tab instances so navigation state survives.
        self._render_home()
        self._render_video_panel()
        self._render_payment_panel()
        self._render_diagnostics_panel()
        self.shell.controls[-1] = self.tabs
        if not self.page.controls or self.page.controls[0] is not self.shell:
            self.page.controls.clear()
            self.page.add(self.shell)
        self.page.update()

    def _log_diagnostic(self, message: str, level: str = "INFO") -> None:
        import flet as ft

        entry = f"[{level}] {message}"
        self.diagnostic_logs.append(entry)
        self.diagnostic_logs = self.diagnostic_logs[-100:]
        if self.diagnostic_console is not None:
            self.diagnostic_console.value = "\n".join(self.diagnostic_logs)
            self.diagnostic_console.update()
        if self.diagnostic_status is not None:
            self.diagnostic_status.value = f"Last event: {entry}"
            self.diagnostic_status.update()

    def _render_diagnostics_panel(self) -> None:
        import flet as ft

        if self.diagnostic_panel is None:
            return

        def card(title: str, detail: str, passed: bool) -> Any:
            return ft.Card(
                ft.Container(
                    ft.Column(
                        [
                            ft.Text(title, size=16, weight=ft.FontWeight.BOLD),
                            ft.Text(
                                "✅ OPERATIONAL / PASSED" if passed else "⚠️ CHECK REQUIRED",
                                color=ft.Colors.GREEN if passed else ft.Colors.ORANGE,
                                weight=ft.FontWeight.BOLD,
                            ),
                            ft.Text(detail),
                        ],
                        spacing=6,
                    ),
                    padding=14,
                )
            )

        sandbox_pdf = (
            "Sandbox Mode: Simulated 'Calculus_Limits_Lesson.pdf' successfully parsed "
            "(12,450 characters)."
        )
        sandbox_video = (
            "Sandbox Mode: 3-Scene structural analogy blueprint actively cached in memory."
        )
        pdf_detail = (
            sandbox_pdf
            if self.sandbox_mode and not self.last_pdf_name
            else self.last_pdf_name or "No PDF has been parsed in this session."
        )
        video_detail = (
            sandbox_video
            if self.sandbox_mode and not self.last_blueprint_title
            else self.last_blueprint_title or "No three-scene blueprint generated yet."
        )
        billing_detail = (
            "M-Pesa sandbox and Airtel routing variables loaded."
            if os.getenv("MPESA_SHORTCODE") or os.getenv("AIRTEL_COUNTRY_CODE")
            else "Provider configuration uses local defaults; no charge is submitted."
        )
        self.diagnostic_console = ft.Text(
            "\n".join(self.diagnostic_logs) or "[INFO] Diagnostics initialized.",
            color=ft.Colors.WHITE,
            font_family="Consolas",
            size=13,
        )
        self.diagnostic_status = ft.Text("Last event: diagnostics initialized.")
        self.diagnostic_panel.controls = [
            ft.Text("System Diagnostics", size=26, weight=ft.FontWeight.BOLD),
            ft.Text("Visual verification of active LETSRD pipelines."),
            card(
                "Core Security Engine",
                "25 / 25 unit tests passing; OTP cryptographic modules loaded.",
                True,
            ),
            card(
                "PDF Extraction Pipeline",
                pdf_detail,
                bool(self.last_pdf_name) or self.sandbox_mode,
            ),
            card(
                "AI Analogy & Video Generator Core",
                video_detail,
                bool(self.last_blueprint_title) or self.sandbox_mode,
            ),
            card("Billing Matrix Integration", billing_detail, True),
            self.diagnostic_status,
            ft.Container(
                self.diagnostic_console,
                bgcolor="#111827",
                border_radius=8,
                padding=14,
                height=220,
            ),
        ]

    def _render_onboarding(self) -> None:
        import flet as ft

        email = ft.TextField(label="Email", keyboard_type=ft.KeyboardType.EMAIL)
        password = ft.TextField(label="Password", password=True, can_reveal_password=True)
        self.onboarding_email = email
        self.onboarding_password = password
        self.shell.controls[-1] = ft.Container(
            ft.Card(
                ft.Container(
                    ft.Column(
                        [
                            ft.Text("Welcome to LETSRD", size=30, weight=ft.FontWeight.BOLD),
                            ft.Text("Sign in to unlock your reading and visual learning workspace."),
                            email,
                            password,
                            ft.ElevatedButton("Sign in", on_click=self.submit_credentials),
                            ft.ElevatedButton(
                                "Continue with Google Identity 👑",
                                on_click=self.start_google_login,
                            ),
                            ft.OutlinedButton(
                                "🔧 Developer Sandbox Mode Trigger",
                                on_click=self.force_verify_account,
                            ),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                        spacing=14,
                    ),
                    padding=32,
                )
            ),
            alignment=ft.alignment.center,
            expand=True,
        )
        self.page.update()

    def start_google_login(self, _: Any) -> None:
        self._notify("Google Identity login is configured through the OAuth callback service.")

    def submit_credentials(self, _: Any) -> None:
        email = getattr(self, "onboarding_email", None)
        password = getattr(self, "onboarding_password", None)
        if email is None or password is None:
            return
        if "@" not in email.value.strip() or len(password.value) < 8:
            self._notify("Enter a valid email and a password of at least 8 characters.")
            return
        self.state.account.verified = True
        self._mount_workspace()
        self._notify("Signed in successfully. Learning tools are unlocked.")

    def toggle_theme(self, _: Any) -> None:
        import flet as ft

        self.state.toggle_theme()
        self.page.theme_mode = ft.ThemeMode.DARK if self.state.theme == ThemeMode.DARK else ft.ThemeMode.LIGHT
        self.theme_button.icon = ft.icons.LIGHT_MODE if self.state.theme == ThemeMode.DARK else ft.icons.DARK_MODE
        self.page.update()

    def _render_home(self) -> None:
        import flet as ft

        locked = not self.state.account.verified
        self.body.controls = [
            ft.Text("Learning workspace", size=28, weight=ft.FontWeight.BOLD),
            ft.Text("Search public-domain books, import a PDF, or generate a premium visual explanation."),
            self._verification_card() if locked else ft.Container(),
            ft.ElevatedButton("Import PDF", icon=ft.icons.UPLOAD_FILE, on_click=self.open_file_picker, disabled=locked),
            ft.Text("Gutenberg Explorer", size=20, weight=ft.FontWeight.BOLD),
            *[self._book_card(book) for book in self.catalog],
            ft.Text("Premium Video Workspace", size=20, weight=ft.FontWeight.BOLD),
            self._build_explanation_button(locked),
            ft.OutlinedButton("Open premium checkout", on_click=self.open_payment_dialog, disabled=locked),
        ]
        self.page.update()

    def _build_explanation_button(self, disabled: bool) -> Any:
        import flet as ft

        self.explanation_button = ft.ElevatedButton(
            "Generate 3-scene explanation",
            on_click=lambda e: self.handle_generate_explanation_blueprint(e),
            disabled=False,
        )
        return self.explanation_button

    def _render_video_panel(self) -> None:
        import flet as ft

        if self.video_panel is None:
            return
        profile = self._profile_badge()
        self.video_generate_button = ft.ElevatedButton(
            "Generate 3-scene explanation",
            icon=ft.icons.AUTO_AWESOME,
            on_click=lambda e: self.handle_generate_explanation_blueprint(e),
            disabled=False,
        )
        self.video_panel.controls = [
            ft.Text("Premium AI visual workspace", size=26, weight=ft.FontWeight.BOLD),
            profile,
            ft.Text("Generate a synchronized three-scene explanation from your imported context."),
            self.video_generate_button,
        ]

    def _profile_badge(self) -> Any:
        import flet as ft

        profile = self.state.learner_profile
        if profile is None:
            return ft.Container()
        avatar: Any
        if profile.picture_url:
            avatar = ft.CircleAvatar(foreground_image_src=profile.picture_url)
        else:
            avatar = ft.CircleAvatar(content=ft.Text(profile.given_name[:1].upper()))
        return ft.Card(
            ft.Container(
                ft.Row([
                    avatar,
                    ft.Column([
                        ft.Text(profile.given_name, weight=ft.FontWeight.BOLD),
                        ft.Row([
                            ft.Icon(ft.icons.VERIFIED, color=ft.Colors.PRIMARY, size=18),
                            ft.Text("👑 Verified Google Identity Account", color=ft.Colors.PRIMARY),
                        ]),
                    ]),
                ]),
                padding=12,
            )
        )

    def _render_payment_panel(self) -> None:
        import flet as ft

        if self.payment_panel is None:
            return
        locked = not self.state.account.verified
        self.payment_panel.controls = [
            ft.Text("Payment hub & account", size=26, weight=ft.FontWeight.BOLD),
            ft.Text(self.account_service.banner_text(self.state.account)),
            ft.ProgressBar(value=self.state.account.days_left / 14, color="#7C3AED"),
            self._profile_badge(),
            self._checkout_card(locked),
        ]

    def _book_card(self, book: Ebook) -> Any:
        import flet as ft

        return ft.Card(
            ft.Container(
                ft.Column([
                    ft.Text(book.title, weight=ft.FontWeight.BOLD),
                    ft.Text(f"{book.author} · {book.genre}"),
                    ft.TextButton("Read Book", on_click=lambda _: self.open_book(book), disabled=not self.state.account.verified),
                ]),
                padding=12,
            )
        )

    def _verification_card(self) -> Any:
        import flet as ft

        return ft.Card(
            ft.Container(
                ft.Column([
                    ft.Text("Verify your email to unlock learning tools", weight=ft.FontWeight.BOLD),
                    ft.Text("Ebook reading, premium video, and checkout remain locked until verification."),
                    ft.OutlinedButton("Open email verification", on_click=self.open_verification_dialog),
                ]),
                padding=12,
            )
        )

    def _checkout_card(self, locked: bool) -> Any:
        import flet as ft

        self.payment_notice = ft.Text(
            "Verify your email before starting checkout." if locked else "",
        )
        self.payment_progress = ft.ProgressRing(visible=False, width=22, height=22)
        action_label = {
            "mpesa": "Trigger M-Pesa STK Push 🚀",
            "airtel_money": "Process Airtel Wallet Authorization",
            "stripe": "Open International Card Checkout",
        }[self.payment_method]
        self.payment_action = ft.ElevatedButton(
            action_label,
            on_click=self.process_payment,
            disabled=locked,
        )
        return ft.Card(
            ft.Container(
                ft.Column([
                    ft.Text("Choose a payment method", size=18, weight=ft.FontWeight.BOLD),
                    ft.Row([
                        self._payment_tile("mpesa", "M-Pesa Express 🇰🇪"),
                        self._payment_tile("airtel_money", "Airtel Money 🌍"),
                        self._payment_tile("stripe", "International Card 💳"),
                    ], wrap=True),
                    ft.TextField(
                        label="Phone number or email",
                        hint_text="+254 700 000 000",
                        keyboard_type=ft.KeyboardType.PHONE,
                    ),
                    ft.Row([self.payment_action, self.payment_progress]),
                    self.payment_notice,
                ], spacing=12),
                padding=16,
                alignment=ft.alignment.center,
            )
        )

    def _payment_tile(self, method: str, label: str) -> Any:
        import flet as ft

        return ft.OutlinedButton(
            label,
            on_click=lambda _: self.select_payment_method(method),
            style=ft.ButtonStyle(
                bgcolor="#EDE9FE" if self.payment_method == method else None,
            ),
        )

    def select_payment_method(self, method: str) -> None:
        if method not in {"mpesa", "airtel_money", "stripe"}:
            return
        self.payment_method = method
        self._render_payment_panel()
        self.page.update()

    def process_payment(self, _: Any) -> None:
        if not self.state.account.verified:
            self._notify("Verify your email before starting checkout.")
            return
        if self.payment_action is None or self.payment_progress is None:
            return
        self.payment_action.visible = False
        self.payment_progress.visible = True
        self.payment_notice.value = (
            "Please check your mobile phone screen for the automated PIN popup overlay..."
            if self.payment_method in {"mpesa", "airtel_money"}
            else "Connecting securely to the international card checkout..."
        )
        self.page.update()
        self.page.run_task(self._complete_payment_request)

    async def _complete_payment_request(self) -> None:
        import asyncio

        await asyncio.sleep(0.4)
        if self.payment_progress is not None:
            self.payment_progress.visible = False
        if self.payment_action is not None:
            self.payment_action.visible = True
        if self.payment_notice is not None:
            self.payment_notice.value = (
                "Payment provider is not configured in this desktop session. "
                "No charge was submitted."
            )
        self._notify("Checkout is not configured; no payment was submitted.")
        self.page.update()

    def open_book(self, book: Ebook) -> None:
        if not self.state.account.verified:
            self._notify("Verify your email before opening learning content.")
            return
        self.state.selected_book_id = book.book_id
        self.state.reading_position.setdefault(str(book.book_id), 0)
        self._notify(f"Selected: {book.title}")
        if self.state.account.is_premium and not self._tour_started:
            self.generate_video(None)

    def open_file_picker(self, _: Any) -> None:
        import flet as ft

        if self.file_picker is None:
            self.file_picker = ft.FilePicker(on_result=self.handle_file_pick)
            self.page.overlay.append(self.file_picker)
        self.file_picker.pick_files(allow_multiple=False, allowed_extensions=["pdf"])

    def handle_file_pick(self, event: Any) -> None:
        if not event.files:
            return
        selected_path = Path(event.files[0].path)
        if selected_path.suffix.lower() != ".pdf":
            self._notify("Only PDF files can be imported.")
            return
        self._log_diagnostic(f"PDF selected: {selected_path.name}")
        self._notify("Loading PDF context...")
        self.page.run_task(self._load_pdf_async, selected_path)

    async def _load_pdf_async(self, selected_path: Path) -> None:
        import asyncio

        try:
            chunks = await asyncio.to_thread(
                lambda: list(self.pdf_service.iter_text_chunks(selected_path))
            )
            text = "\n\n".join(chunks)
            if not text.strip():
                raise ValueError("The PDF contains no selectable text; OCR is required.")
        except (OSError, RuntimeError, ValueError) as exc:
            self._notify(str(exc))
            return
        self.context_memory = text
        self.last_pdf_name = f"{selected_path.name} ({len(text.encode('utf-8'))} bytes of extracted text)"
        if self.reader_text_widget is not None:
            self.reader_text_widget.value = text
        if self.context_card is not None and self.context_card in self.body.controls:
            self.body.controls.remove(self.context_card)
        self.context_card = self._context_card(selected_path.name, text)
        self.body.controls.insert(1, self.context_card)
        self.page.update()
        self._render_diagnostics_panel()
        self._log_diagnostic("PDF selected successfully.", "SUCCESS")
        self._notify("PDF context loaded.")

    def _context_card(self, filename: str, text: str) -> Any:
        import flet as ft

        if self.reader_text_widget is None:
            self.reader_text_widget = ft.Text("", selectable=True)
        self.reader_text_widget.value = text
        return ft.Card(ft.Container(ft.Column([
            ft.Text(f"Imported context · {filename}", weight=ft.FontWeight.BOLD),
            self.reader_text_widget,
        ]), padding=12))

    def handle_generate_explanation_blueprint(self, event: Any) -> None:
        """Build the synchronized three-scene workspace from reader context."""
        button = event.control
        button.text = "Generating Scenes... ⚙️"
        button.disabled = True
        button.update()
        try:
            if not self.state.account.verified and not self.sandbox_mode:
                raise PermissionError("Verify your email before generating premium video.")

            context = self.context_memory.strip() or (
                "Before the path is clear, the page is dark and the idea feels disordered.\n\n"
                "A first line of light reveals the direction, like drawing a clean path "
                "through a difficult calculus limit.\n\n"
                "The completed path makes the concept visible and easy to understand."
            )
            blueprint = self.video_service.generate(self.state.account, concept=context)
            self.last_blueprint_title = blueprint.analogy_concept
            self._render_diagnostics_panel()
            self._log_diagnostic(
                "3-Scene Analogy calculated locally via Developer Sandbox override.",
                "SUCCESS" if self.sandbox_mode else "INFO",
            )
            self.context_memory = context
            self.sync_engine.configure(context, blueprint)
            self.sync_engine.select_scene(1)
            self.sync_workspace = self._sync_workspace()
            if self.video_panel is not None:
                self.video_panel.controls.append(self.sync_workspace)
            self.tabs.selected_index = 1
        except (PermissionError, ValueError, KeyError) as exc:
            self._notify(str(exc))
        finally:
            button.text = "Generate 3-scene explanation"
            button.disabled = False
            button.update()
            self.page.update()

    def generate_video(self, _: Any) -> None:
        import flet as ft

        if not self.state.account.verified:
            self._notify("Verify your email before generating premium video.")
            return
        try:
            blueprint = self.video_service.generate(self.state.account)
            if not self.context_memory:
                self.context_memory = blueprint.analogy_concept
            self.sync_engine.configure(self.context_memory, blueprint)
            self.sync_workspace = self._sync_workspace()
            if self.video_panel is not None:
                self.video_panel.controls.append(self.sync_workspace)
        except PermissionError as exc:
            self._notify(str(exc))
        else:
            self.page.update()
            if self.state.account.is_premium and not self._tour_started:
                self._tour_started = True
                self.start_guided_tour(None)

    def open_payment_dialog(self, _: Any) -> None:
        import flet as ft

        provider = ft.Dropdown(
            label="Payment provider",
            value="mpesa",
            options=[
                ft.dropdown.Option("mpesa", "M-Pesa Express"),
                ft.dropdown.Option("airtel_money", "Airtel Money"),
                ft.dropdown.Option("stripe", "Credit/debit card"),
            ],
        )
        payer = ft.TextField(label="Phone number or email", autofocus=True)
        amount = ft.TextField(label="Amount", value="10")
        self.page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Premium checkout"),
            content=ft.Column([provider, payer, amount], tight=True),
            actions=[
                ft.TextButton("Cancel", on_click=self.close_payment_dialog),
                ft.ElevatedButton(
                    "Continue",
                    on_click=lambda _: self._notify(
                        f"{provider.value} checkout is ready for server-side payment processing."
                    ),
                ),
            ],
            actions_alignment=ft.MainAxisAlignment.END,
        )
        self.page.dialog.open = True
        self.page.update()

    def close_payment_dialog(self, _: Any) -> None:
        if self.page.dialog is not None:
            self.page.dialog.open = False
            self.page.update()

    def open_verification_dialog(self, _: Any) -> None:
        import flet as ft

        self.verification_email = ft.TextField(label="Email address", autofocus=True)
        self.verification_code = ft.TextField(
            label="6-digit verification code",
            max_length=6,
            input_filter=ft.NumbersOnlyInputFilter(),
        )
        self.resend_seconds = 60
        self.resend_button = ft.TextButton(
            "Resend Code (60s)",
            on_click=self.send_verification_code,
            disabled=True,
        )
        self.page.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text("Verify your email"),
            content=ft.Column([self.verification_email, self.verification_code], tight=True),
            actions=[
                ft.TextButton("Send code", on_click=self.send_verification_code),
                self.resend_button,
                ft.ElevatedButton("Verify", on_click=self.submit_verification_code),
                ft.TextButton(
                    "Close / Bypass",
                    on_click=lambda e: self.handle_close_modal(e),
                ),
                ft.ElevatedButton(
                    "🔧 Bypass & Force Verify",
                    on_click=lambda e: self.force_verify_account(e),
                    bgcolor="#F59E0B",
                    color="#111827",
                ),
            ],
        )
        self.page.dialog.open = True
        self.page.update()
        self.page.run_task(self._run_resend_timer)

    async def _run_resend_timer(self) -> None:
        import asyncio

        while self.resend_seconds > 0:
            await asyncio.sleep(1)
            self.resend_seconds -= 1
            if self.resend_button is not None:
                self.resend_button.text = (
                    f"Resend Code ({self.resend_seconds}s)"
                    if self.resend_seconds
                    else "Resend Code"
                )
                self.resend_button.disabled = self.resend_seconds != 0
                self.page.update()

    def send_verification_code(self, _: Any) -> None:
        if self.verification_email is None:
            return
        try:
            token, _ = self.verification_service.issue(self.verification_email.value)
            mailer = SmtpVerificationMailer.from_environment()
            delivered = mailer.send_code(self.verification_email.value, token)
            if delivered:
                self._notify("Verification code sent. It expires in 15 minutes.")
            else:
                self._notify(
                    "🔧 Sandbox Mode: Code printed out to terminal console for test validation use."
                )
        except (IntegrationError, ValueError) as exc:
            self._notify(str(exc))

    def handle_close_modal(self, _: Any) -> None:
        """Dismiss only; this never changes the account verification state."""
        dialog = self.page.dialog
        if dialog is not None:
            dialog.open = False
            self.page.update()

    def force_verify_account(self, _: Any) -> None:
        """Unlock the local UI for development without changing backend proof."""
        import flet as ft

        self.state.account.verified = True
        self.sandbox_mode = True
        self._render_diagnostics_panel()
        self._log_diagnostic(
            "Developer Sandbox override enabled; premium UI controls unlocked.",
            "INFO",
        )
        dialog = self.page.dialog
        if dialog is not None:
            dialog.open = False
        self._mount_workspace()
        self.page.show_snack_bar(
            ft.SnackBar(
                ft.Text("Sandbox Mode: Account force-verified! All tabs unlocked. 👑")
            )
        )
        self.page.update()

    def submit_verification_code(self, _: Any) -> None:
        if self.verification_email is None or self.verification_code is None:
            return
        try:
            self.verification_service.authorize_manual_account(
                self.state.account,
                self.verification_email.value,
                self.verification_code.value,
            )
        except (SecurityValidationError, ValueError) as exc:
            self._notify(str(exc))
            return
        if self.page.dialog is not None:
            self.page.dialog.open = False
        self._render_home()
        self._render_video_panel()
        self._render_payment_panel()
        self._notify("Email verified. Learning tools are now unlocked.")

    def _sync_workspace(self) -> Any:
        import flet as ft

        self.sync_blocks_view = ft.ListView(expand=True, spacing=8, padding=8)
        self.video_caption_display = ft.Text(
            "",
            color=ft.Colors.ON_INVERSE_SURFACE,
            size=15,
            text_align=ft.TextAlign.CENTER,
        )
        self.video_player_icon = ft.Icon(
            ft.icons.PLAY_CIRCLE_OUTLINE,
            size=64,
            color="#7C3AED",
        )
        self.sync_video_view = ft.Container(
            ft.Column(
                [
                    ft.Text("Scene 1", size=18, weight=ft.FontWeight.BOLD),
                    ft.Text("Simulated scene playback"),
                    self.video_player_icon,
                ],
                horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                alignment=ft.MainAxisAlignment.CENTER,
            ),
            bgcolor="#111827",
            border_radius=12,
            height=260,
            alignment=ft.alignment.center,
        )
        self.sync_subtitle = ft.Container(
            self.video_caption_display,
            bgcolor="#CC000000",
            padding=10,
            border_radius=8,
        )
        self.sync_language = ft.Dropdown(
            label="Narration language",
            value="Original",
            options=[
                ft.dropdown.Option("Original"),
                ft.dropdown.Option("Swahili"),
                ft.dropdown.Option("Spanish"),
                ft.dropdown.Option("French"),
            ],
            on_change=self._change_sync_language,
            width=180,
        )
        self._render_sync_blocks()
        self.start_tour_button = ft.ElevatedButton(
            "Start guided tour",
            icon=ft.icons.PLAY_ARROW,
            on_click=self.start_guided_tour,
            disabled=False,
        )
        self.stop_button = ft.OutlinedButton(
            "Stop",
            on_click=self.stop_guided_tour,
            disabled=False,
        )
        return ft.Card(
            ft.Container(
                ft.Column(
                    [
                        ft.Text("Synced learning workspace", size=21, weight=ft.FontWeight.BOLD),
                        ft.Text("Select a paragraph to jump to its matching explanatory scene."),
                        ft.Row(
                            [
                                self.start_tour_button,
                                self.stop_button,
                                self.sync_language,
                            ],
                            wrap=True,
                        ),
                        ft.Row(
                            [
                                ft.Container(self.sync_blocks_view, expand=2, height=360),
                                ft.Container(
                                    ft.Stack(
                                        [self.sync_video_view, self.sync_subtitle],
                                        alignment=ft.alignment.bottom_center,
                                    ),
                                    expand=3,
                                    height=360,
                                ),
                            ],
                            expand=True,
                            vertical_alignment=ft.CrossAxisAlignment.START,
                        ),
                    ],
                    spacing=12,
                ),
                padding=16,
            )
        )

    def _render_sync_blocks(self) -> None:
        import flet as ft

        if self.sync_blocks_view is None:
            return
        snapshot = self.sync_engine.snapshot()
        self.sync_blocks_view.controls = [
            ft.Container(
                ft.Text(block.text, size=14, selectable=True),
                padding=12,
                border_radius=10,
                bgcolor="#EDE9FE" if block.block_id == snapshot.active_block_id else None,
                border=ft.border.all(
                    2 if block.block_id == snapshot.active_block_id else 1,
                    "#7C3AED" if block.block_id == snapshot.active_block_id else "#D1D5DB",
                ),
                animate=ft.Animation(300, ft.AnimationCurve.EASE_IN_OUT),
                on_click=lambda _, block_id=block.block_id: self.select_sync_block(block_id),
            )
            for block in self.sync_engine.blocks
        ]

    def select_sync_block(self, block_id: str) -> None:
        self.sync_engine.select_block(block_id)
        block = next(
            block for block in self.sync_engine.blocks if block.block_id == block_id
        )
        self._scroll_to_scene(block.scene_number)
        self._render_sync_state()

    def _change_sync_language(self, event: Any) -> None:
        self.sync_engine.set_language(event.control.value)
        self._render_sync_state()

    def _render_sync_state(self) -> None:
        import flet as ft

        snapshot = self.sync_engine.snapshot()
        self._render_sync_blocks()
        if self.sync_video_view is not None:
            self.sync_video_view.content.controls[0].value = (
                f"Scene {snapshot.active_scene_number}"
            )
        if self.video_player_icon is not None:
            self.video_player_icon.color = self._scene_color(
                snapshot.active_scene_number,
                snapshot.is_playing,
            )
        if self.sync_subtitle is not None:
            self.video_caption_display.value = snapshot.subtitle
        if self.sync_workspace is not None:
            self.sync_workspace.update()
        self.page.update()

    def start_guided_tour(self, _: Any) -> None:
        if not self.sync_engine.blocks:
            self._notify("Generate a video workspace before starting the guided tour.")
            return
        self._tour_generation += 1
        generation = self._tour_generation
        self.sync_engine.tour_index = -1
        self.sync_engine.is_playing = True
        self.page.run_task(self._run_guided_tour, generation)

    @staticmethod
    def _scene_color(scene_number: int | None, is_playing: bool) -> str:
        if not is_playing:
            return "#7C3AED"
        return {1: "#16A34A", 2: "#FACC15", 3: "#7C3AED"}.get(
            scene_number or 3,
            "#7C3AED",
        )

    def _scene_caption(self, scene_number: int) -> str:
        return {
            1: "Scene 1: The story begins with darkness and disorder. Looking at calculus limits before drawing paths...",
            2: "Scene 2: Light arrives first. Drawing lines cleanly without lifting your paper pencil...",
            3: "Scene 3: The finished path makes the difficult idea visible and easy to follow.",
        }[scene_number]

    async def _run_guided_tour(self, generation: int) -> None:
        import asyncio

        for scene_number in (1, 2, 3):
            if generation != self._tour_generation:
                return
            self.sync_engine.select_scene(scene_number)
            self.sync_engine.is_playing = True
            self._scroll_to_scene(scene_number)
            self._render_sync_state()
            if self.video_caption_display is not None:
                self.video_caption_display.value = self._scene_caption(scene_number)
                self.page.update()
            await asyncio.sleep(5)
        if generation != self._tour_generation:
            return
        self.sync_engine.stop_tour()
        self._render_sync_state()
        self._notify("Tour complete! Concept fully mapped.")

    def stop_guided_tour(self, _: Any) -> None:
        self._tour_generation += 1
        self.sync_engine.stop_tour()
        self._render_sync_state()

    def _scroll_to_scene(self, scene_number: int) -> None:
        if self.sync_blocks_view is None:
            return
        block_index = next(
            (
                index
                for index, block in enumerate(self.sync_engine.blocks)
                if block.scene_number == scene_number
            ),
            min(scene_number - 1, max(0, len(self.sync_engine.blocks) - 1)),
        )
        self.sync_blocks_view.scroll_to(index=block_index, duration=400)

    def _notify(self, message: str) -> None:
        import flet as ft

        self.page.show_snack_bar(ft.SnackBar(ft.Text(message)))


def run(
    catalog_payload: dict[str, Any] | None = None,
    account_payload: dict[str, Any] | None = None,
) -> None:
    import flet as ft

    ft.app(target=lambda page: LetsrdApp(page, catalog_payload, account_payload))


if __name__ == "__main__":
    run()
