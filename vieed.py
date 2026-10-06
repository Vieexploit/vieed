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
from functools import partial

from pygments.lexers import get_lexer_for_filename, guess_lexer, ClassNotFound
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical
from textual.widgets import TextArea, Input, Static, Label, OptionList
from textual.widgets.option_list import Option
from textual.widgets import TextArea, Header, Footer, Input, OptionList
from textual.widgets.text_area import Selection

OLLAMA_URL = os.environ.get("VIEED_OLLAMA_URL", "http://localhost:11434/api/generate")
DEFAULT_MODEL = os.environ.get("VIEED_MODEL", "qwen2.5-coder:1.5b")
MAX_CONTEXT_CHARS = 8000  # cap on file context sent to the AI

THEMES = {
    "carbon": {
        "name": "Carbon",
        "bg": "#121212",
        "editor_bg": "#181818",
        "header_bg": "#222222",
        "border": "#333333",
        "accent": "#00ffaf",
    },
    "oled": {
        "name": "Pure OLED Monochrome",
        "bg": "#000000",
        "editor_bg": "#000000",
        "header_bg": "#111111",
        "border": "#222222",
        "accent": "#ffffff",
    },
    "slate": {
        "name": "Slate Gray",
        "bg": "#1a1c23",
        "editor_bg": "#212431",
        "header_bg": "#2d3142",
        "border": "#4f5d75",
        "accent": "#ffffff",
    },
}


class ChatSidebar(Container):
    """Sidebar for the AI Q&A session based on the active code context."""

    def compose(self) -> ComposeResult:
        yield Label("[bold cyan]🤖 Vieed AI Assistant[/bold cyan]")
        yield Static("Press [bold]Ctrl+T[/bold] to close.", id="chat_hint")
        yield Static("", id="chat_response", classes="chat_box")
        yield Input(placeholder="Ask something about this code...", id="chat_input")


