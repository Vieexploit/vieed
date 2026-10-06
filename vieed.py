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
from rich.markup import escape
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Container, Horizontal, Vertical, VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import TextArea, Input, Static, Label, OptionList
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
            "• [bold yellow]Ctrl + B[/bold yellow]       : AI Bug/Error Code Analysis\n"
            "• [bold yellow]Ctrl + T[/bold yellow]       : Toggle AI Chat Assistant Sidebar\n"
            "• [bold yellow]Ctrl + P[/bold yellow]       : Switch Color Theme (Carbon, OLED, Slate)\n"
            "• [bold yellow]Ctrl+Shift+C[/bold yellow]  : Copy Selected Text\n"
            "• [bold yellow]Ctrl+Shift+V[/bold yellow]  : Paste Clipboard Text\n"
            "• [bold yellow]Ctrl+Shift+X[/bold yellow]  : Cut Selected Text\n"
            "• [bold yellow]Tab[/bold yellow]           : Insert Indentation/Tab in Editor\n"
            "• [bold yellow]Ctrl + H[/bold yellow]       : Open This Help Dialog\n"
            "• [bold yellow]Ctrl + Q[/bold yellow]       : Quit Vieed\n"
            "• [bold yellow]Esc[/bold yellow]          : Dismiss Active Panels / Popups\n\n"
            "[dim]Press ESC or Ctrl+H to close this dialog.[/dim]"
        )
        with Container(id="help_dialog"):
            yield Static(help_text)

    def action_dismiss(self) -> None:
        self.app.pop_screen()


