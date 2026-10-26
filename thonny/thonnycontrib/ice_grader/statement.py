"""The Statement panel: the problem's PDF beside your code, drawn by pdfium (the pypdfium2 package), with Copy (the PDF
file itself, to paste into a chat or an AI), Save and Open buttons. Zoom works like the VS Code version: the buttons,
or Ctrl + mouse wheel, which zooms around the mouse; drag (or Shift + wheel) to move around a page wider than the panel."""
import os
import threading
import tkinter as tk
from tkinter import ttk

GAP = 10  # pixels around and between pages
MIN_ZOOM, MAX_ZOOM = 0.4, 4.0  # 1.0 = the pages fit the panel's width
# All pages together are drawn at most this many pixels (Tk keeps 4 bytes a pixel, so about 100 MB): a wide panel
# at a high zoom would otherwise take gigabytes.
MAX_PIXELS = 25_000_000
WHEEL_PX = 60  # pixels scrolled per notch of the mouse wheel
_pdfium = threading.Lock()  # pdfium is not thread-safe: one render at a time


def can_show_pdfs():
    try:
        import pypdfium2  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 - not installed, or no build for this computer
        return False


def _image_data(bitmap):
    """A pdfium bitmap as PPM (or PGM) bytes, which Tk's PhotoImage reads directly."""
    w, h, stride, n = bitmap.width, bitmap.height, bitmap.stride, bitmap.n_channels
    raw = bytes(bitmap.buffer)
    row = w * n
    if stride != row:
        raw = b"".join(raw[i * stride:i * stride + row] for i in range(h))
    if n == 1:
        return b"P5\n%d %d\n255\n" % (w, h) + raw
    if n == 4:  # drop the alpha channel
        rgb = bytearray(w * h * 3)
        rgb[0::3], rgb[1::3], rgb[2::3] = raw[0::4], raw[1::4], raw[2::4]
        raw = bytes(rgb)
    return b"P6\n%d %d\n255\n" % (w, h) + raw


def render_pdf(path, width, zoom=1.0, stale=lambda: False, max_pixels=MAX_PIXELS):
    """Every page at one scale, the widest page `width` pixels wide times zoom (less if all pages together would be
    over max_pixels) -> [(w, h, image data)], or None when stale() turns true first (a newer zoom wants another
    render). Safe to call from a worker thread."""
    import pypdfium2 as pdfium
    with _pdfium:
        if stale():
            return None
        pdf = pdfium.PdfDocument(path)
        try:
            sizes = [pdf.get_page_size(i) for i in range(len(pdf))]
            widest = max((w for w, h in sizes), default=0) or 595
            scale = width / widest * zoom
            pixels = sum(w * h for w, h in sizes) * scale * scale
            if pixels > max_pixels:
                scale *= (max_pixels / pixels) ** 0.5
            scale = max(0.2, min(8.0, scale))
            pages = []
            for i in range(len(pdf)):
                if stale():
                    return None
                page = pdf[i]
                bitmap = page.render(scale=scale, rev_byteorder=True)
                pages.append((bitmap.width, bitmap.height, _image_data(bitmap)))
                page.close()
            return pages
        finally:
            pdf.close()


