"""AI explain (against a fake Gemini, never the real one), copying a file to the clipboard, drawing statements."""
import os
import shutil
import subprocess
import tempfile
import threading
import time
import tkinter as tk
import unittest
from tkinter import font as tkfont
from tkinter import ttk
from unittest import mock

from thonnycontrib.ice_grader import statement
from thonnycontrib.ice_grader.ai import CODE_REMOVED, AIError, build_prompt, call_gemini, without_code
from thonnycontrib.ice_grader.clipboard import copy_command, copy_file
from thonnycontrib.ice_grader.core import Core
from thonnycontrib.ice_grader.passwords import MemorySecrets
from thonnycontrib.ice_grader.statement import (GAP, StatementView, can_show_pdfs, lay_out, position_of, render_pdf,
                                                spot_at, wheel_steps)

FAILURE = {"n": 2, "verdict": "FAIL", "input": "3\n", "expected": "6\n", "actual": "5\n", "stderr": ""}


def answer(text):
    return 200, {"candidates": [{"content": {"parts": [{"text": "thinking...", "thought": True}, {"text": text}]}}]}


class FakeGemini:
    def __init__(self, *replies):
        self.replies = list(replies)
        self.asked = []

    def __call__(self, key, model, body):
        self.asked.append((model, body))
        return self.replies.pop(0)


class Explain(unittest.TestCase):
    def test_the_prompt_has_the_code_the_failing_tests_and_where_they_differ(self):
        prompt = build_prompt("n = int(input())\nprint(n + 2)\n", [FAILURE] * 4, 4, {"code": "05_List_15", "name": "Sum"},
                              {"data.txt": "1 2"})
        self.assertIn("Problem: 05_List_15 - Sum", prompt)
        self.assertIn("print(n + 2)", prompt)
        self.assertIn("data.txt:", prompt)
        self.assertIn("Failing tests (3 of 4 shown):", prompt)
        self.assertIn("(First difference from expected: line 1, column 1)", prompt)

    def test_no_code_comes_back(self):
        self.assertEqual(without_code("Line 2 adds 2.\n```python\nprint(n * 2)\n```\nUse `n`.\n```\nx"),
                         "Line 2 adds 2.\n%s\n\nUse `n`.\n%s" % (CODE_REMOVED, CODE_REMOVED))

    def test_the_answer_without_its_thinking(self):
        gemini = FakeGemini(answer("Line 2 adds 2 instead of doubling."))
        r = call_gemini("key", ["m1", "m2"], "prompt", send=gemini, sleep=lambda s: None)
        self.assertEqual(r, {"text": "Line 2 adds 2 instead of doubling.", "model": "m1", "fallback": False})
        body = gemini.asked[0][1]
        self.assertIn("Do not write any code", body["systemInstruction"]["parts"][0]["text"])
        self.assertEqual(body["generationConfig"]["thinkingConfig"], {"thinkingLevel": "low"})

    def test_busy_gemini_is_retried_then_the_fallback_model_answers(self):
        busy = (503, {"error": {"message": "overloaded"}})
        gemini = FakeGemini(busy, busy, busy, answer("ok"))
        waits = []
        r = call_gemini("key", ["m1", "m2"], "prompt", send=gemini, sleep=waits.append)
        self.assertEqual((r["model"], r["fallback"]), ("m2", True))
        self.assertEqual([m for m, _ in gemini.asked], ["m1", "m1", "m1", "m2"])
        self.assertEqual(waits, [2, 5])

    def test_a_model_without_thinking_levels_is_asked_again_without(self):
        gemini = FakeGemini((400, {"error": {"message": "thinking level is not supported"}}), answer("ok"))
        call_gemini("key", ["m1"], "prompt", send=gemini, sleep=lambda s: None)
        self.assertNotIn("thinkingConfig", gemini.asked[1][1]["generationConfig"])

    def test_errors_say_what_to_do(self):
        for reply, words in [((400, {"error": {"message": "API key not valid"}}), "Invalid Gemini API key"),
                             ((429, {}), "limit"), ((200, {"promptFeedback": {"blockReason": "SAFETY"}}), "blocked"),
                             ((200, {"candidates": []}), "no explanation")]:
            with self.assertRaisesRegex(AIError, words):
                call_gemini("key", ["m1"], "prompt", send=FakeGemini(reply), sleep=lambda s: None)


