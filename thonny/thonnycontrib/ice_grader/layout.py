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
    a Windows device name, no dot at the end (Windows drops it) and at most 100 characters. The same as the VS Code
    version's safeName."""
    name = re.sub(r"[^\w\-.]+", "_", s, flags=re.ASCII)
    name = re.sub(r"^_|[_.]+$", "", re.sub(r"_+", "_", name)[:100])
    if not name:
        return "problem"
    return "_" + name if _DEVICE.match(name) else name


def is_exam(code):
    """Exam practice problems, e.g. 2025s1_Exam2_A1-1_Student or Exam1-2024_Q1A_student (not "Example")."""
    return bool(_EXAM.search(code))


def chapter_of(code, name="", spellings=None):
    """05_List_15 -> 05_List; exam problems go together by exam number: Exam1, Exam2, ... When the problem's name
    starts with another chapter number than its code, the name wins, as on the grader's page: code 09_MoreDC_12 named
    "10_TSD_★_Union Intersection" -> 10_TSD. The name may be written "10_TSD", "10-TSD", "10 TSD" or "10_★_...";
    "3.14 ..." is no chapter number. spellings (from chapter_spellings) makes every problem of one chapter number land
    in one group. The same as the VS Code version's chapterOf."""
    m = _EXAM_NUMBER.search(code)
    if m:
        return "Exam%d" % int(m.group(1))
    if is_exam(code):
        return "Exam"
    in_code = re.match(r"([0-9]+)_", code)
    in_name = re.match(r"([0-9]{1,2})(?![ _.\-]*[0-9])[ _.\-]+([a-zA-Z]*)", name or "")
    if in_code and in_name and int(in_code.group(1)) != int(in_name.group(1)):
        spelled = (spellings or {}).get(int(in_name.group(1)))
        return spelled or ("%s_%s" % in_name.groups() if in_name.group(2) else in_name.group(1))
    return "_".join(code.split("_")[:2]) or code


def chapter_spellings(problems):
    """Chapter number -> the one spelling to show, so "11_TSD", "11_tsd" and "11_★_..." don't become separate groups.
    A chapter that problem codes already use wins, then the spelling most names use."""
    tally = {}
    for p in problems:
        name = p.get("name", "")
        chapter = chapter_of(p["code"], name)
        m = re.match(r"([0-9]+)_", chapter)
        if m:
            seen = tally.setdefault(int(m.group(1)), {})
            seen[chapter] = seen.get(chapter, 0) + (1 if chapter != chapter_of(p["code"]) else 1000000)
    return {n: min(seen, key=lambda c: (-seen[c], c)) for n, seen in tally.items()}


def solution_path(root, code, ext=".py", name="", spellings=None):
    """New solution file: <root>/<chapter>/<code>.py"""
    return os.path.join(root, safe_name(chapter_of(code, name, spellings)), safe_name(code) + ext)
