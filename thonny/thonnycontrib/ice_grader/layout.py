"""Problem codes: grouping into chapters, and where solution files go."""
import os
import re

# ASCII letters and digits only, like the VS Code version (re.I alone would also take e.g. the Kelvin sign as a "k",
# and \d Thai digits)
_EXAM = re.compile(r"(?<![a-zA-Z])(?i:exam)(?![a-zA-Z])")
_EXAM_NUMBER = re.compile(r"(?<![a-zA-Z])(?i:exam)[\s_-]*([0-9]+)")
_DEVICE = re.compile(r"(con|prn|aux|nul|com[0-9]|lpt[0-9])(\.|$)", re.I)  # Windows device names (CON, NUL.py, ...)


def safe_name(s):
    """A file or folder name made from a problem code. Never "." or ".." (or empty), which would point outside, never
    a Windows device name, and no dot at the end (Windows drops it). The same as the VS Code version's safeName."""
    name = re.sub(r"[^\w\-.]+", "_", s, flags=re.ASCII)
    name = re.sub(r"_+", "_", name).strip("_").rstrip(".")
    if not name:
        return "problem"
    return "_" + name if _DEVICE.match(name) else name


def is_exam(code):
    """Exam practice problems, e.g. 2025s1_Exam2_A1-1_Student or Exam1-2024_Q1A_student (not "Example")."""
    return bool(_EXAM.search(code))


def chapter_of(code):
    """05_List_15 -> 05_List; exam problems go together by exam number: Exam1, Exam2, ..."""
    m = _EXAM_NUMBER.search(code)
    if m:
        return "Exam%d" % int(m.group(1))
    if is_exam(code):
        return "Exam"
    return "_".join(code.split("_")[:2]) or code


def solution_path(root, code, ext=".py"):
    """New solution file: <root>/<chapter>/<code>.py"""
    return os.path.join(root, safe_name(chapter_of(code)), safe_name(code) + ext)