def lay_out(sizes, area):
    """Pages stacked top to bottom and centred in a view `area` pixels wide -> ([(x, y, w, h)], width, height) of
    the whole. Pages wider than the view make the whole wider, to scroll sideways."""
    widest = max((w for w, h in sizes), default=0)
    width = area if widest + GAP <= area else widest + 2 * GAP
    boxes, y = [], GAP
    for w, h in sizes:
        boxes.append(((width - w) // 2, y, w, h))
        y += h + GAP
    return boxes, width, y


def spot_at(boxes, x, y):
    """What is at (x, y) as (page, fraction across, fraction down), to find the same spot after a zoom."""
    for i, (bx, by, w, h) in enumerate(boxes):
        if y < by + h + GAP or i == len(boxes) - 1:
            return i, (x - bx) / w, (y - by) / h
    return None


def position_of(boxes, spot):
    i, fx, fy = spot
    bx, by, w, h = boxes[min(i, len(boxes) - 1)]
    return bx + fx * w, by + fy * h


def wheel_steps(delta, windowing, tk_version):
    """Wheel notches in one <MouseWheel> event, up/away being positive; touchpads give fractions. Tk sends 120 per
    notch, except Tk 8.6 on macOS, which sends about 1."""
    return float(delta) if windowing == "aqua" and tk_version < 9 else delta / 120


class StatementView(ttk.Frame):
    def __init__(self, master):
        super().__init__(master)
        from . import statement_copy, statement_open, statement_save  # the plug-in's commands
        self.problem = None
        self.path = None
        self.loading = None  # the id of the problem whose statement is being fetched
        self.zoom = 1.0
        self.images = []
        self.boxes = []  # where each page is drawn: (x, y, w, h)
        self._size = (1, 1)  # of everything drawn
        self._anchor = None  # (view x, view y, spot) to keep in place on the next draw
        self.generation = 0
        self._width = 0
        self._drawn_width = 1  # the width the latest render was asked for (the pages' width at zoom 1)
        self._resize_job = None
        self._windowing = self.tk.call("tk", "windowingsystem")

        bar = ttk.Frame(self, padding=(6, 4, 6, 2))
        bar.pack(fill="x")
        self.title = ttk.Label(bar, text="No statement open", anchor="w")
        self.title.pack(side="left", fill="x", expand=True)
        buttons = ttk.Frame(self, padding=(6, 0, 6, 2))
        buttons.pack(fill="x")
        ttk.Button(buttons, text="−", width=3, command=lambda: self.set_zoom(self.zoom / 1.2)).pack(side="left")
        self.zoom_label = ttk.Label(buttons, text="100%", width=5, anchor="center")
        self.zoom_label.pack(side="left")
        self.zoom_label.bind("<Button-1>", lambda e: self.set_zoom(1.0))
        ttk.Button(buttons, text="+", width=3, command=lambda: self.set_zoom(self.zoom * 1.2)).pack(side="left")
        # A row of their own, as narrow as their words: Thonny's side panels start 15 em wide, too narrow for all six.
        actions = ttk.Frame(self, padding=(6, 0, 6, 2))
        actions.pack(fill="x")
        for text, command in (("Copy", lambda: statement_copy(self)), ("Save", lambda: statement_save(self)),
                              ("Open", lambda: statement_open(self))):
            button = ttk.Button(actions, text=text, width=0, command=command)
            button.pack(side="left", padx=(0 if text == "Copy" else 4, 0), fill="x", expand=True)
        self.note = ttk.Label(self, text="", padding=(8, 0, 6, 2))
        self.note.pack(fill="x")
        self.note.bind("<Configure>", lambda e: self.note.configure(wraplength=max(e.width - 14, 60)))

        middle = ttk.Frame(self)
        middle.pack(fill="both", expand=True)
        middle.rowconfigure(0, weight=1)
        middle.columnconfigure(0, weight=1)
        self.canvas = tk.Canvas(middle, background="#8a8a8a", highlightthickness=0, borderwidth=0)
        bar_y = ttk.Scrollbar(middle, orient="vertical", command=self.canvas.yview)
        self.bar_x = ttk.Scrollbar(middle, orient="horizontal", command=self.canvas.xview)
        self.canvas.configure(yscrollcommand=bar_y.set, xscrollcommand=self.bar_x.set)
        self.canvas.grid(row=0, column=0, sticky="nsew")
        bar_y.grid(row=0, column=1, sticky="ns")
        self.bar_x.grid(row=1, column=0, sticky="ew")
        self.bar_x.grid_remove()  # shown when a page is wider than the panel
        self.canvas.bind("<Configure>", self._resized)
        self.canvas.bind("<MouseWheel>", lambda e: self._wheel(e, wheel_steps(e.delta, self._windowing, tk.TkVersion)))
        self.canvas.bind("<Button-4>", lambda e: self._wheel(e, 1))  # Linux
        self.canvas.bind("<Button-5>", lambda e: self._wheel(e, -1))
        try:  # Tk 9's touchpad scrolling
            self.canvas.bind("<TouchpadScroll>", self._touchpad)
        except tk.TclError:
            pass
        for button in (1, 2, 3):  # drag with any button to move around, like right-drag in VS Code
            self.canvas.bind("<ButtonPress-%d>" % button, self._grab)
            self.canvas.bind("<B%d-Motion>" % button, self._drag)
            self.canvas.bind("<ButtonRelease-%d>" % button, lambda e: self.canvas.configure(cursor=""))
        self.message("Double-click a problem in the Grader panel to read its statement here.")

    # ---- what is shown

    def show(self, problem, path):
        same = self.path == path
        self.problem, self.path = problem, path
        self.title.configure(text=problem["code"])
        if not same:  # another statement: from the top, fitting the panel
            self.zoom = 1.0
            self.zoom_label.configure(text="100%")
            self.boxes, self._anchor = [], None
        self.render()

    def message(self, text):
        self.canvas.delete("all")
        self.images, self.boxes = [], []
        self.bar_x.grid_remove()
        self.canvas.create_text(GAP * 2, GAP * 2, text=text, anchor="nw", fill="white",
                                width=max(self.canvas.winfo_width() - GAP * 4, 150))
        self.canvas.configure(scrollregion=(0, 0, 1, 1))

    def flash(self, text):
        """A short note under the buttons, e.g. "Copied"."""
        self.note.configure(text=text)
        self.after(8000, lambda: self.note.cget("text") == text and self.note.configure(text=""))

    def set_zoom(self, zoom, at=None):
        """Zooms keeping what is at the view's point `at` (default: its middle) in place."""
        zoom = max(MIN_ZOOM, min(MAX_ZOOM, zoom))
        if abs(zoom - self.zoom) < 1e-9:
            return
        self.zoom = zoom
        self.zoom_label.configure(text="%d%%" % round(zoom * 100))
        if at is None:
            at = (self.canvas.winfo_width() / 2, self.canvas.winfo_height() / 2)
        self._anchor = self._spot(*at) or self._anchor
        self.render()

    def _spot(self, vx, vy):
        spot = self.boxes and spot_at(self.boxes, self.canvas.canvasx(vx), self.canvas.canvasy(vy))
        return (vx, vy, spot) if spot else None

    # ---- drawing (pages are drawn in a worker thread, then put on the canvas here)

    def render(self):
        """Draws the pages again (for a new statement, zoom or panel width). A newer render stops an older one."""
        if not self.path:
            return
        self.generation += 1  # also when nothing is drawn here: an older statement still being drawn is dropped
        width = self.canvas.winfo_width() - 2 * GAP
        if width < 60:  # not on screen yet: drawn when it gets its size (_resized)
            return
        if not self.path.lower().endswith(".pdf"):
            self.message("This statement isn't a PDF. Click Open to read it.")
            return
        generation, path, zoom, result = self.generation, self.path, self.zoom, {}
        self._drawn_width = width

        def work():
            try:
                result["pages"] = render_pdf(path, width, zoom, lambda: generation != self.generation)
            except Exception as e:  # noqa: BLE001 - shown in the panel
                result["error"] = e
        worker = threading.Thread(target=work, daemon=True)
        worker.start()
        self._wait(worker, generation, result)

    def _wait(self, worker, generation, result):
        if generation != self.generation:  # a newer render took over
            return
        if worker.is_alive():
            self.after(15, self._wait, worker, generation, result)
        elif "error" in result:
            self.message("Couldn't show this statement (%s). Click Open to read it in your PDF app." % result["error"])
        elif result.get("pages") == []:
            self.message("This statement has no pages. Click Open to read it in your PDF app.")
        elif result.get("pages"):
            self._draw(result["pages"])

    def _draw(self, pages):
        area = self.canvas.winfo_width()
        anchor = self._anchor or self._spot(0, 0)  # zoomed: keep the mouse's spot; else what is at the top-left
        self._anchor = None
        self.canvas.delete("all")
        self.images = [tk.PhotoImage(data=data, format="ppm") for w, h, data in pages]
        self.boxes, width, height = lay_out([(w, h) for w, h, _ in pages], area)
        # Pages too big to draw at the zoom asked for are drawn smaller: the % says how big they really are.
        drawn = max(w for w, h, _ in pages) / max(1, self._drawn_width)
        if drawn < self.zoom - 0.005:
            self.zoom = drawn
            self.zoom_label.configure(text="%d%%" % round(drawn * 100))
        for image, (x, y, w, h) in zip(self.images, self.boxes):
            self.canvas.create_image(x, y, image=image, anchor="nw")
        self._size = (width, max(height, self.canvas.winfo_height()))
        self.canvas.configure(scrollregion=(0, 0) + self._size)
        if width > area:
            self.bar_x.grid()
        else:
            self.bar_x.grid_remove()
        if anchor:
            vx, vy, spot = anchor
            x, y = position_of(self.boxes, spot)
            self._move_to(x - vx, y - vy)
        else:
            self._move_to(0, 0)

    def _move_to(self, left, top):
        """Scrolls so the view's top-left corner is at (left, top) of everything drawn."""
        width, height = self._size
        self.canvas.xview_moveto(left / width)
        self.canvas.yview_moveto(top / height)

    def _resized(self, event):
        if abs(event.width - self._width) < 8:
            return
        self._width = event.width
        if self._resize_job:
            self.after_cancel(self._resize_job)
        self._resize_job = self.after(250, self.render)

    # ---- mouse

    def _wheel(self, event, steps):
        aqua_command = self._windowing == "aqua" and event.state & 0x8
        if event.state & 0x4 or aqua_command:  # Ctrl + wheel: zoom around the mouse
            # (from the pointer itself: some Tk 8.6 builds give a wheel event's x and y in screen coordinates)
            at = (self.winfo_pointerx() - self.canvas.winfo_rootx(), self.winfo_pointery() - self.canvas.winfo_rooty())
            self.set_zoom(self.zoom * 1.1 ** max(-3, min(3, steps)), at)
        elif event.state & 0x1:  # Shift + wheel: sideways
            self._scroll(-steps * WHEEL_PX, 0)
        else:
            self._scroll(0, -steps * WHEEL_PX)
        return "break"

    def _touchpad(self, event):
        dx, dy = event.delta >> 16, ((event.delta & 0xFFFF) ^ 0x8000) - 0x8000
        self._scroll(-dx, -dy)
        return "break"

    def _scroll(self, dx, dy):
        if self.boxes:
            self._move_to(self.canvas.canvasx(0) + dx, self.canvas.canvasy(0) + dy)

    def _grab(self, event):
        self.canvas.scan_mark(event.x, event.y)

    def _drag(self, event):
        self.canvas.configure(cursor="fleur")
        self.canvas.scan_dragto(event.x, event.y, gain=1)

    def file_name(self):
        """The name the PDF gets when it is copied or saved: the problem's code."""
        from .layout import safe_name
        return safe_name(self.problem["code"]) + os.path.splitext(self.path)[1] if self.problem else None
