#!/usr/bin/env python3
"""
Vieed - Modern, Minimalist & Smart Offline TUI Text Editor
Author: vieexploit (https://github.com/vieexploit)
License: MIT
"""

import os
import re
import sys
import httpx
import asyncio

from pygments.lexers import get_lexer_for_filename, guess_lexer, get_lexer_by_name, ClassNotFound
from rich.markup import escape
from rich.syntax import Syntax
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import TextArea, Input, Static, Label, OptionList, Button, Markdown
from textual.widgets.option_list import Option
from textual.widgets.text_area import Selection


class HelpScreen(ModalScreen):
    """Dialog screen displaying shortcut references and Vieed feature info."""

    BINDINGS = [("escape", "dismiss", "Close"), ("ctrl+h", "dismiss", "Close")]

    def compose(self) -> ComposeResult:
        help_text = (
            "[bold cyan]Vieed - Shortcut & Feature Reference[/bold cyan]\n"
            "[dim]Created by vieexploit[/dim]\n\n"
            "• [bold yellow]Ctrl + S[/bold yellow]       : Save File\n"
            "• [bold yellow]Ctrl + F[/bold yellow]       : Search Text (Enter: Next, Esc: Close)\n"
            "• [bold yellow]Ctrl + Space[/bold yellow]   : Trigger Autocomplete Suggestion\n"
            "• [bold yellow]Ctrl+Shift+A[/bold yellow] : AI Bug/Error Code Analysis\n"
            "• [bold yellow]Ctrl+Shift+F[/bold yellow] : Format / Auto-Indent Code\n"
            "• [bold yellow]Ctrl + T[/bold yellow]       : Toggle AI Chat Assistant Sidebar\n"
            "• [bold yellow]Ctrl + Y[/bold yellow]       : Copy AI Fix Code to Clipboard\n"
            "• [bold yellow]Ctrl + R[/bold yellow]       : Refresh / Reset AI & UI State\n"
            "• [bold yellow]Ctrl+Shift+C[/bold yellow] : Copy Selected Text in Editor\n"
            "• [bold yellow]Ctrl+Shift+V[/bold yellow] : Paste Clipboard Text\n"
            "• [bold yellow]Ctrl+Shift+X[/bold yellow] : Cut Selected Text\n"
            "• [bold yellow]Tab[/bold yellow]          : Insert Indentation/Tab in Editor\n"
            "• [bold yellow]Ctrl + H[/bold yellow]       : Open This Help Dialog\n"
            "• [bold yellow]Ctrl + Q[/bold yellow]       : Quit Vieed\n"
            "• [bold yellow]Esc[/bold yellow]          : Dismiss Active Panels / Popups\n\n"
            "[dim]Press ESC or Ctrl+H to close this dialog.[/dim]"
        )
        with Container(id="help_dialog"):
            yield Static(help_text)

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class CodeBlockWithCopy(Container):
    """Fenced code block with a dedicated copy button pinned at the bottom-right corner."""

    def __init__(self, code: str, language: str = "", **kwargs):
        super().__init__(**kwargs)
        self.code = code
        self.language = language.strip().lower()

    def compose(self) -> ComposeResult:
        lexer = None
        if self.language:
            try:
                lexer = get_lexer_by_name(self.language)
            except ClassNotFound:
                lexer = None
        syntax = Syntax(
            self.code,
            lexer or "text",
            theme="ansi_dark",
            word_wrap=True,
        )
        with Vertical(classes="code_block_wrapper"):
            yield Static(syntax, classes="code_block_content", markup=False)
            with Horizontal(classes="code_block_footer"):
                yield Button("📋 Copy Code", classes="copy_code_btn")

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Copy the block's code to the clipboard when its button is clicked."""
        if not event.button.has_class("copy_code_btn"):
            return
        event.stop()
        app = self.app
        app._set_clipboard(self.code)
        app.set_status("📋 Code copied to clipboard.")
        event.button.label = "✅ Copied!"
        self.set_timer(1.5, self._reset_button_label)

    def _reset_button_label(self) -> None:
        try:
            self.query_one(".copy_code_btn", Button).label = "📋 Copy Code"
        except Exception:
            pass