class VieedEditor(App):
    """Main Vieed TUI Editor app with monochrome themes & autocomplete."""

    CSS = """
    Screen {
        align: center middle;
        background: #121212;
        color: #e0e0e0;
    }

    #viewport_container {
        width: 100%;
        max-width: 160;
        height: 100%;
        max-height: 50;
        border: round #333333;
        background: #181818;
    }

    #header_bar {
        height: 1;
        background: #222222;
        color: #00ffaf;
        content-align: center middle;
        text-style: bold;
    }

    #main_pane {
        height: 1fr;
    }

    #editor_area {
        height: 1fr;
        border: none;
        background: #181818;
    }

    #status_bar {
        height: 1;
        background: #262626;
        color: #888888;
        padding: 0 1;
    }

    /* Panels below are docked so they overlay instead of shifting the editor */
    #search_bar {
        dock: bottom;
        height: 3;
        display: none;
        background: #1f1f1f;
        border-top: solid #00ffaf;
    }

    #search_bar.visible {
        display: block;
    }

    #completion_popup {
        dock: bottom;
        height: 6;
        display: none;
        background: #222222;
        border: single #00ffaf;
    }

    #completion_popup.visible {
        display: block;
    }

    #chat_sidebar {
        width: 45;
        height: 100%;
        border-left: solid #333333;
        background: #141414;
        display: none;
        padding: 1;
    }

    #chat_sidebar.visible {
        display: block;
    }

    .chat_box {
        height: 1fr;
        border: single #333333;
        padding: 1;
        margin: 1 0;
        overflow-y: scroll;
    }

    #chat_hint {
        color: #666666;
        font-size: 11;
    }
    """

    BINDINGS = [
        Binding("ctrl+f", "toggle_search", "Search", show=True),
        Binding("ctrl+b", "analyze_error", "AI Bug Check", show=True),
        Binding("ctrl+t", "toggle_chat", "AI Chat", show=True),
        Binding("ctrl+p", "cycle_theme", "Switch Theme", show=True),
        Binding("ctrl+space", "trigger_autocomplete", "Autocomplete", show=True),
        Binding("ctrl+s", "save_file", "Save", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("escape", "dismiss_panels", "Dismiss", show=False),
    ]

    def __init__(self, filename: str = None):
        super().__init__()
        self.filename = filename or "Untitled"
        self.detected_lang = "Plain Text"
        self.theme_keys = list(THEMES.keys())
        self.current_theme_index = 0
        self._chat_log: list[str] = []

    def compose(self) -> ComposeResult:
        with Container(id="viewport_container"):
            yield Static(f"Vieed | File: {self.filename} | Lang: {self.detected_lang}", id="header_bar")
            with Horizontal():
                with Vertical(id="main_pane"):
                    yield TextArea(id="editor_area", show_line_numbers=True)
                    yield OptionList(id="completion_popup")
                    yield Input(placeholder="Search text... (Enter: next, Esc: close)", id="search_bar")
                yield ChatSidebar(id="chat_sidebar")
            yield Static(" Ready | Ctrl+P: Theme | Ctrl+Space: Complete", id="status_bar")

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
        self.apply_theme(self.theme_keys[self.current_theme_index])

    # --- LANGUAGE & THEME ---

    def detect_language(self) -> None:
        """Detect the programming language offline using Pygments."""
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
        theme_name = THEMES[self.theme_keys[self.current_theme_index]]["name"]
        header = self.query_one("#header_bar", Static)
        header.update(
            f"Vieed | Author: vieexploit | File: {self.filename} | "
            f"Lang: {self.detected_lang} | Theme: {theme_name}"
        )

    def action_cycle_theme(self) -> None:
        """Cycle through the monochrome/dark themes."""
        self.current_theme_index = (self.current_theme_index + 1) % len(self.theme_keys)
        selected_key = self.theme_keys[self.current_theme_index]
        self.apply_theme(selected_key)
        self.set_status(f"🎨 Color scheme switched to: {THEMES[selected_key]['name']}")

    def apply_theme(self, theme_key: str) -> None:
        """Apply dynamic styles for the selected theme."""
        t = THEMES[theme_key]
        container = self.query_one("#viewport_container")
        header = self.query_one("#header_bar")
        editor = self.query_one("#editor_area")

        self.screen.styles.background = t["bg"]
        container.styles.background = t["editor_bg"]
        container.styles.border = ("round", t["border"])
        header.styles.background = t["header_bg"]
        header.styles.color = t["accent"]
        editor.styles.background = t["editor_bg"]
        self.update_header()

    # --- SEARCH (cursor actually jumps to the match) ---

    @staticmethod
    def _offset_for_location(text: str, location: tuple[int, int]) -> int:
        """Convert (row, col) into an absolute offset in the text."""
        row, col = location
        lines = text.splitlines(keepends=True)
        return sum(len(line) for line in lines[:row]) + col

    @staticmethod
    def _location_for_offset(text: str, offset: int) -> tuple[int, int]:
        """Convert an absolute offset into (row, col)."""
        before = text[:offset]
        row = before.count("\n")
        col = offset - (before.rfind("\n") + 1)
        return (row, col)

    def _find_and_jump(self, query: str) -> bool:
        """Find the next match (from cursor, wrap-around), then highlight & jump."""
        editor = self.query_one("#editor_area", TextArea)
        text = editor.text
        if not query:
            return False

        start = self._offset_for_location(text, editor.cursor_location)
        # If the current match is selected, start AFTER it (find-next behavior)
        if editor.selected_text == query:
            start += len(query)

        idx = text.find(query, start)
        if idx == -1:
            idx = text.find(query)  # wrap around to the top of the document
        if idx == -1:
            return False

        row, col = self._location_for_offset(text, idx)
        editor.move_cursor((row, col), select=False)
        editor.selection = Selection((row, col), (row, col + len(query)))
        editor.focus()
        return True

    def action_toggle_search(self) -> None:
        """Show/hide the search bar."""
        search_bar = self.query_one("#search_bar", Input)
        if search_bar.has_class("visible"):
            self._close_search()
        else:
            search_bar.add_class("visible")
            # Pre-fill with the currently selected text, if any
            editor = self.query_one("#editor_area", TextArea)
            if editor.selected_text and "\n" not in editor.selected_text:
                search_bar.value = editor.selected_text
            search_bar.focus()

    def _close_search(self) -> None:
        search_bar = self.query_one("#search_bar", Input)
        search_bar.remove_class("visible")
        search_bar.value = ""
        self.query_one("#editor_area", TextArea).focus()

    # --- SIMPLE AUTOCOMPLETION ---

    def action_trigger_autocomplete(self) -> None:
        """Suggest words based on tokens in the active document."""
        editor = self.query_one("#editor_area", TextArea)
        popup = self.query_one("#completion_popup", OptionList)

        cursor = editor.cursor_location
        lines = editor.text.splitlines()
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
        """Insert the selected word from the autocomplete popup into the editor."""
        editor = self.query_one("#editor_area", TextArea)
        popup = self.query_one("#completion_popup", OptionList)
        selected_word = str(event.option.prompt)

        cursor = editor.cursor_location
        lines = editor.text.splitlines()
        current_line = lines[cursor[0]][:cursor[1]] if cursor[0] < len(lines) else ""
        words_in_line = re.findall(r"\b\w+\b", current_line)
        prefix = words_in_line[-1] if words_in_line else ""

        completion_suffix = selected_word[len(prefix):]
        editor.insert(completion_suffix)

        popup.remove_class("visible")
        editor.focus()
        self.set_status(f"✨ Autocomplete: '{selected_word}' inserted.")

    # --- PANELS & STATUS ---

    def action_dismiss_panels(self) -> None:
        """Close all floating panels (search, autocomplete, chat) and focus the editor."""
        self.query_one("#search_bar", Input).remove_class("visible")
        self.query_one("#chat_sidebar").remove_class("visible")
        self.query_one("#completion_popup", OptionList).remove_class("visible")
        self.query_one("#editor_area", TextArea).focus()

    def action_toggle_chat(self) -> None:
        """Show/hide the AI chat sidebar."""
        chat = self.query_one("#chat_sidebar")
        if chat.has_class("visible"):
            chat.remove_class("visible")
            self.query_one("#editor_area", TextArea).focus()
        else:
            chat.add_class("visible")
            self.query_one("#chat_input", Input).focus()

    def action_save_file(self) -> None:
        """Save the editor content to the file."""
        if self.filename == "Untitled":
            self.set_status("⚠️ Save failed: run with a filename, e.g.: vieed code.py")
            return

        editor = self.query_one("#editor_area", TextArea)
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                f.write(editor.text)
            self.set_status(f"💾 File saved: {self.filename}")
        except Exception as e:
            self.set_status(f"❌ Error saving file: {e}")

    def set_status(self, msg: str) -> None:
        """Update the status/notification bar message."""
        self.query_one("#status_bar", Static).update(f" {msg}")

    # --- LOCAL AI INTEGRATION (ON-DEMAND) ---

    def action_analyze_error(self) -> None:
        """Trigger AI Error Detector via Ctrl+B."""
        editor = self.query_one("#editor_area", TextArea)

        selected_text = editor.selected_text
        if not selected_text:
            cursor_row = editor.cursor_location[0]
            lines = editor.text.splitlines()
            selected_text = lines[cursor_row] if cursor_row < len(lines) else ""

        if not selected_text.strip():
            self.set_status("⚠️ No code/line selected for analysis.")
            return

        self.set_status("🔄 AI is analyzing the code...")
        prompt = (
            f"You are a concise linter/debugger. Analyze the following {self.detected_lang} code "
            f"and state the error and its fix in 1-2 short sentences:\n\n{selected_text}"
        )
        self.run_worker(partial(self._call_ollama_worker, prompt, "status"), thread=True)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle submit from the Search Input or the AI Chat Input."""
        if event.input.id == "search_bar":
            query = event.value
            if not query:
                self.set_status("⚠️ Enter text to search for.")
                return
            if self._find_and_jump(query):
                self.set_status(f"🔍 Found '{query}'. Enter: next, Esc: close.")
            else:
                self.set_status(f"❌ Text '{query}' not found.")

        elif event.input.id == "chat_input":
            user_msg = event.value.strip()
            if not user_msg:
                return

            event.input.value = ""
            editor = self.query_one("#editor_area", TextArea)
            chat_box = self.query_one("#chat_response", Static)

            context = editor.text[:MAX_CONTEXT_CHARS]
            full_prompt = (
                f"Current file context ({self.filename}, Language: {self.detected_lang}):\n"
                f"```\n{context}\n```\n\n"
                f"User question: {user_msg}\n"
                f"Answer briefly, accurately, and helpfully."
            )

            self._chat_log.append(f"[bold yellow]You:[/bold yellow] {user_msg}")
            chat_box.update("\n\n".join(self._chat_log) + "\n\n[bold cyan]Vieed AI:[/bold cyan] Thinking...")
            self.run_worker(partial(self._call_ollama_worker, full_prompt, "chat"), thread=True)

    def _call_ollama_worker(self, prompt: str, target: str) -> None:
        """Synchronous worker (runs in a separate thread) so the UI doesn't freeze."""
        payload = {
            "model": DEFAULT_MODEL,
            "prompt": prompt,
            "stream": False,
        }
        try:
            with httpx.Client(timeout=60.0) as client:
                response = client.post(OLLAMA_URL, json=payload)
            response.raise_for_status()
            result = response.json().get("response", "").strip()
        except Exception as e:
            self.call_from_thread(self._handle_ai_error, str(e), target)
            return

        if result:
            self.call_from_thread(self._handle_ai_response, result, target)
        else:
            self.call_from_thread(self._handle_ai_error, "Empty response from model.", target)

    def _handle_ai_response(self, response_text: str, target: str) -> None:
        """Handle a successful AI worker response."""
        if target == "status":
            self.set_status(f"🤖 AI: {response_text}")
        elif target == "chat":
            self._chat_log.append(f"[bold cyan]Vieed AI:[/bold cyan] {response_text}")
            self.query_one("#chat_response", Static).update("\n\n".join(self._chat_log))

    def _handle_ai_error(self, error: str, target: str) -> None:
        """Surface AI errors politely — not just on the status bar."""
        if target == "chat":
            self._chat_log.append(f"[bold red]Vieed AI:[/bold red] ⚠️ Failed: {error}")
            self.query_one("#chat_response", Static).update("\n\n".join(self._chat_log))
        self.set_status(f"❌ Failed to connect to Ollama: {error}")


def main() -> None:
    """Entry point for the 'vieed' console script and python vieed.py."""
    target_file = sys.argv[1] if len(sys.argv) > 1 else "Untitled"
    VieedEditor(filename=target_file).run()


if __name__ == "__main__":
    main()
