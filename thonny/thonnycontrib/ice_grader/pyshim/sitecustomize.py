# Python loads this by itself before the student's program, during a local test that has data files.
# open("/data/x.txt") then reads the local copy of the problem's data file, as it would on the grader.
# Any other path, and a /data/ file the problem doesn't have, behaves as usual. Same file in the VS Code extension.
import builtins
import io
import os

_folder = os.environ.get("ICE_GRADER_DATA")

if _folder:
    _real_open = builtins.open

    def _local(file):
        if isinstance(file, str) and file.replace("\\", "/").startswith("/data/"):
            name = os.path.basename(file.replace("\\", "/"))
            copy = os.path.join(_folder, name.rstrip(". ") if os.name == "nt" else name)
            if os.path.isfile(copy):
                return copy
        return file

    def open(file, *args, **kwargs):
        return _real_open(_local(file), *args, **kwargs)

    builtins.open = open
    io.open = open