class ChatMessageWidget(Container):
    """Widget to render Chat Messages safely using Textual's native Markdown widget."""

    CODE_BLOCK_PATTERN = re.compile(r"```([a-zA-Z0-9+#._-]*)\n(.*?)\n?```", re.DOTALL)

    def __init__(self, sender: str, text: str, **kwargs):
        super().__init__(**kwargs)
        self.sender = sender
        self.text = text

    def compose(self) -> ComposeResult:
        is_ai = "Vieed AI" in self.sender
        header_color = "cyan" if is_ai else "green"
        safe_sender = escape(self.sender)

        yield Label(f"[{header_color}][bold]{safe_sender}:[/bold][/{header_color}]", classes="msg_sender")
        last_end = 0
        found_block = False
        for match in self.CODE_BLOCK_PATTERN.finditer(self.text):
            found_block = True
            before = self.text[last_end:match.start()].strip()
            if before:
                yield Markdown(before, classes="msg_markdown")
            yield CodeBlockWithCopy(code=match.group(2), language=match.group(1))
            last_end = match.end()

        if not found_block:
            yield Markdown(self.text, classes="msg_markdown")
        else:
            remainder = self.text[last_end:].strip()
            if remainder:
                yield Markdown(remainder, classes="msg_markdown")


class ChatSidebar(Container):
    """Sidebar for the AI Q&A session based on the active code context."""

    def compose(self) -> ComposeResult:
        with Horizontal(id="chat_header_row"):
            yield Label("[bold cyan]🤖 Vieed AI Assistant[/bold cyan]", id="chat_title")
            yield Static("Press [bold]Ctrl+T[/bold] to close.", id="chat_hint")
        with VerticalScroll(id="chat_scroll_area"):
            pass
        yield Input(placeholder="Ask something about this code...", id="chat_input")