class ChatSidebar(Container):
    """Sidebar for the AI Q&A session based on the active code context."""

    def compose(self) -> ComposeResult:
        yield Label("[bold cyan]🤖 Vieed AI Assistant[/bold cyan]")
        yield Static("Press [bold]Ctrl+T[/bold] to close.", id="chat_hint")
        with VerticalScroll(id="chat_scroll_area"):
            yield Static("", id="chat_response")
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
        border: solid #00ffaf;
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

    #chat_scroll_area {
        height: 1fr;
        border: solid #333333;
        padding: 1;
        margin: 1 0;
    }

    #chat_hint {
        color: #666666;
    }

    #help_dialog {
        padding: 2;
        background: #1c1c1c;
        border: thick #00ffaf;
        width: 60;
        height: auto;
        align: center middle;
    }
    """

    BINDINGS = [
        Binding("ctrl+f", "toggle_search", "Search", show=True),
        Binding("ctrl+b", "analyze_error", "AI Bug Check", show=True),
        Binding("ctrl+t", "toggle_chat", "AI Chat", show=True),
        Binding("ctrl+p", "cycle_theme", "Switch Theme", show=True),
        Binding("ctrl+h", "show_help", "Help", show=True),
        Binding("ctrl+space", "trigger_autocomplete", "Autocomplete", show=True),
        Binding("ctrl+s", "save_file", "Save", show=True),
        Binding("ctrl+q", "quit", "Quit", show=True),
        Binding("ctrl+shift+c", "copy_text", "Copy", show=False),
        Binding("ctrl+shift+v", "paste_text", "Paste", show=False),
        Binding("ctrl+shift+x", "cut_text", "Cut", show=False),
        Binding("escape", "dismiss_panels", "Dismiss", show=False),
    ]

    THEMES = {
        "carbon": {"name": "Carbon", "bg": "#121212", "editor_bg": "#181818", "header_bg": "#222222", "border": "#333333", "accent": "#00ffaf"},
        "oled": {"name": "Pure OLED Monochrome", "bg": "#000000", "editor_bg": "#000000", "header_bg": "#111111", "border": "#222222", "accent": "#ffffff"},
        "slate": {"name": "Slate Gray", "bg": "#1a1c23", "editor_bg": "#212431", "header_bg": "#2d3142", "border": "#4f5d75", "accent": "#ffffff"},
    }

    def __init__(self, filename: str = None):
        super().__init__()
        self.filename = filename or "Untitled"
        self.detected_lang = "Plain Text"
        self.theme_keys = list(self.THEMES.keys())
        self.current_theme_index = 0
        self._chat_log: list[str] = []
        self.ollama_url = os.environ.get("VIEED_OLLAMA_URL", "http://localhost:11434/api/generate")
        self.default_model = os.environ.get("VIEED_MODEL", "qwen2.5-coder:1.5b")
        self.max_context_chars = 8000

    def compose(self) -> ComposeResult:
        with Container(id="viewport_container"):
            yield Static(f"Vieed | File: {self.filename} | Lang: {self.detected_lang}", id="header_bar")
            with Horizontal():
                with Vertical(id="main_pane"):
                    yield TextArea(id="editor_area", show_line_numbers=True)
                    yield OptionList(id="completion_popup")
                    yield Input(placeholder="Search text... (Enter: next, Esc: close)", id="search_bar")
                yield ChatSidebar(id="chat_sidebar")
            yield Static(" Ready | Ctrl+H: Help | Ctrl+P: Theme | Ctrl+T: AI Chat", id="status_bar")

    def on_mount(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        # Tab tidak lagi berpindah fokus ke chat, melainkan menyisipkan indentasi
        editor.can_focus_tab = False

        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    editor.text = f.read()
                self.notify(f"File '{self.filename}' loaded successfully.")
            except Exception as e:
                self.notify(f"Failed to read file: {e}", severity="error")

        self.detect_language()
        self.apply_theme(self.theme_keys[self.current_theme_index])

    def action_show_help(self) -> None:
        self.push_screen(HelpScreen())

    def action_copy_text(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        if editor.selected_text:
            self.copy_to_clipboard(editor.selected_text)
            self.set_status("📋 Text copied to clipboard.")

    def action_cut_text(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        if editor.selected_text:
            self.copy_to_clipboard(editor.selected_text)
            editor.replace("", editor.selection.start, editor.selection.end)
            self.set_status("✂️ Text cut to clipboard.")

    def action_paste_text(self) -> None:
        editor = self.query_one("#editor_area", TextArea)
        try:
            pasted_text = self.app.get_clipboard()
            if pasted_text:
                editor.insert(pasted_text)
                self.set_status("📌 Text pasted from clipboard.")
            else:
                self.set_status("⚠️ Clipboard is empty.")
        except Exception as e:
            self.set_status(f"❌ Failed to paste text: {e}")

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
        theme_name = self.THEMES[self.theme_keys[self.current_theme_index]]["name"]
        header = self.query_one("#header_bar", Static)
        header.update(
            f"Vieed | Author: vieexploit | File: {self.filename} | "
            f"Lang: {self.detected_lang} | Theme: {theme_name}"
        )

    def action_cycle_theme(self) -> None:
        self.current_theme_index = (self.current_theme_index + 1) % len(self.theme_keys)
        selected_key = self.theme_keys[self.current_theme_index]
        self.apply_theme(selected_key)
        self.set_status(f"🎨 Color scheme switched to: {self.THEMES[selected_key]['name']}")

    def apply_theme(self, theme_key: str) -> None:
        t = self.THEMES[theme_key]
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
            selected_text = editor.text

        if not selected_text.strip():
            self.set_status("⚠️ Editor is empty.")
            return

        self.set_status("🤖 AI is analyzing code for bugs/errors...")

        chat_sidebar = self.query_one("#chat_sidebar")
        if not chat_sidebar.has_class("visible"):
            chat_sidebar.add_class("visible")

        # PERBAIKAN BUG: Karakter C++ di-escape menggunakan escape() agar Rich Markup tidak crash
        user_prompt_log = f"[bold cyan]You (Bug Check):[/bold cyan]\nCheck this snippet:\n```\n{escape(selected_text)}\n```"
        self._chat_log.append(user_prompt_log)

        chat_box = self.query_one("#chat_response", Static)
        chat_scroll = self.query_one("#chat_scroll_area", VerticalScroll)
        chat_box.update("\n\n".join(self._chat_log))
        chat_scroll.scroll_end(animate=False)

        system_instruction = (
            f"Your Identity:\n"
            f"- You are 'Vieed AI', an embedded AI assistant inside Vieed (a smart offline TUI text editor created by vieexploit).\n"
            f"- You are powered by {self.default_model} developed by Alibaba Cloud.\n\n"
            f"Review this {self.detected_lang} snippet for bugs or potential issues. "
            f"Be concise, point out exact problems, and show fixed code:\n\n{selected_text}"
        )
        self.run_worker(partial(self._query_ollama, system_instruction, callback=self._handle_ai_analysis), thread=True)

    def _handle_ai_analysis(self, response_text: str) -> None:
        chat_box = self.query_one("#chat_response", Static)
        chat_scroll = self.query_one("#chat_scroll_area", VerticalScroll)

        # Respon AI juga di-escape agar sintaks/contoh kode aman dari parser Rich
        self._chat_log.append(f"[bold green]Vieed AI (Bug Analysis):[/bold green]\n{escape(response_text)}")
        chat_box.update("\n\n".join(self._chat_log))
        chat_scroll.scroll_end(animate=False)
        self.set_status("✨ AI Analysis complete.")

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
            chat_box = self.query_one("#chat_response", Static)
            chat_scroll = self.query_one("#chat_scroll_area", VerticalScroll)
            editor = self.query_one("#editor_area", TextArea)

            self._chat_log.append(f"[bold cyan]You:[/bold cyan] {escape(user_msg)}")
            chat_box.update("\n\n".join(self._chat_log))
            chat_scroll.scroll_end(animate=False)

            code_context = editor.text[:self.max_context_chars]
            prompt = (
                f"Your Identity System Prompt:\n"
                f"- You are 'Vieed AI', an embedded AI assistant built directly into Vieed, a smart offline TUI text editor created by vieexploit.\n"
                f"- You are powered by the underlying LLM model: {self.default_model} (developed by Alibaba Cloud).\n"
                f"- If asked who created you or what application this is, answer clearly that this editor is Vieed created by vieexploit, and your AI engine model is {self.default_model} by Alibaba.\n\n"
                f"Context code ({self.detected_lang}):\n```\n{code_context}\n```\n\n"
                f"User question: {user_msg}\n"
                f"Provide a helpful and concise answer in English."
            )
            self.set_status("🤖 Thinking...")
            self.run_worker(partial(self._query_ollama, prompt, callback=self._handle_chat_response), thread=True)

    def _handle_chat_response(self, response_text: str) -> None:
        chat_box = self.query_one("#chat_response", Static)
        chat_scroll = self.query_one("#chat_scroll_area", VerticalScroll)
        self._chat_log.append(f"[bold green]Vieed AI:[/bold green]\n{escape(response_text)}")
        chat_box.update("\n\n".join(self._chat_log))
        chat_scroll.scroll_end(animate=False)
        self.set_status("Ready")

    def _query_ollama(self, prompt: str, callback=None) -> None:
        try:
            payload = {
                "model": self.default_model,
                "prompt": prompt,
                "stream": False,
            }
            with httpx.Client(timeout=120.0) as client:
                res = client.post(self.ollama_url, json=payload)
                if res.status_code == 200:
                    text = res.json().get("response", "No response from model.")
                else:
                    text = f"Ollama Error (HTTP {res.status_code}): {res.text}"
        except Exception as e:
            text = f"Failed to connect to Ollama ({self.ollama_url}): {e}"

        if callback:
            self.call_from_thread(callback, text)


def main():
    filename = sys.argv[1] if len(sys.argv) > 1 else "Untitled"
    app = VieedEditor(filename=filename)
    app.run()


if __name__ == "__main__":
    main()
