"""Native desktop workspace for Brighten the Dark."""
from concurrent.futures import ThreadPoolExecutor
import csv
import json
import math
import os
from pathlib import Path
import subprocess
import sys
import time
import tkinter as tk
from tkinter import filedialog, simpledialog, ttk
from urllib.error import HTTPError, URLError

import cv2
import numpy as np
from PIL import Image, ImageTk

from .project_io import load_image, save_png, write_csv
from .scene import preview
from .start_dashboard import test_video
from .studio_analysis import (METHODS, ask_openai, choose_scene, compare, enhance,
                              heatmap, settings_context, video_exposure)

ROOT = Path(__file__).resolve().parents[1]
INPUTS = ROOT / "data" / "originals"
VIDEOS = ROOT / "data" / "video"
RESULTS = ROOT / "outputs"
VIDEO_TYPES = {".mp4", ".mov", ".m4v", ".webm", ".avi", ".mkv"}
IMAGE_TYPES = {".jpg", ".jpeg", ".png", ".bmp", ".webp", ".tif", ".tiff"}

BG, PANEL, SURFACE = "#111521", "#192131", "#202b40"
TEXT, MUTED, MINT, BLUE, LINE = "#f2f6ff", "#aab8d2", "#9af0cc", "#93aaff", "#34425d"

SCORE_NAMES = {
    "Entropy_bits": "Entropy (bits)", "Mean_brightness": "Mean brightness",
    "Std_contrast": "Contrast (std. dev.)", "AMBE_vs_input": "Brightness error",
    "PSNR_vs_input_dB": "PSNR vs input (dB)", "SSIM_vs_input": "SSIM vs input",
}


def score_text(value):
    if isinstance(value, (int, float, np.number)):
        return "∞" if not math.isfinite(value) else f"{value:,.3f}"
    return str(value)


def csv_rows(path):
    with path.open(newline="", encoding="utf-8") as stream:
        reader = csv.DictReader(stream)
        return list(reader.fieldnames or []), list(reader)


def layout_columns(parent, widths):
    for index, (weight, minimum) in enumerate(widths):
        parent.columnconfigure(index, weight=weight, minsize=minimum)


class Picture(tk.Canvas):
    def __init__(self, parent):
        super().__init__(parent, bg="#0b0e17", highlightthickness=0)
        self.image = None
        self.photo = None
        self.bind("<Configure>", self.paint)

    def show(self, image):
        self.image = image
        self.paint()

    def paint(self, _event=None):
        if self.image is None or min(self.winfo_width(), self.winfo_height()) < 3:
            return
        height, width = self.image.shape[:2]
        scale = min(self.winfo_width() / width, self.winfo_height() / height)
        size = (max(1, int(width * scale)), max(1, int(height * scale)))
        resized = cv2.resize(self.image, size, interpolation=cv2.INTER_AREA if scale < 1 else cv2.INTER_LINEAR)
        if resized.ndim == 3:
            resized = cv2.cvtColor(resized, cv2.COLOR_BGR2RGB)
        self.photo = ImageTk.PhotoImage(Image.fromarray(resized))
        self.delete("all")
        self.create_image(self.winfo_width() / 2, self.winfo_height() / 2, image=self.photo)


class Plot(tk.Canvas):
    def __init__(self, parent, height=100):
        super().__init__(parent, bg=BG, height=height, highlightthickness=0)
        self.series = []
        self.x_label = ""
        self.action = None
        self.x_max = 0
        self.bind("<Configure>", self.paint)
        self.bind("<Button-1>", self.jump)

    def set(self, series, x_label, action=None):
        self.series, self.x_label, self.action = series, x_label, action
        self.paint()

    def jump(self, event):
        if self.action and self.x_max and self.winfo_width() > 60:
            self.action(np.clip((event.x - 46) / (self.winfo_width() - 59), 0, 1) * self.x_max)

    def paint(self, _event=None):
        self.delete("all")
        width, height = self.winfo_width(), self.winfo_height()
        values = [(x, y) for _, _, group in self.series for x, y in group if y is not None]
        if not values or width < 95 or height < 55:
            return
        self.x_max = max(x for x, _ in values) or 1
        minimum = min(0, min(y for _, y in values))
        maximum = max(y for _, y in values)
        maximum = max(maximum, minimum + .0001)
        left, top, right, bottom = 46, 24, width - 13, height - 23
        for fraction in (0, .5, 1):
            y = bottom - fraction * (bottom - top)
            self.create_line(left, y, right, y, fill=LINE)
            self.create_text(left - 5, y, text=f"{minimum + fraction * (maximum - minimum):.3g}",
                             anchor="e", fill=MUTED, font=("Helvetica Neue", 9))
        for offset, (name, color, group) in enumerate(self.series):
            self.create_text(left + offset * 112, 13, text=name, anchor="w", fill=color,
                             font=("Helvetica Neue", 10, "bold"))
            previous = None
            for x, y in group:
                if y is None:
                    previous = None
                    continue
                point = (left + x / self.x_max * (right - left),
                         bottom - (y - minimum) / (maximum - minimum) * (bottom - top))
                if previous:
                    self.create_line(*previous, *point, fill=color, width=1.5)
                previous = point
        self.create_text(left, height - 11, text="0", anchor="w", fill=MUTED)
        self.create_text(right, height - 11, text=f"{self.x_max:g} {self.x_label}",
                         anchor="e", fill=MUTED, font=("Helvetica Neue", 9))


def table_widget(parent, height=10):
    box = ttk.Frame(parent, style="Panel.TFrame")
    tree = ttk.Treeview(box, show="headings", height=height)
    vertical = ttk.Scrollbar(box, orient="vertical", command=tree.yview)
    horizontal = ttk.Scrollbar(box, orient="horizontal", command=tree.xview)
    tree.configure(yscrollcommand=vertical.set, xscrollcommand=horizontal.set)
    box.columnconfigure(0, weight=1)
    box.rowconfigure(0, weight=1)
    tree.grid(row=0, column=0, sticky="nsew")
    vertical.grid(row=0, column=1, sticky="ns")
    horizontal.grid(row=1, column=0, sticky="ew")
    return box, tree