class VieedEditor(App):
    """Main Vieed TUI Editor app with full-screen TTY compatibility."""

    CSS = """
    Screen {
        align: center middle;
        background: default;
        color: white;
    }

    #viewport_container {
        width: 100%;
        height: 100%;
        border: solid green;
        background: default;
    }

    #header_bar {
        height: 1;
        background: green;
        color: black;
        content-align: center middle;
        text-style: bold;
    }

    #main_pane {
        height: 1fr;
    }

    #editor_area {
        height: 1fr;
        border: none;
        background: default;
    }

    #status_bar {
        height: 1;
        background: blue;
        color: white;
        padding: 0 1;
    }

    #search_bar {
        dock: bottom;
        height: 3;
        display: none;
        background: default;
        border-top: heavy yellow;
    }

    #search_bar.visible {
        display: block;
    }

    #completion_popup {
        dock: bottom;
        height: 6;
        display: none;
        background: black;
        border: heavy cyan;
    }

    #completion_popup.visible {
        display: block;
    }

    #chat_sidebar {
        width: 48;
        height: 100%;
        border-left: solid green;
        background: default;
        display: none;
        padding: 1;
    }

    #chat_sidebar.visible {
        display: block;
    }

    #chat_scroll_area {
        height: 1fr;
        border: solid white;
        padding: 1;
        margin: 1 0;
    }

    #chat_header_row {
        height: 1;
        margin-bottom: 1;
    }

    #chat_title {
        width: 1fr;
        content-align: left middle;
    }

    #chat_hint {
        width: auto;
        color: yellow;
        content-align: right middle;
    }

    /* Chat Messages & Native Markdown Styling */
    ChatMessageWidget {
        margin-bottom: 1;
        height: auto;
    }

    .msg_sender {
        margin-bottom: 0;
    }

    .msg_markdown {
        background: transparent;
        padding: 0;
        margin: 0;
        height: auto;
    }

    .msg_markdown CodeBlock {
        background: default;
        border: ascii yellow;
        margin: 1 0;
        padding: 1;
    }

    /* Fenced code blocks with dedicated copy button */
    CodeBlockWithCopy {
        height: auto;
        margin: 1 0;
        border: ascii yellow;
        background: default;
    }

    .code_block_wrapper {
        height: auto;
    }

    .code_block_content {
        height: auto;
        padding: 1 1 0 1;
    }

    .code_block_footer {
        height: 1;
        align-horizontal: right;
        padding: 0 1;
    }

    .copy_code_btn {
        height: 1;
        min-width: 14;
        border: none;
        background: cyan;
        color: black;
        text-style: bold;
    }

    .copy_code_btn:hover {
        background: white;
        color: black;
    }

    .copy_code_btn:focus {
        text-style: bold reverse;
    }

    #help_dialog {
        padding: 2;
        background: black;
        border: thick cyan;
        width: 64;
        height: auto;
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+f", "toggle_search", "Search", show=True),
        Binding("ctrl+shift+a", "analyze_error", "AI Bug Check", show=True),
        Binding("ctrl+shift+f", "format_code", "Format Code", show=True),
        Binding("ctrl+t", "toggle_chat", "AI Chat", show=True),
        Binding("ctrl+y", "copy_ai_fix", "Copy AI Fix", show=False),
        Binding("ctrl+r", "refresh_app", "Refresh UI/AI", show=True),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("ctrl+space", "trigger_autocomplete", "Autocomplete", show=True),
        Binding("ctrl+s", "save_file", "Save", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+shift+c", "copy_text", "Copy", show=False),
        Binding("ctrl+shift+v", "paste_text", "Paste", show=False),
        Binding("ctrl+shift+x", "cut_text", "Cut", show=False),
        Binding("escape", "dismiss_panels", "Dismiss", show=False),
    ]

    def __init__(self, filename: str = None):
        super().__init__()
        self.filename = filename or "Untitled"
        self.detected_lang = "Plain Text"
        self._ai_task: asyncio.Task = None
        self.last_ai_fix_code: str = ""
        self.internal_clipboard = ""
        self.ollama_url = os.environ.get("VIEED_OLLAMA_URL", "http://localhost:11434/api/generate")
        self.default_model = os.environ.get("VIEED_MODEL", "qwen2.5-coder:1.5b")
        self.max_context_chars = 8000

    def compose(self) -> ComposeResult:
        with Container(id="viewport_container"):
            yield Static(f"Vieed | File: {self.filename} | Lang: {self.detected_lang}", id="header_bar")
            with Horizontal():
                with Vertical(id="main_pane"):
                    yield TextArea.code_editor(id="editor_area")
                    yield OptionList(id="completion_popup")
                    yield Input(placeholder="Search text... (Enter: next, Esc: close)", id="search_bar")
                yield ChatSidebar(id="chat_sidebar")
            yield Static(" Ready | Ctrl+H: Help | Ctrl+Shift+A: Bug Check | Ctrl+T: AI Chat", id="status_bar")

    def on_mount(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    editor.text = f.read()
                self.notify(f"File '{self.filename}' loaded successfully.")
            except Exception as e:
                self.notify(f"Failed to read file: {e}", severity="error")

        self.detect_language()

    def _set_clipboard(self, text: str) -> None:
        """Helper method to copy text to system clipboard or fallback internally."""
        self.internal_clipboard = text
        try:
            import pyperclip
            pyperclip.copy(text)
        except Exception:
            pass

    def action_copy_ai_fix(self) -> None:
        """Shortcut action (Ctrl+Y) to quickly copy the latest AI generated fix."""
        if self.last_ai_fix_code:
            self._set_clipboard(self.last_ai_fix_code)
            self.set_status("📋 AI Fix code copied to clipboard.")
        else:
            self.set_status("⚠️ No AI fix code available yet.")

    def action_format_code(self) -> None:
        """Standard relevant action replacing F6: Trim trailing spaces and clean code lines."""
        editor = self.query_one("#editor_area", TextArea)
        lines = editor.text.splitlines()
        formatted = "\n".join(line.rstrip() for line in lines)
        if editor.text != formatted:
            editor.text = formatted
            self.set_status("✨ Code formatted (trimmed trailing whitespaces).")
        else:
            self.set_status("✨ Code is already clean.")

    def action_refresh_app(self) -> None:
        """Cancel any active AI task and refresh the UI."""
        if self._ai_task and not self._ai_task.done():
            self._ai_task.cancel()
            self._ai_task = None
            self.set_status("🔄 AI task cancelled & UI refreshed.")
        else:
            self.set_status("🔄 Refreshed.")

        self.refresh()
        self.query_one("#editor_area", TextArea).focus()

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_copy_text(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        if editor.selected_text:
            self._set_clipboard(editor.selected_text)
            self.set_status("📋 Text copied to clipboard.")

    def action_cut_text(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        if editor.selected_text:
            self._set_clipboard(editor.selected_text)
            start, end = editor.selection.start, editor.selection.end
            editor.replace("", start, end)
            self.set_status("✂️ Text cut to clipboard.")

    def action_paste_text(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        pasted_text = None
        try:
            import pyperclip
            pasted_text = pyperclip.paste()
        except Exception:
            pasted_text = self.internal_clipboard or None

        if pasted_text:
            editor.insert(pasted_text)
            self.set_status("📌 Text pasted from clipboard.")
        else:
            self.set_status("⚠️ Clipboard is empty.")

    def detect_language(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        try:
            if self.filename != "Untitled":
                lexer = get_lexer_for_filename(self.filename)
            else:
                lexer = guess_lexer(editor.text[:500])
            self.detected_lang = lexer.name
        except ClassNotFound:
            self.detected_lang = "Plain Text"

        self.update_header()

    def update_header(self) -> None:
        header = self.query_one("#header_bar", Static)
        header.update(
            f"Vieed | Author: vieexploit | File: {self.filename} | Lang: {self.detected_lang}"
        )

    @staticmethod
    def _offset_for_location(text: str, location: tuple[int, int]) -> int:
        row, col = location
        lines = text.splitlines(keepends=True)
        return sum(len(line) for line in lines[:row]) + col

    @staticmethod
    def _location_for_offset(text: str, offset: int) -> tuple[int, int]:
        before = text[:offset]
        row = before.count("\n")
        col = offset - (before.rfind("\n") + 1)
        return (row, col)

    def _find_and_jump(self, query: str) -> bool:
        editor = self.query_one("#editor_area", TextArea)
        text = editor.text
        if not query:
            return False

        start = self._offset_for_location(text, editor.cursor_location)
        if editor.selected_text == query:
            start += len(query)

        idx = text.find(query, start)
        if idx == -1:
            idx = text.find(query)
        if idx == -1:
            return False

        row, col = self._location_for_offset(text, idx)
        editor.move_cursor((row, col), select=False)
        editor.selection = Selection((row, col), (row, col + len(query)))
        editor.focus()
        return True

    def action_toggle_search(self) -> None:
        search_bar = self.query_one("#search_bar", Input)
        if search_bar.has_class("visible"):
            self._close_search()
        else:
            search_bar.add_class("visible")
            editor = self.query_one("#editor_area", TextArea)
            if editor.selected_text and "\n" not in editor.selected_text:
                search_bar.value = editor.selected_text
            search_bar.focus()

    def _close_search(self) -> None:
        search_bar = self.query_one("#search_bar", Input)
        search_bar.remove_class("visible")
        search_bar.value = ""
        self.query_one("#editor_area", TextArea).focus()

    def action_trigger_autocomplete(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        popup = self.query_one("#completion_popup", OptionList)

        cursor = editor.cursor_location
        lines = editor.text.split("\n")
        if not lines or cursor[0] >= len(lines):
            return

        current_line = lines[cursor[0]][:cursor[1]]
        words_in_line = re.findall(r"\b\w+\b", current_line)
        prefix = words_in_line[-1] if words_in_line else ""

        if not prefix or len(prefix) < 2:
            self.set_status("⚠️ Type at least 2 characters for autocompletion.")
            popup.remove_class("visible")
            return

        all_words = set(re.findall(r"\b[a-zA-Z_]\w*\b", editor.text))
        matches = sorted([w for w in all_words if w.startswith(prefix) and w != prefix])

        if not matches:
            self.set_status(f"❌ No words matching '{prefix}'")
            popup.remove_class("visible")
            return

        popup.clear_options()
        for match in matches[:5]:
            popup.add_option(Option(match))

        popup.add_class("visible")
        popup.focus()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        editor = self.query_one("#editor_area", TextArea)
        popup = self.query_one("#completion_popup", OptionList)
        selected_word = str(event.option.prompt)

        cursor = editor.cursor_location
        lines = editor.text.split("\n")
        current_line = lines[cursor[0]][:cursor[1]] if cursor[0] < len(lines) else ""
        words_in_line = re.findall(r"\b\w+\b", current_line)
        prefix = words_in_line[-1] if words_in_line else ""

        completion_suffix = selected_word[len(prefix):]
        editor.insert(completion_suffix)

        popup.remove_class("visible")
        editor.focus()
        self.set_status(f"✨ Autocomplete: '{selected_word}' inserted.")

    def action_dismiss_panels(self) -> None:
        self.query_one("#search_bar", Input).remove_class("visible")
        self.query_one("#chat_sidebar").remove_class("visible")
        self.query_one("#completion_popup", OptionList).remove_class("visible")
        self.query_one("#editor_area", TextArea).focus()

    def action_toggle_chat(self) -> None:
        chat = self.query_one("#chat_sidebar")
        if chat.has_class("visible"):
            chat.remove_class("visible")
            self.query_one("#editor_area", TextArea).focus()
        else:
            chat.add_class("visible")
            self.query_one("#chat_input", Input).focus()

    def action_save_file(self) -> None:
        if self.filename == "Untitled":
            self.set_status("⚠️ Save failed: run with a filename, e.g.: vieed code.cpp")
            return

        editor = self.query_one("#editor_area", TextArea)
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                f.write(editor.text)
            self.set_status(f"💾 File saved: {self.filename}")
        except Exception as e:
            self.set_status(f"❌ Error saving file: {e}")

    def set_status(self, msg: str) -> None:
        self.query_one("#status_bar", Static).update(f" {msg}")

    def action_analyze_error(self) -> None:
        editor = self.query_one("#editor_area", TextArea)

        selected_text = editor.selected_text
        if not selected_text:
            selected_text = editor.text[:self.max_context_chars]

        if not selected_text.strip():
            self.set_status("⚠️ Editor is empty.")
            return

        self.set_status("🤖 AI is analyzing code...")

        chat_sidebar = self.query_one("#chat_sidebar")
        if not chat_sidebar.has_class("visible"):
            chat_sidebar.add_class("visible")

        user_prompt_log = f"Check code status / bugs:\n```\n{selected_text}\n```"
        self._add_chat_message("You (Bug Check)", user_prompt_log)

        system_instruction = (
            f"Your Identity:\n"
            f"- You are 'Vieed AI', an embedded AI assistant inside Vieed (a smart offline TUI text editor created by vieexploit).\n"
            f"- Model: {self.default_model}.\n\n"
            f"TASK: Rigorous bug analysis of the following {self.detected_lang} code.\n"
            f"The user believes this code has bugs. Your job is to VERIFY WITH EVIDENCE. Do not be agreeable, do not rush to a verdict.\n\n"
            f"MANDATORY WORKFLOW - execute ALL steps in this exact order and WRITE OUT each step:\n\n"
            f"STEP 1 - SYNTAX / COMPILER CHECK:\n"
            f"Read the code as a strict {self.detected_lang} compiler would. Quote every line that is syntactically invalid and say why. A syntax error anywhere means the program does not even compile. NEVER skip this step.\n\n"
            f"STEP 2 - RUNTIME BUG CHECKLIST. For EACH letter below, write one line: PASS or FAIL, with the exact code fragment as evidence:\n"
            f"a) Constructor/initialization: is every member variable actually assigned? Watch for parameter shadowing, e.g. `id = id;` assigns NOTHING and leaves garbage values.\n"
            f"b) Loop bounds: can any index reach .size()/.length() (off-by-one, `<=` instead of `<`)? Out-of-bounds means crash or undefined behavior.\n"
            f"c) Pointer/null safety: is any pointer - including function return values that may be nullptr - dereferenced without a null check?\n"
            f"d) Branch structure: is every if/else if/else chain legal? An `else` followed by a condition is a SYNTAX ERROR.\n"
            f"e) Logic: uninitialized variables, wrong comparisons, edge cases that misbehave.\n\n"
            f"STEP 3 - VERDICT (only AFTER Steps 1-2 are fully written out):\n"
            f"- If and ONLY if every single item is PASS, output exactly: '✅ Kode sudah benar / tidak ditemukan bug!' and ask if the user wants new features.\n"
            f"- If ANY item is FAIL, then for EACH bug output in EXACTLY this format:\n"
            f"  [BUG] <short title>\n"
            f"  Lokasi: <quote the faulty line>\n"
            f"  Masalah: <what is wrong + what happens at runtime: crash / wrong output / undefined behavior>\n"
            f"  Perbaikan: <the correct approach in one sentence>\n\n"
            f"STEP 4 - FIXED CODE: only AFTER all explanations above, give the COMPLETE corrected file in ONE markdown code block. Explanations FIRST, code block LAST. Dumping raw code with no explanation is forbidden.\n\n"
            f"HARD RULES:\n"
            f"- Do NOT deny real bugs to seem agreeable. Do NOT invent fake bugs. Evidence only.\n"
            f"- Never output the verdict before the checklist.\n"
            f"- Answer in Indonesian.\n\n"
            f"Code to analyze:\n"
            f"```\n{selected_text}\n```"
        )

        if self._ai_task and not self._ai_task.done():
            self._ai_task.cancel()

        self._ai_task = asyncio.create_task(
            self._query_ollama_async(system_instruction, callback=self._handle_ai_analysis)
        )

    def _handle_ai_analysis(self, response_text: str) -> None:
        code_blocks = re.findall(r"```(?:[a-zA-Z0-9+#-]+)?\n(.*?)```", response_text, flags=re.DOTALL)
        if code_blocks:
            self.last_ai_fix_code = code_blocks[-1].strip()

        self._add_chat_message("Vieed AI (Bug Check)", response_text)
        self.set_status("✨ AI Analysis complete. Press Ctrl+Y to copy fix code.")

    def _add_chat_message(self, sender: str, text: str) -> None:
        try:
            chat_scroll = self.query_one("#chat_scroll_area", VerticalScroll)
        except Exception:
            return
        msg_widget = ChatMessageWidget(sender=sender, text=text)
        chat_scroll.mount(msg_widget)
        chat_scroll.scroll_end(animate=False)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search_bar":
            query = event.value.strip()
            if not query:
                self._close_search()
                return

            found = self._find_and_jump(query)
            if not found:
                self.set_status(f"❌ Search: '{query}' not found.")
            else:
                self.set_status(f"🔍 Found: '{query}'")

        elif event.input.id == "chat_input":
            user_msg = event.value.strip()
            if not user_msg:
                return

            event.input.value = ""
            editor = self.query_one("#editor_area", TextArea)

            self._add_chat_message("You", user_msg)

            code_context = editor.text[:self.max_context_chars]
            prompt = (
                f"Your Identity System Prompt:\n"
                f"- You are 'Vieed AI', an embedded AI assistant built directly into Vieed, a smart offline TUI text editor created by vieexploit.\n"
                f"- Model: {self.default_model} by Alibaba Cloud.\n"
                f"- Answer politely, clearly, and concisely in Indonesian or English according to user input.\n\n"
                f"Context code ({self.detected_lang}):\n```\n{code_context}\n```\n\n"
                f"User question: {user_msg}\n"
                f"Wrap code snippets in markdown triple backticks if any."
            )
            self.set_status("🤖 Thinking...")

            if self._ai_task and not self._ai_task.done():
                self._ai_task.cancel()

            self._ai_task = asyncio.create_task(
                self._query_ollama_async(prompt, callback=self._handle_chat_response)
            )

    def _handle_chat_response(self, response_text: str) -> None:
        self._add_chat_message("Vieed AI", response_text)
        self.set_status("Ready.")

    async def _query_ollama_async(self, prompt: str, callback=None) -> None:
        """Fully asynchronous Ollama request to prevent freezing the TUI event loop."""
        text = ""
        try:
            payload = {
                "model": self.default_model,
                "prompt": prompt,
                "stream": False,
                "options": {"temperature": 0.2},
            }
            async with httpx.AsyncClient(timeout=120.0) as client:
                res = await client.post(self.ollama_url, json=payload)
                if res.status_code == 200:
                    text = res.json().get("response", "No response from model.")
                else:
                    text = f"Ollama Error (HTTP {res.status_code}): {res.text}"
        except asyncio.CancelledError:
            text = "⚠️ Request cancelled by user."
            if callback:
                callback(text)
            return
        except Exception as e:
            text = f"Failed to connect to Ollama ({self.ollama_url}): {e}"

        if callback:
            callback(text)


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else "Untitled"
    app = VieedEditor(filename=filename)
    app.run()


if __name__ == "__main__":
    main()