class Clipboard(unittest.TestCase):
    def test_the_command_for_each_system(self):
        self.assertIn("Set-Clipboard -LiteralPath $env:ICE_FILE", copy_command("win32")[0][-1])
        self.assertIn("POSIX file", copy_command("darwin")[0][-1])
        self.assertIn("wl-copy", copy_command("linux", {"WAYLAND_DISPLAY": "wayland-0"})[0][-1])
        self.assertIn("xclip", copy_command("linux", {})[0][-1])

    def test_the_file_goes_in_the_environment_not_the_command(self):
        seen = []

        def run(cmd, env, **kw):
            seen.append((cmd, env["ICE_FILE"], env["ICE_URI"]))
            return subprocess.CompletedProcess(cmd, 0, None, b"")
        copy_file("/tmp/a b.pdf", "linux", run)
        cmd, path, uri = seen[0]
        self.assertTrue(path.endswith("a b.pdf") and uri.startswith("file:") and "a%20b.pdf" in uri)
        self.assertNotIn("a b.pdf", " ".join(cmd))
        odd = os.path.abspath(os.path.join("it's \"$HOME\" & [x] `y` %TEMP%", "โจทย์ 1.pdf"))
        for platform in ("win32", "darwin", "linux"):
            seen.clear()
            copy_file(odd, platform, run)
            cmd, path, uri = seen[0]
            self.assertEqual((cmd, path), (copy_command(platform)[0], odd))  # the command never changes
            self.assertNotIn("โจทย์", uri)  # percent-encoded for the file managers that read it

    @unittest.skipUnless(shutil.which("sh"), "needs sh")
    def test_a_copy_tool_that_stays_in_the_background_does_not_hold_up_copy(self):
        # Like xclip: it forks a process that stays to hand the file to whoever pastes, and that process keeps the
        # output it was given. This stand-in never touches the real clipboard.
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with open(os.path.join(d, "xclip"), "w", newline="\n") as f:
            f.write("#!/bin/sh\ncat > /dev/null\n(sleep 4) &\nexit 0\n")
        os.chmod(os.path.join(d, "xclip"), 0o755)
        with mock.patch.dict(os.environ, {"PATH": d + os.pathsep + os.environ["PATH"]}):
            start = time.time()
            copy_file(os.path.join(d, "x.pdf"), "linux")
        self.assertLess(time.time() - start, 3)

    def test_a_missing_tool_is_named(self):
        def run(cmd, **kw):
            raise FileNotFoundError(cmd[0])
        with self.assertRaisesRegex(OSError, "xclip is not installed"):
            copy_file("/tmp/x.pdf", "linux", run)


@unittest.skipUnless(can_show_pdfs(), "pypdfium2 is not installed")
class Statement(unittest.TestCase):
    def setUp(self):
        import pypdfium2 as pdfium
        self.dir = tempfile.mkdtemp()
        self.path = os.path.join(self.dir, "s.pdf")
        pdf = pdfium.PdfDocument.new()
        pdf.new_page(600, 800)
        pdf.new_page(600, 800)
        pdf.save(self.path)
        pdf.close()

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def test_every_page_is_drawn_to_the_width_asked_for_as_an_image_tk_can_read(self):
        pages = render_pdf(self.path, 300)
        self.assertEqual([(w, h) for w, h, _ in pages], [(300, 400), (300, 400)])
        data = pages[0][2]
        self.assertTrue(data.startswith(b"P6\n300 400\n255\n"))
        self.assertEqual(len(data), len(b"P6\n300 400\n255\n") + 300 * 400 * 3)
        self.assertEqual([(w, h) for w, h, _ in render_pdf(self.path, 300, zoom=2)], [(600, 800), (600, 800)])

    def test_pages_of_different_sizes_keep_their_proportions_and_a_newer_zoom_stops_a_render(self):
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(self.path)
        pdf.new_page(300, 400)
        pdf.save(self.path + "2")
        pdf.close()
        self.assertEqual([(w, h) for w, h, _ in render_pdf(self.path + "2", 300)], [(300, 400), (300, 400), (150, 200)])
        self.assertIsNone(render_pdf(self.path, 300, stale=lambda: True))