def fill_table(tree, columns, records, headings=None):
    tree.delete(*tree.get_children())
    tree["columns"] = columns
    for column in columns:
        tree.heading(column, text=(headings or {}).get(column, column.replace("_", " ")))
        tree.column(column, width=170 if column in ("image", "method", "metric") else 114, stretch=True)
    for index, record in enumerate(records):
        tree.insert("", "end", iid=str(index), values=[score_text(record.get(key, "")) for key in columns],
                    tags=("stripe",) if index % 2 else ())
    tree.tag_configure("stripe", background="#1d293d")


class Studio:
    def __init__(self, root):
        self.root = root
        root.title("Brighten the Dark  ·  Studio")
        root.configure(bg=BG)
        root.geometry("1240x815")
        root.minsize(930, 685)
        root.protocol("WM_DELETE_WINDOW", self.close)
        self.views = {}
        self.nav = {}
        self.pool = ThreadPoolExecutor(max_workers=2)
        self.status = tk.StringVar(value="Ready")
        self.view = ""
        self.last_lab = "Image Lab"
        self.context = {}
        self.video_capture = None
        self.enhanced_capture = None
        self.playing = False
        self.play_job = None
        self.video_frame = 0
        self.video_adjusting = False
        self.video_samples = []
        self.history = []
        self.api_key = os.environ.get("OPENAI_API_KEY", "").strip()
        self.image_pending = None
        self.configure_theme()
        self.build_shell()
        self.build_images()
        self.build_videos()
        self.build_scores()
        self.build_files()
        self.build_assistant()
        self.show("Image Lab")
        if self.image_path:
            self.status.set(f"{self.image_path.name}  ·  Image Lab ready")
        for number, name in enumerate(self.nav, 1):
            modifier = "Command" if sys.platform == "darwin" else "Control"
            self.root.bind(f"<{modifier}-Key-{number}>", lambda _, tab=name: self.show(tab))

    def configure_theme(self):
        style = ttk.Style(self.root)
        style.theme_use("clam")
        base = ("Helvetica Neue", 12)
        style.configure(".", background=BG, foreground=TEXT, fieldbackground=SURFACE,
                        bordercolor=LINE, font=base)
        style.configure("TFrame", background=BG)
        style.configure("Panel.TFrame", background=PANEL)
        style.configure("TLabel", background=BG, foreground=TEXT)
        style.configure("Panel.TLabel", background=PANEL, foreground=TEXT)
        style.configure("Muted.TLabel", background=BG, foreground=MUTED, font=("Helvetica Neue", 11))
        style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Helvetica Neue", 27, "bold"))
        style.configure("Section.TLabel", background=PANEL, foreground=TEXT, font=("Helvetica Neue", 13, "bold"))
        style.configure("TButton", background=SURFACE, foreground=TEXT, padding=(11, 7), borderwidth=1)
        style.map("TButton", background=[("active", "#344665"), ("disabled", PANEL)],
                  foreground=[("disabled", MUTED)])
        style.configure("Accent.TButton", background=MINT, foreground="#11251f", font=("Helvetica Neue", 12, "bold"))
        style.map("Accent.TButton", background=[("active", "#baf7df"), ("disabled", SURFACE)],
                  foreground=[("disabled", MUTED)])
        style.configure("Nav.TButton", anchor="w", background=PANEL, padding=(13, 11))
        style.configure("Selected.Nav.TButton", anchor="w", background="#29463e", foreground=MINT, padding=(13, 11))
        style.configure("TCombobox", fieldbackground=SURFACE, background=SURFACE, foreground=TEXT, padding=4)
        style.map("TCombobox", fieldbackground=[("readonly", SURFACE)], foreground=[("readonly", TEXT)],
                  selectbackground=[("readonly", SURFACE)], selectforeground=[("readonly", TEXT)])
        self.root.option_add("*TCombobox*Listbox.background", SURFACE)
        self.root.option_add("*TCombobox*Listbox.foreground", TEXT)
        self.root.option_add("*TCombobox*Listbox.selectBackground", "#36516a")
        style.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=TEXT,
                        rowheight=25, borderwidth=0)
        style.configure("Treeview.Heading", background=SURFACE, foreground=TEXT, padding=6)
        style.map("Treeview", background=[("selected", "#335767")], foreground=[("selected", TEXT)])
        style.configure("Horizontal.TScale", background=PANEL, troughcolor=LINE, sliderthickness=16)

    def build_shell(self):
        rail = ttk.Frame(self.root, style="Panel.TFrame", padding=(12, 20))
        rail.pack(side="left", fill="y")
        ttk.Label(rail, text="BRIGHTEN", style="Section.TLabel").pack(anchor="w", padx=12)
        ttk.Label(rail, text="The Dark  /  Studio", style="Panel.TLabel").pack(anchor="w", padx=12, pady=(3, 24))
        for name in ("Image Lab", "Video Lab", "Scores", "Project Files", "Assistant"):
            button = ttk.Button(rail, text=name, width=16, style="Nav.TButton", command=lambda n=name: self.show(n))
            button.pack(fill="x", pady=3)
            self.nav[name] = button
        ttk.Button(rail, text="Open project folder", style="Nav.TButton",
                   command=lambda: self.open_file(ROOT)).pack(side="bottom", fill="x")
        body = ttk.Frame(self.root, padding=(17, 13, 17, 8))
        body.pack(side="left", fill="both", expand=True)
        ttk.Label(body, textvariable=self.status, style="Muted.TLabel").pack(side="bottom", fill="x", pady=(5, 0))
        self.stack = ttk.Frame(body)
        self.stack.pack(fill="both", expand=True)
        self.stack.rowconfigure(0, weight=1)
        self.stack.columnconfigure(0, weight=1)

    def page(self, name, subtitle):
        frame = ttk.Frame(self.stack)
        frame.grid(row=0, column=0, sticky="nsew")
        header = ttk.Frame(frame)
        header.pack(fill="x", pady=(3, 13))
        ttk.Label(header, text=name, style="Title.TLabel").pack(anchor="w")
        ttk.Label(header, text=subtitle, style="Muted.TLabel").pack(anchor="w", pady=(3, 0))
        self.views[name] = frame
        return frame

    def show(self, name):
        if name != "Video Lab":
            self.pause_video()
        if name in ("Image Lab", "Video Lab", "Scores", "Project Files"):
            self.last_lab = name
        self.view = name
        self.views[name].tkraise()
        for label, button in self.nav.items():
            button.configure(style="Selected.Nav.TButton" if label == name else "Nav.TButton")
        if name == "Scores":
            self.refresh_scores()
        elif name == "Project Files":
            self.list_files()
        elif name == "Assistant":
            self.assistant_context.set(f"Context · {self.last_lab}")

    def panel(self, parent, title=None, pad=9):
        frame = ttk.Frame(parent, style="Panel.TFrame", padding=pad)
        if title:
            ttk.Label(frame, text=title, style="Section.TLabel").pack(anchor="w", pady=(0, 5))
        return frame

    def dropdown(self, parent, items, initial, callback, width=21):
        combo = ttk.Combobox(parent, values=items, state="readonly", width=width)
        combo.set(initial)
        combo.bind("<<ComboboxSelected>>", lambda _: callback())
        return combo

    def task(self, label, work, done, button=None):
        self.status.set(label)
        if button:
            button.state(["disabled"])
        future = self.pool.submit(work)

        def poll():
            if not future.done():
                self.root.after(75, poll)
                return
            if button:
                button.state(["!disabled"])
            try:
                result = future.result()
                done(result)
            except HTTPError as error:
                self.status.set(f"OpenAI request failed (HTTP {error.code}).")
            except URLError as error:
                self.status.set(f"Network request failed: {error.reason}")
            except Exception as error:
                self.status.set(str(error))

        self.root.after(75, poll)

    def open_file(self, path):
        if sys.platform == "darwin":
            subprocess.Popen(["open", str(path)])
        else:
            subprocess.Popen(["xdg-open", str(path)])

    def pick_file(self, title, extensions):
        return filedialog.askopenfilename(parent=self.root, title=title,
                                          filetypes=[("Supported media", " ".join(f"*{x}" for x in sorted(extensions))),
                                                     ("All files", "*")])

    def build_images(self):
        page = self.page("Image Lab", "Tune an enhancement and inspect the result, histogram and exposure metrics in real time.")
        self.image_sources = {p.name: p for p in sorted(INPUTS.glob("*")) if p.suffix.lower() in IMAGE_TYPES}
        top = self.panel(page)
        top.pack(fill="x", pady=(0, 8))
        self.image_selector = self.dropdown(top, list(self.image_sources), next(iter(self.image_sources), ""),
                                             self.select_image, 27)
        self.image_selector.pack(side="left", padx=(0, 7))
        ttk.Button(top, text="Open image…", command=self.import_image).pack(side="left")
        self.image_method = self.dropdown(top, METHODS, METHODS[0], self.adjust_image)
        self.image_method.pack(side="right")
        layout = ttk.Frame(page)
        layout.pack(fill="both", expand=True)
        layout_columns(layout, [(1, 0), (0, 260)])
        layout.rowconfigure(0, weight=1)
        left = self.panel(layout)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.image_display = self.dropdown(left, ("Split", "Original", "Enhanced", "Difference heatmap"),
                                           "Split", self.paint_image, 19)
        self.image_display.pack(anchor="w", pady=(0, 6))
        self.image_picture = Picture(left)
        self.image_picture.pack(fill="both", expand=True)
        self.split = tk.DoubleVar(value=50)
        ttk.Scale(left, from_=0, to=100, variable=self.split, command=lambda _: self.paint_image()).pack(fill="x", pady=4)
        self.hist = Plot(left, 117)
        self.hist.pack(fill="x")
        right = self.panel(layout, "Enhancement controls")
        right.grid(row=0, column=1, sticky="nsew")
        self.image_controls = {}
        self.image_scales = {}
        for key, label, low, high, initial in (
            ("clip", "CLAHE clip", 1., 8., 2.),
            ("tiles", "Tile count", 2., 16., 8.),
            ("strength", "Shadow lift", 0., 1., .85),
            ("gamma", "Gamma", .6, 3., 1.65),
        ):
            value = tk.DoubleVar(value=initial)
            caption = tk.StringVar()
            ttk.Label(right, textvariable=caption, style="Panel.TLabel").pack(anchor="w")
            scale = ttk.Scale(right, from_=low, to=high, variable=value, command=lambda _: self.adjust_image())
            scale.pack(fill="x", pady=(0, 3))
            self.image_controls[key] = (value, caption, label)
            self.image_scales[key] = scale
        self.image_info = tk.StringVar()
        ttk.Label(right, textvariable=self.image_info, style="Panel.TLabel", wraplength=233).pack(anchor="w", pady=(2, 7))
        buttons = ttk.Frame(right, style="Panel.TFrame")
        buttons.pack(fill="x", pady=(0, 7))
        ttk.Button(buttons, text="Save PNG", style="Accent.TButton", command=self.export_image).pack(side="left")
        ttk.Button(buttons, text="Save metrics", command=self.export_image_scores).pack(side="left", padx=(5, 0))
        box, self.image_table = table_widget(right, 6)
        box.pack(fill="both", expand=True)
        self.image_path = None
        self.image_original = None
        self.image_scores = {}
        if self.image_sources:
            self.select_image()

    def import_image(self):
        path = self.pick_file("Open a source image", IMAGE_TYPES)
        if path:
            p = Path(path)
            name = p.name if p.name not in self.image_sources or self.image_sources[p.name] == p else str(p)
            self.image_sources[name] = p
            self.image_selector.configure(values=list(self.image_sources))
            self.image_selector.set(name)
            self.select_image()

    def select_image(self):
        path = self.image_sources[self.image_selector.get()]
        try:
            picture = preview(load_image(path), 960)
            self.image_automatic = choose_scene(picture)
        except (ValueError, OSError, cv2.error) as error:
            self.status.set(f"Cannot open image: {error}")
            return
        self.image_path, self.image_original = path, picture
        self.process_image()

    def adjust_image(self):
        if self.image_pending is not None:
            self.root.after_cancel(self.image_pending)
        self.image_pending = self.root.after(90, self.process_image)

    def image_settings(self):
        settings = {key: value.get() for key, (value, _, _) in self.image_controls.items()}
        settings["tiles"] = round(settings["tiles"])
        return settings

    def process_image(self):
        if self.image_pending is not None:
            self.root.after_cancel(self.image_pending)
            self.image_pending = None
        if self.image_original is None:
            return
        method = self.image_method.get()
        config = self.image_settings()
        applicable = {
            "Manual shadow CLAHE": {"clip", "tiles", "strength"}, "Fixed CLAHE": {"clip", "tiles"},
            "Gamma": {"gamma"}, "Denoise + CLAHE": {"clip", "tiles"}, "Local illumination": {"strength"},
        }.get(method, set())
        for key, (_, caption, label) in self.image_controls.items():
            caption.set(f"{label}   {config[key]:.2f}" if key != "tiles" else f"{label}   {config[key]}")
            self.image_scales[key].state(["!disabled" if key in applicable else "disabled"])
        self.image_result = enhance(self.image_original, method, automatic=self.image_automatic, **config)
        self.image_scores, before, after, self.image_diff = compare(self.image_original, self.image_result)
        self.paint_image()
        setting = self.image_automatic
        details = (f"Auto selected clip {setting.clip:g} · {setting.tiles}×{setting.tiles} tiles"
                   if setting.strength else "Auto selected the original")
        self.image_info.set((details + "\n" if method == METHODS[0] else "") + "Metrics use preview pixels and the original as reference.")
        self.hist.set([("Original", BLUE, list(enumerate(before))),
                       ("Enhanced", MINT, list(enumerate(after)))], "intensity")
        fill_table(self.image_table, ("metric", "value"),
                   [{"metric": SCORE_NAMES.get(k, k), "value": v} for k, v in self.image_scores.items()])
        self.image_table.column("metric", width=145)
        self.image_table.column("value", width=75)
        safe_scores = {key: score_text(value) for key, value in self.image_scores.items()}
        self.context["Image Lab"] = {"image": self.image_path.name, "method": method, "settings": config,
                                     "automatic": settings_context(setting), "preview_metrics": safe_scores}
        self.status.set(f"{self.image_path.name}  ·  {self.image_original.shape[1]} × {self.image_original.shape[0]} preview")

    def paint_image(self):
        if not hasattr(self, "image_result"):
            return
        mode = self.image_display.get()
        image = self.image_original
        if mode == "Enhanced":
            image = self.image_result
        elif mode == "Difference heatmap":
            image = heatmap(self.image_diff)
        elif mode == "Split":
            split = round(self.split.get() / 100 * image.shape[1])
            image = image.copy()
            image[:, split:] = self.image_result[:, split:]
            if 0 < split < image.shape[1]:
                image[:, split-1:split+1] = (204, 240, 154)
        self.image_picture.show(image)

    def export_image(self):
        if not self.image_path:
            return
        path = filedialog.asksaveasfilename(parent=self.root, initialdir=RESULTS, defaultextension=".png",
                                            initialfile=f"{self.image_path.stem}_studio.png")
        if path:
            original, method, config = self.image_path, self.image_method.get(), self.image_settings()

            def save():
                picture = load_image(original)
                save_png(Path(path), enhance(picture, method, **config))

            self.task("Exporting full-resolution PNG…", save, lambda _: self.status.set(f"Saved {path}"))

    def export_image_scores(self):
        if self.image_scores:
            self.save_csv("studio_image_metrics.csv", ("metric", "value"),
                          [{"metric": k, "value": v} for k, v in self.image_scores.items()])

    def build_videos(self):
        page = self.page("Video Lab", "Play the source and comparison together, sample exposure, or benchmark a clip.")
        top = self.panel(page)
        top.pack(fill="x", pady=(0, 8))
        self.video_sources = {p.name: p for p in sorted(VIDEOS.glob("*")) if p.suffix.lower() in VIDEO_TYPES}
        self.video_selector = self.dropdown(top, list(self.video_sources), next(iter(self.video_sources), ""),
                                             self.select_video, 24)
        self.video_selector.pack(side="left", padx=(0, 5))
        ttk.Button(top, text="Open video…", command=self.import_video).pack(side="left")
        self.video_method = self.dropdown(top, (), "", self.video_method_changed, 24)
        self.video_method.pack(side="right")
        screens = ttk.Frame(page)
        screens.pack(fill="both", expand=True)
        layout_columns(screens, [(1, 0), (1, 0)])
        screens.rowconfigure(0, weight=1)
        left, right = self.panel(screens, "Original"), self.panel(screens, "Enhanced")
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
        right.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
        self.original_video, self.output_video = Picture(left), Picture(right)
        self.original_video.pack(fill="both", expand=True)
        self.output_video.pack(fill="both", expand=True)
        transport = self.panel(page)
        transport.pack(fill="x", pady=7)
        self.play_button = ttk.Button(transport, text="Play", width=7, style="Accent.TButton", command=self.toggle_video)
        self.play_button.pack(side="left", padx=(0, 5))
        ttk.Button(transport, text="‹ Frame", command=lambda: self.step(-1)).pack(side="left")
        ttk.Button(transport, text="Frame ›", command=lambda: self.step(1)).pack(side="left", padx=5)
        self.video_position = tk.DoubleVar(value=0)
        self.video_slider = ttk.Scale(transport, from_=0, to=1, variable=self.video_position,
                                      command=self.scrub)
        self.video_slider.pack(side="left", fill="x", expand=True, padx=6)
        self.video_clock = tk.StringVar(value="0.00 s")
        ttk.Label(transport, textvariable=self.video_clock, style="Panel.TLabel").pack(side="right")
        lower = self.panel(page)
        lower.pack(fill="x")
        actions = ttk.Frame(lower, style="Panel.TFrame")
        actions.pack(fill="x")
        self.sample_button = ttk.Button(actions, text="Sample exposure", command=self.sample_video)
        self.sample_button.pack(side="left")
        self.benchmark_button = ttk.Button(actions, text="Run full benchmark", command=self.benchmark_video,
                                           style="Accent.TButton")
        self.benchmark_button.pack(side="left", padx=5)
        ttk.Button(actions, text="Export samples", command=self.export_video_samples).pack(side="left")
        self.video_chart_metric = self.dropdown(
            actions, ("Input brightness", "Shadow coverage", "Highlight coverage", "Brightness lift", "Flicker", "Processing time"),
            "Brightness lift", self.draw_video_plot, 16,
        )
        self.video_chart_metric.pack(side="right")
        self.video_plot = Plot(lower, 124)
        self.video_plot.pack(fill="x", pady=5)
        self.video_info = tk.StringVar(value="Preview playback is silent.")
        ttk.Label(lower, textvariable=self.video_info, style="Panel.TLabel", wraplength=920).pack(anchor="w")
        self.video_path = None
        self.frame_count = 0
        self.fps = 0
        self.video_runs = {}
        self.video_rows = {}
        if self.video_sources:
            self.select_video()

    def import_video(self):
        path = self.pick_file("Open a source video", VIDEO_TYPES)
        if path:
            self.add_video(Path(path))

    def add_video(self, path, preferred=None):
        name = path.name if path.name not in self.video_sources or self.video_sources[path.name] == path else str(path)
        self.video_sources[name] = path
        self.video_selector.configure(values=list(self.video_sources))
        self.video_selector.set(name)
        self.select_video(preferred)

    def select_video(self, preferred=None):
        self.pause_video()
        path = self.video_sources[self.video_selector.get()]
        capture = cv2.VideoCapture(str(path))
        if not capture.isOpened():
            capture.release()
            self.status.set(f"Cannot open {path.name}")
            return
        fps, frames = capture.get(cv2.CAP_PROP_FPS), capture.get(cv2.CAP_PROP_FRAME_COUNT)
        if not math.isfinite(fps) or fps <= 0 or not math.isfinite(frames) or frames < 1:
            capture.release()
            self.status.set(f"Cannot determine frame rate or duration for {path.name}")
            return
        if self.video_capture:
            self.video_capture.release()
        self.video_capture = capture
        self.video_path = path
        self.fps, self.frame_count = fps, int(frames)
        self.video_frame = 0
        self.video_samples = []
        self.video_automatic = None
        self.video_runs = {}
        self.video_rows = {}
        if path.parent == VIDEOS:
            folder = RESULTS / "video" / path.stem
            summary = folder / "video_summary.csv"
            if summary.exists():
                _, records = csv_rows(summary)
                for record in records:
                    method = record["method"]
                    output = folder / f"{method}.mp4"
                    if output.exists():
                        self.video_runs[method] = (output, record)
                        metrics = folder / f"{method}_frames.csv"
                        if metrics.exists():
                            self.video_rows[method] = csv_rows(metrics)[1]
        self.video_choices = {f"Saved · {label.replace('_', ' ').title()}": label for label in self.video_runs}
        self.video_choices.update({f"Live · {label}": label for label in
                                   (METHODS[0], "Fixed CLAHE", "Gamma", "Denoise + CLAHE", "Local illumination")})
        self.video_method.configure(values=list(self.video_choices))
        target = "Saved · Scene Tuned" if "scene_tuned" in self.video_runs else "Live · Scene-tuned CLAHE"
        self.video_method.set(preferred if preferred in self.video_choices else target)
        self.video_slider.configure(to=max(1, self.frame_count - 1))
        self.video_method_changed()
        self.status.set(f"{path.name}  ·  {self.frame_count:,} frames at {self.fps:.2f} fps")

    def video_method_changed(self):
        self.pause_video()
        if self.enhanced_capture:
            self.enhanced_capture.release()
            self.enhanced_capture = None
        self.current_video_method = self.video_choices.get(self.video_method.get())
        pair = self.video_runs.get(self.current_video_method)
        if pair:
            self.enhanced_capture = cv2.VideoCapture(str(pair[0]))
        self.draw_video_frame(self.video_frame, seek=True)
        self.draw_video_plot()
        self.video_context()

    def video_context(self):
        if self.video_path is None:
            return
        pair = self.video_runs.get(self.current_video_method)
        self.context["Video Lab"] = {
            "clip": self.video_path.name, "frames": self.frame_count, "fps": self.fps,
            "method": self.video_method.get(), "benchmark": pair[1] if pair else None,
            "sample_count": len(self.video_samples),
        }
        if self.video_samples:
            brightness = [row["mean_brightness"] for row in self.video_samples]
            self.context["Video Lab"]["sample_mean_brightness"] = float(np.mean(brightness))
            self.context["Video Lab"]["sample_darkest_frame"] = min(
                self.video_samples, key=lambda row: row["mean_brightness"])["frame"]

    def draw_video_frame(self, index, seek=False):
        if not self.video_capture:
            return False
        if seek:
            self.video_capture.set(cv2.CAP_PROP_POS_FRAMES, index)
            if self.enhanced_capture:
                self.enhanced_capture.set(cv2.CAP_PROP_POS_FRAMES, index)
        ok, frame = self.video_capture.read()
        if not ok:
            return False
        frame = preview(frame, 640)
        if self.enhanced_capture:
            ok, output = self.enhanced_capture.read()
            if not ok:
                self.status.set("The saved output could not be decoded at this frame.")
                return False
            output = preview(output, 640)
        else:
            if self.video_automatic is None and self.current_video_method == METHODS[0]:
                self.video_automatic = choose_scene(frame)
            output = enhance(frame, self.current_video_method, automatic=self.video_automatic)
        self.original_video.show(frame)
        self.output_video.show(output)
        self.video_frame = index
        self.video_adjusting = True
        self.video_position.set(index)
        self.video_adjusting = False
        self.video_clock.set(f"{index / self.fps:.2f} / {self.frame_count / self.fps:.2f} s")
        first = float(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY).mean())
        second = float(cv2.cvtColor(output, cv2.COLOR_BGR2GRAY).mean())
        info = f"Frame {index:,}  ·  Preview luma {first:.2f} → {second:.2f} ({second-first:+.2f})"
        if self.video_samples:
            info += f"  ·  {len(self.video_samples)} exposure samples"
        if self.enhanced_capture is None and self.current_video_method == METHODS[0]:
            info += "  ·  Live tuning uses the first previewed frame"
        self.video_info.set(info + "  ·  Silent preview")
        return True

    def step(self, delta):
        self.pause_video()
        self.jump_frame(self.video_frame + delta)

    def jump_frame(self, index):
        if self.frame_count:
            self.draw_video_frame(max(0, min(self.frame_count - 1, int(index))), seek=True)

    def scrub(self, value):
        if not self.video_adjusting:
            self.pause_video()
            self.jump_frame(float(value))

    def pause_video(self):
        if self.play_job:
            self.root.after_cancel(self.play_job)
            self.play_job = None
        if self.playing:
            self.playing = False
            self.play_button.configure(text="Play")

    def toggle_video(self):
        if self.playing:
            self.pause_video()
        elif self.video_capture:
            if self.video_frame >= self.frame_count - 1:
                self.jump_frame(0)
            self.playing = True
            self.play_button.configure(text="Pause")
            self.play_next()

    def play_next(self):
        self.play_job = None
        if not self.playing:
            return
        start = time.monotonic()
        if self.video_frame + 1 >= self.frame_count or not self.draw_video_frame(self.video_frame + 1):
            self.pause_video()
            return
        budget = 1000 / self.fps - (time.monotonic() - start) * 1000
        self.play_job = self.root.after(max(1, round(budget)), self.play_next)

    def sample_video(self):
        if self.video_path is None:
            return
        path = self.video_path

        def done(rows):
            if self.video_path != path:
                self.status.set(f"Exposure sampling finished for {path.name}.")
                return
            self.video_samples = rows
            self.video_chart_metric.set("Shadow coverage")
            self.draw_video_plot()
            self.video_context()
            darkest = min(rows, key=lambda row: row["mean_brightness"])
            self.status.set(f"{len(rows)} samples  ·  Darkest sampled frame {darkest['frame']} at {darkest['time_s']:.2f} s")

        self.task("Sampling video exposure…", lambda: video_exposure(path), done, self.sample_button)

    def draw_video_plot(self):
        selected = self.video_chart_metric.get()
        raw = self.video_rows.get(getattr(self, "current_video_method", None), [])
        series = []
        sampled_metrics = {"Shadow coverage": "Shadow pixels (%)", "Highlight coverage": "Highlight pixels (%)",
                           "Input brightness": "mean_brightness"}
        raw_metrics = {"Brightness lift": "mean_lift", "Flicker": "flicker",
                       "Processing time": "enhancement_ms", "Input brightness": "input_luma"}
        if self.video_samples and selected in sampled_metrics:
            key = sampled_metrics[selected]
            series = [(selected, MINT, [(r["time_s"], r[key]) for r in self.video_samples])]
        elif raw and selected in raw_metrics:
            key = raw_metrics[selected]
            points = [(float(row["time_s"]), (
                float(row[key]) + float(row["profile_ms"]) if key == "enhancement_ms"
                else float(row[key]) if row[key] else None)) for row in raw]
            series = [(selected, MINT, points)]
        self.video_plot.set(series, "s", lambda seconds: self.step_to_time(seconds))
        if not series:
            self.video_plot.create_text(12, 22, anchor="w", fill=MUTED,
                                        text="Sample exposure or select a saved benchmark to populate the timeline.")

    def step_to_time(self, seconds):
        self.pause_video()
        self.jump_frame(round(seconds * self.fps))

    def benchmark_video(self):
        if self.video_path is not None:
            path = self.video_path

            def done(run):
                source = next(p for p in VIDEOS.glob(f"{run}.*") if p.suffix.lower() in VIDEO_TYPES)
                self.add_video(source, "Saved · Scene Tuned")
                self.status.set(f"Benchmark saved in outputs/video/{run}")

            self.task("Benchmarking fixed, scene-tuned and stabilized enhancement…",
                      lambda: test_video(path), done, self.benchmark_button)

    def export_video_samples(self):
        if self.video_samples:
            self.save_csv("video_exposure.csv", tuple(self.video_samples[0]), self.video_samples)
        else:
            self.status.set("Sample exposure before exporting a CSV.")

    def save_csv(self, filename, fields, rows):
        path = filedialog.asksaveasfilename(parent=self.root, initialdir=RESULTS, defaultextension=".csv",
                                            initialfile=filename)
        if path:
            try:
                write_csv(path, fields, rows)
                self.status.set(f"Saved {path}")
            except OSError as error:
                self.status.set(f"Cannot save CSV: {error}")

    def build_scores(self):
        page = self.page("Scores", "Open a measured dataset, filter rows and sort by any column.")
        controls = self.panel(page)
        controls.pack(fill="x", pady=(0, 8))
        self.score_dataset = self.dropdown(controls, (), "", self.load_score_table, 35)
        self.score_dataset.pack(side="left")
        self.score_filter = tk.StringVar()
        self.score_filter.trace_add("write", lambda *_: self.reset_score_page())
        ttk.Label(controls, text="Filter", style="Panel.TLabel").pack(side="left", padx=(10, 4))
        ttk.Entry(controls, textvariable=self.score_filter, width=23).pack(side="left", fill="x", expand=True)
        ttk.Button(controls, text="Save filtered CSV", command=self.export_filtered_scores).pack(side="right", padx=5)
        self.score_count = tk.StringVar()
        ttk.Label(page, textvariable=self.score_count, style="Muted.TLabel").pack(anchor="w", pady=(0, 7))
        box, self.score_tree = table_widget(page)
        box.pack(fill="both", expand=True)
        footer = ttk.Frame(page)
        footer.pack(fill="x", pady=(6, 0))
        self.prev_score = ttk.Button(footer, text="Previous", command=lambda: self.change_score_page(-1))
        self.prev_score.pack(side="left")
        self.next_score = ttk.Button(footer, text="Next", command=lambda: self.change_score_page(1))
        self.next_score.pack(side="left", padx=4)
        self.score_page = 0
        self.score_page_size = 300
        ttk.Label(page, text="PSNR and SSIM use the original as reference. Higher values indicate similarity to the input.",
                  style="Muted.TLabel").pack(anchor="w", pady=(7, 0))
        self.score_tree.bind("<<TreeviewSelect>>", self.score_context)
        self.score_columns, self.score_records, self.score_visible = [], [], []
        self.score_sort = ("", False)
        self.score_sources = {}

    def refresh_scores(self, choose=None):
        datasets = sorted(RESULTS.rglob("*.csv"))
        self.score_sources = {str(path.relative_to(RESULTS)): path for path in datasets}
        selected = choose or self.score_dataset.get()
        self.score_dataset.configure(values=list(self.score_sources))
        if selected not in self.score_sources:
            selected = "metrics.csv" if "metrics.csv" in self.score_sources else next(iter(self.score_sources), "")
        self.score_dataset.set(selected)
        self.load_score_table()

    def load_score_table(self):
        path = self.score_sources.get(self.score_dataset.get())
        self.score_columns, self.score_records = csv_rows(path) if path else ([], [])
        self.score_sort = ("", False)
        self.reset_score_page()

    def sort_scores(self, key):
        previous_key, reverse = self.score_sort
        self.score_sort = (key, not reverse if previous_key == key else False)
        self.reset_score_page()

    def reset_score_page(self):
        self.score_page = 0
        self.filter_scores()

    def change_score_page(self, delta):
        self.score_page += delta
        self.filter_scores()

    def filter_scores(self):
        text = self.score_filter.get().strip().lower()
        rows = [row for row in self.score_records if not text or any(text in str(value).lower() for value in row.values())]
        field, reverse = self.score_sort
        order = 1
        if field:
            def sort_key(row):
                raw = row.get(field) or ""
                try:
                    return 0, float(raw)
                except ValueError:
                    return 1, raw.casefold()

            rows.sort(key=sort_key, reverse=reverse)
            order = -1 if reverse else 1
        self.score_visible = rows
        last = max(0, (len(rows) - 1) // self.score_page_size)
        self.score_page = min(last, max(0, self.score_page))
        start = self.score_page * self.score_page_size
        end = min(start + self.score_page_size, len(rows))
        self.score_displayed = rows[start:end]
        fill_table(self.score_tree, self.score_columns, self.score_displayed, SCORE_NAMES)
        self.prev_score.state(["!disabled" if self.score_page > 0 else "disabled"])
        self.next_score.state(["!disabled" if self.score_page < last else "disabled"])
        for key in self.score_columns:
            label = SCORE_NAMES.get(key, key.replace("_", " "))
            if key == field:
                label += " ↑" if order == 1 else " ↓"
            self.score_tree.heading(key, text=label, command=lambda k=key: self.sort_scores(k))
        self.score_count.set(f"{len(rows):,} / {len(self.score_records):,} rows"
                             + (f"  ·  Showing {start + 1:,}–{end:,}" if rows else ""))
        self.score_context()

    def score_context(self, _event=None):
        selected = self.score_tree.selection()
        self.context["Scores"] = {"dataset": self.score_dataset.get(), "matching_rows": len(self.score_visible),
                                  "rows": [self.score_displayed[int(item)] for item in selected[:6]]
                                  if selected else self.score_displayed[:5]}

    def export_filtered_scores(self):
        if self.score_columns:
            self.save_csv("filtered_metrics.csv", self.score_columns, self.score_visible)

    def build_files(self):
        page = self.page("Project Files", "Browse inputs, results and reports. Double-click media to open it in a lab.")
        toolbar = self.panel(page)
        toolbar.pack(fill="x", pady=(0, 8))
        self.file_query = tk.StringVar()
        ttk.Label(toolbar, text="Search", style="Panel.TLabel").pack(side="left", padx=(0, 6))
        ttk.Entry(toolbar, textvariable=self.file_query).pack(side="left", fill="x", expand=True)
        ttk.Button(toolbar, text="Open selected", command=self.open_selected).pack(side="left", padx=6)
        self.file_query.trace_add("write", lambda *_: self.list_files())
        box, self.file_tree = table_widget(page)
        box.pack(fill="both", expand=True)
        self.file_tree.bind("<Double-1>", lambda _: self.open_selected())
        self.file_tree.bind("<<TreeviewSelect>>", self.file_context)

    def list_files(self):
        assets = []
        for directory in (ROOT / "data", RESULTS):
            assets.extend(p for p in directory.rglob("*") if p.is_file()
                          and "review" not in p.relative_to(directory).parts
                          and not any(part.startswith(".") for part in p.relative_to(directory).parts))
        assets.extend(p for p in ROOT.iterdir() if p.suffix.lower() in (".pdf", ".docx", ".md"))
        query = self.file_query.get().strip().casefold()
        self.file_paths = [p for p in sorted(assets) if query in str(p.relative_to(ROOT)).casefold()]
        fill_table(self.file_tree, ("path", "type", "size"),
                   [{"path": str(p.relative_to(ROOT)), "type": p.suffix.lstrip(".").upper(),
                     "size": f"{p.stat().st_size / 1024:.1f} KB"} for p in self.file_paths])
        self.file_tree.column("path", width=490)

    def file_context(self, _event=None):
        selection = self.file_tree.selection()
        if selection:
            path = self.file_paths[int(selection[0])]
            self.context["Project Files"] = {"project_relative_path": str(path.relative_to(ROOT))}

    def open_selected(self):
        selection = self.file_tree.selection()
        if not selection:
            return
        path = self.file_paths[int(selection[0])]
        kind = path.suffix.lower()
        if kind in IMAGE_TYPES:
            name = path.name if path.name not in self.image_sources or self.image_sources[path.name] == path else str(path)
            self.image_sources[name] = path
            self.image_selector.configure(values=list(self.image_sources))
            self.image_selector.set(name)
            self.select_image()
            self.show("Image Lab")
        elif kind in VIDEO_TYPES:
            self.add_video(path)
            self.show("Video Lab")
        elif kind == ".csv" and path.is_relative_to(RESULTS):
            self.show("Scores")
            self.refresh_scores(str(path.relative_to(RESULTS)))
        else:
            self.open_file(path)

    def build_assistant(self):
        page = self.page("Assistant", "Explain active measurements or prepare an edit request for ChatGPT.")
        controls = self.panel(page)
        controls.pack(fill="x", pady=(0, 8))
        self.assistant_context = tk.StringVar(value="Context · Image Lab")
        ttk.Label(controls, textvariable=self.assistant_context, style="Panel.TLabel").pack(side="left")
        self.api_label = tk.StringVar()
        ttk.Button(controls, text="API key…", command=self.configure_api).pack(side="right")
        ttk.Label(controls, textvariable=self.api_label, style="Panel.TLabel").pack(side="right", padx=8)
        self.transcript = tk.Text(page, wrap="word", bg=PANEL, fg=TEXT, insertbackground=TEXT,
                                  relief="flat", padx=14, pady=12, font=("Helvetica Neue", 13), height=12,
                                  highlightthickness=0)
        self.transcript.pack(fill="both", expand=True)
        self.append_chat("Studio", "Ask about the view you were using. Send shares your question, selected metrics and recent chat with OpenAI. Copy edit request prepares a prompt with the project path for your Codex chat.")
        self.question = tk.StringVar()
        row = self.panel(page)
        row.pack(fill="x", pady=(8, 0))
        entry = ttk.Entry(row, textvariable=self.question)
        entry.pack(side="left", fill="x", expand=True)
        entry.bind("<Return>", lambda _: self.send_question())
        self.send_button = ttk.Button(row, text="Send to OpenAI", command=self.send_question, style="Accent.TButton")
        self.send_button.pack(side="left", padx=7)
        self.update_api_state()
        ttk.Button(row, text="Copy edit request", command=self.copy_edit_request).pack(side="left")

    def update_api_state(self):
        self.api_label.set("Key set for this session" if self.api_key else "OpenAI key required")
        self.send_button.state(["!disabled" if self.api_key else "disabled"])

    def configure_api(self):
        key = simpledialog.askstring("OpenAI API key",
                                      "Enter an API key for this session only.", parent=self.root, show="•")
        if key is not None:
            self.api_key = key.strip()
            self.update_api_state()

    def append_chat(self, author, text):
        self.transcript.configure(state="normal")
        self.transcript.insert("end", f"{author}\n{text}\n\n")
        self.transcript.see("end")
        self.transcript.configure(state="disabled")

    def send_question(self):
        question = self.question.get().strip()
        if not question or self.send_button.instate(["disabled"]):
            return
        context = self.context.get(self.last_lab, {})
        self.question.set("")
        self.append_chat("You", question)
        history = self.history.copy()
        key = self.api_key

        def done(answer):
            self.history.extend([{"role": "user", "content": question}, {"role": "assistant", "content": answer}])
            self.history = self.history[-6:]
            self.append_chat("Assistant", answer)
            self.status.set("Assistant response received.")

        self.task("Waiting for OpenAI…", lambda: ask_openai(question, context, history, key=key), done, self.send_button)

    def copy_edit_request(self):
        detail = self.question.get().strip()
        if not detail:
            self.status.set("Enter the project change you want to request.")
            return
        context = json.dumps(self.context.get(self.last_lab, {}), ensure_ascii=False, default=str)
        prompt = (f"Edit this existing local project in place: {ROOT}\n"
                  f"Requested change: {detail}\n"
                  f"Current Studio view: {self.last_lab}\n"
                  f"Selected context: {context}\n"
                  "Use the files in this folder and verify the result in the native Studio.")
        self.root.clipboard_clear()
        self.root.clipboard_append(prompt)
        self.status.set("Edit request copied. Paste it into the Codex workspace chat.")

    def close(self):
        self.pause_video()
        for capture in (self.video_capture, self.enhanced_capture):
            if capture:
                capture.release()
        self.pool.shutdown(wait=False, cancel_futures=True)
        self.root.destroy()


def main():
    root = tk.Tk()
    studio = Studio(root)
    root.mainloop()
    return studio


if __name__ == "__main__":
    main()