class StatementPanel(unittest.TestCase):
    """The real panel, in a window that is never shown."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        self.root.withdraw()
        self.view = StatementView(self.root)
        self.view.canvas.winfo_width = lambda: 400  # as if it were on screen
        self.view.canvas.winfo_height = lambda: 300

    def tearDown(self):
        self.root.destroy()

    def test_a_pdf_still_being_drawn_does_not_cover_a_statement_opened_since(self):
        go = threading.Event()

        def slow_render(path, width, zoom=1.0, stale=lambda: False):
            go.wait(5)
            return None if stale() else [(2, 2, b"P6\n2 2\n255\n" + bytes(12))]
        with mock.patch.object(statement, "render_pdf", slow_render):
            self.view.show({"id": "1", "code": "A_1"}, os.path.join("a", "statement.pdf"))
            self.view.show({"id": "2", "code": "B_2"}, os.path.join("b", "statement.html"))
            go.set()
            end = time.time() + 1
            while time.time() < end:
                self.root.update()
        self.assertEqual([self.view.canvas.type(i) for i in self.view.canvas.find_all()], ["text"])  # the "not a PDF" note


class NarrowPanels(unittest.TestCase):
    """Thonny makes side panels 15 em wide (about 150 pixels): every button, the list's scroll bar and its status
    column must show."""

    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError:
            self.skipTest("no display")
        ttk.Style(self.root).theme_use("clam")  # what Thonny's own themes build on
        self.width = 15 * tkfont.nametofont("TkDefaultFont").measure("m")  # like Thonny's ems_to_pixels(15)
        self.root.geometry("%dx420-3000-3000" % self.width)  # on screen for Tk, but out of sight
        self.root.attributes("-alpha", 0.0)

    def tearDown(self):
        self.root.destroy()

    def shown(self, widget):
        widget.pack(fill="both", expand=True)
        self.root.update()
        widgets, todo = [], [widget]
        while todo:
            w = todo.pop()
            widgets.append(w)
            todo.extend(w.winfo_children())
        return widgets

    def test_every_statement_button_shows(self):
        buttons = [w for w in self.shown(StatementView(self.root)) if w.winfo_class() == "TButton"]
        self.assertEqual(len(buttons), 5)
        right = self.root.winfo_rootx() + self.width
        for b in buttons:
            self.assertTrue(b.winfo_ismapped() and b.winfo_rootx() + b.winfo_width() <= right, b.cget("text"))

    def test_the_problem_list_shows_its_scroll_bar_and_status_column(self):
        import thonnycontrib.ice_grader as ig
        d = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, d, True)
        with mock.patch.object(ig, "_core", Core(d, "https://grader.test/", secrets=MemorySecrets())):
            view = ig.GraderView(self.root)
        bars = [w for w in self.shown(view) if w.winfo_class() == "TScrollbar"]
        self.assertTrue(bars[0].winfo_ismapped() and bars[0].winfo_width() > 5)
        tree = view.tree  # the tree doesn't narrow its columns to fit: they must start narrow enough
        self.assertLessEqual(tree.column("#0", "width") + tree.column("status", "width"), tree.winfo_width())


class Zoom(unittest.TestCase):
    """The Statement panel's layout and zoom, without a screen: what is under the mouse stays under it."""

    def test_pages_are_centred_and_a_page_wider_than_the_panel_scrolls_sideways(self):
        boxes, width, height = lay_out([(300, 400), (150, 200)], 400)
        self.assertEqual((boxes, width, height), ([(50, GAP, 300, 400), (125, 420, 150, 200)], 400, 630))
        boxes, width, _ = lay_out([(900, 1200)], 400)
        self.assertEqual((boxes[0][0], width), (GAP, 900 + 2 * GAP))

    def test_the_spot_under_the_mouse_is_found_again_after_zooming(self):
        before, _, _ = lay_out([(300, 400), (300, 400)], 320)
        spot = spot_at(before, 160, 600)  # second page, a little below its top, in the middle
        self.assertEqual(spot[0], 1)
        after, _, _ = lay_out([(600, 800), (600, 800)], 320)
        self.assertEqual([round(v, 6) for v in position_of(after, spot)], [GAP + 300, 820 + 2 * (600 - 420)])
        self.assertEqual(spot_at(before, 160, 5000)[0], 1)  # below everything: the last page

    def test_wheel_notches(self):
        self.assertEqual(wheel_steps(120, "win32", 8.6), 1)
        self.assertEqual(wheel_steps(-30, "win32", 8.6), -0.25)  # a touchpad
        self.assertEqual(wheel_steps(-2, "aqua", 8.6), -2)
        self.assertEqual(wheel_steps(240, "aqua", 9.0), 2)


if __name__ == "__main__":
    unittest.main()
