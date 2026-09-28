"""Tkinter and ttk interface. Only the UI thread touches Tk widgets."""

import os
import json
import queue
import threading
import tkinter as tk
from dataclasses import asdict
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from .display import estimated_file_size, format_duration, format_size, planning_rate
from .job import Cancelled, JobControl, run
from .model import Config, EstimateCancelled, estimate_output


def lines(value: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys(item.strip() for item in value.splitlines() if item.strip()))


def substitutions(value: str) -> tuple[tuple[str, str], ...]:
    result = []
    for line in value.splitlines():
        if not line.strip():
            continue
        if "=" not in line:
            raise ValueError("Use one substitution per line in the form a=@.")
        source, target = line.split("=", 1)
        if len(source) != 1 or len(target) != 1:
            raise ValueError("Each substitution must contain one character on either side of =.")
        result.append((source, target))
    return tuple(dict.fromkeys(result))


class Tip:
    def __init__(self, widget, message):
        self.widget = widget
        self.message = message
        self.popup = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")
        widget.bind("<ButtonPress>", self.hide, add="+")

    def show(self, _event):
        if self.popup:
            return
        x, y = self.widget.winfo_rootx() + 20, self.widget.winfo_rooty() + 24
        popup = tk.Toplevel(self.widget)
        popup.wm_overrideredirect(True)
        popup.wm_geometry(f"+{x}+{y}")
        tk.Label(popup, text=self.message, bg="#21344d", fg="white", padx=9,
                 pady=6, wraplength=360, justify="left").pack()
        self.popup = popup

    def hide(self, _event):
        if self.popup:
            self.popup.destroy()
            self.popup = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Wordlist Studio - Authorized password audits")
        self.geometry("960x810")
        self.minsize(780, 650)
        self.configure(bg="#edf2f7")
        self.protocol("WM_DELETE_WINDOW", self.close)
        style = ttk.Style(self)
        if "clam" in style.theme_names():
            style.theme_use("clam")
        style.configure("TFrame", background="#edf2f7")
        style.configure("TLabel", background="#edf2f7", foreground="#183048")
        style.configure("TLabelframe", background="#edf2f7", foreground="#183048")
        style.configure("TLabelframe.Label", background="#edf2f7", foreground="#183048",
                        font=("TkDefaultFont", 10, "bold"))
        style.configure("TButton", padding=(10, 6))
        style.configure("Accent.TButton", background="#176b9a", foreground="white")
        self.mode = tk.StringVar(value="exhaustive")
        self.minimum = tk.StringVar(value="4")
        self.maximum = tk.StringVar(value="4")
        self.lowercase = tk.BooleanVar(value=True)
        self.uppercase = tk.BooleanVar()
        self.digits = tk.BooleanVar(value=True)
        self.symbols = tk.BooleanVar()
        self.extra = tk.StringVar()
        self.exclude = tk.StringVar()
        self.combine = tk.BooleanVar()
        self.cases = tk.BooleanVar()
        self.deduplicate = tk.BooleanVar()
        self.compress = tk.BooleanVar()
        self.workers = tk.StringVar(value=str(min(os.cpu_count() or 1, 8)))
        self.output = tk.StringVar(value=str(Path.home() / "wordlist.txt"))
        self.estimate_text = tk.StringVar(value="")
        self.estimate_time = tk.StringVar(value="")
        self.estimate_size = tk.StringVar(value="")
        self.estimate_note = tk.StringVar(value="")
        self.status = tk.StringVar(value="Ready")
        self.count = tk.StringVar(value="Processed 0 | Written 0 | ETA -")
        self.messages = queue.Queue(maxsize=64)
        self.estimate_revision = 0
        self.estimate_cache = None
        self.control = None
        self.worker = None
        self.settings_path = None
        self._build_menu()
        self._build()
        for var in (self.mode, self.minimum, self.maximum, self.lowercase, self.uppercase,
                    self.digits, self.symbols, self.extra, self.exclude, self.combine,
                    self.cases, self.deduplicate, self.compress, self.workers):
            var.trace_add("write", lambda *_: self._schedule_estimate())
        self.compress.trace_add("write", lambda *_: self._match_output_extension())
        self.after(200, self._poll)
        self._schedule_estimate()

    def _build_menu(self):
        menubar = tk.Menu(self)
        file_menu = tk.Menu(menubar, tearoff=False)
        file_menu.add_command(label="Open Settings...", accelerator="Ctrl+O",
                              command=self._load_settings)
        file_menu.add_command(label="Save Settings", accelerator="Ctrl+S",
                              command=self._save_settings)
        file_menu.add_command(label="Save Settings As...", accelerator="Ctrl+Shift+S",
                              command=lambda: self._save_settings(save_as=True))
        file_menu.add_separator()
        file_menu.add_command(label="Exit", command=self.close)
        menubar.add_cascade(label="File", menu=file_menu)
        self.configure(menu=menubar)
        self.bind("<Control-o>", lambda _event: self._load_settings())
        self.bind("<Control-s>", lambda _event: self._save_settings())
        self.bind("<Control-Shift-S>", lambda _event: self._save_settings(save_as=True))

    def _save_settings(self, save_as=False):
        try:
            config = self._read()
            estimate_output(config)
        except (TypeError, ValueError) as exc:
            messagebox.showerror("Cannot save settings", str(exc))
            return
        path = self.settings_path
        if save_as or path is None:
            path = filedialog.asksaveasfilename(
                title="Save Wordlist Studio settings", defaultextension=".json",
                initialfile="wordlist-settings.json",
                filetypes=[("JSON settings", "*.json")])
        if not path:
            return
        try:
            payload = {"version": 1, "settings": asdict(config), "output": self.output.get()}
            Path(path).write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                                  encoding="utf-8")
        except OSError as exc:
            messagebox.showerror("Cannot save settings", str(exc))
            return
        self.settings_path = Path(path)
        self.status.set(f"Settings saved to {self.settings_path}")

    def _load_settings(self):
        path = filedialog.askopenfilename(
            title="Open Wordlist Studio settings",
            filetypes=[("JSON settings", "*.json"), ("All files", "*.*")])
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or payload.get("version") != 1:
                raise ValueError("Unsupported or invalid settings file.")
            settings = payload.get("settings")
            if not isinstance(settings, dict):
                raise ValueError("Settings file has no settings object.")
            for key in ("words", "prefixes", "suffixes"):
                if key in settings:
                    settings[key] = tuple(settings[key])
            if "substitutions" in settings:
                settings["substitutions"] = tuple(tuple(pair)
                                                  for pair in settings["substitutions"])
            config = Config(**settings)
            estimate_output(config)
            output_path = payload.get("output", str(Path.home() / "wordlist.txt"))
            if not isinstance(output_path, str):
                raise ValueError("The output path must be text.")
        except (OSError, TypeError, ValueError, KeyError) as exc:
            messagebox.showerror("Cannot open settings", str(exc))
            return

        self.mode.set(config.mode)
        self.minimum.set(str(config.min_length))
        self.maximum.set(str(config.max_length))
        self.lowercase.set(config.lowercase)
        self.uppercase.set(config.uppercase)
        self.digits.set(config.digits)
        self.symbols.set(config.symbols)
        self.extra.set(config.extra_chars)
        self.exclude.set(config.exclude_chars)
        self.combine.set(config.combine_words)
        self.cases.set(config.case_variants)
        self.deduplicate.set(config.deduplicate)
        self.compress.set(config.gzip_output)
        self.workers.set(str(config.workers))
        self._set_text(self.words, "\n".join(config.words))
        self._set_text(self.subs, "\n".join(f"{source}={target}"
                                              for source, target in config.substitutions))
        self._set_text(self.prefixes, "\n".join(config.prefixes))
        self._set_text(self.suffixes, "\n".join(config.suffixes))
        self.output.set(output_path)
        self.settings_path = Path(path)
        self.status.set(f"Settings loaded from {self.settings_path}")
        self._schedule_estimate()

    @staticmethod
    def _set_text(widget, value):
        widget.delete("1.0", "end")
        widget.insert("1.0", value)
        widget.edit_modified(False)

    def _build(self):
        frame = ttk.Frame(self, padding=18)
        frame.pack(fill="both", expand=True)
        ttk.Label(frame, text="Wordlist Studio", font=("TkDefaultFont", 20, "bold")).pack(anchor="w")
        ttk.Label(frame, text="For authorized security testing and lawful password audits only.",
                  foreground="#a13030").pack(anchor="w", pady=(2, 12))
        self.canvas = tk.Canvas(frame, highlightthickness=0, bg="#edf2f7")
        scrollbar = ttk.Scrollbar(frame, orient="vertical", command=self.canvas.yview)
        self.canvas.configure(yscrollcommand=scrollbar.set)
        scrollbar.pack(side="right", fill="y")
        self.canvas.pack(side="left", fill="both", expand=True)
        body = ttk.Frame(self.canvas)
        window = self.canvas.create_window((0, 0), window=body, anchor="nw")
        body.bind("<Configure>", lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(window, width=e.width))

        options = ttk.LabelFrame(body, text="Generation", padding=12)
        options.pack(fill="x", pady=5)
        for text, value, tip in (
            ("Exhaustive combinations", "exhaustive", "Generate every string from the selected character pool."),
            ("Keyword rules", "rules", "Mutate keywords, optionally combine ordered word pairs and add affixes."),
        ):
            button = ttk.Radiobutton(options, text=text, value=value, variable=self.mode)
            button.pack(side="left", padx=(0, 20))
            Tip(button, tip)
        ttk.Label(options, text="Workers").pack(side="left", padx=(0, 6))
        worker_entry = ttk.Spinbox(options, from_=1, to=32, textvariable=self.workers, width=4)
        worker_entry.pack(side="left")
        Tip(worker_entry, "Use separate CPU processes. More workers can speed up large jobs; "
                          "small jobs may take longer due to startup overhead.")
        lengths = ttk.LabelFrame(body, text="Length and character pool", padding=12)
        lengths.pack(fill="x", pady=5)
        row = ttk.Frame(lengths)
        row.pack(fill="x")
        for label, variable, tip in (("Minimum length", self.minimum, "Shortest output in characters."),
                                     ("Maximum length", self.maximum, "Longest output in characters, up to 32.")):
            ttk.Label(row, text=label).pack(side="left", padx=(0, 6))
            entry = ttk.Entry(row, textvariable=variable, width=6)
            entry.pack(side="left", padx=(0, 20))
            Tip(entry, tip)
        row = ttk.Frame(lengths)
        row.pack(fill="x", pady=8)
        for label, variable, tip in (
            ("Lowercase", self.lowercase, "Add a through z to the exhaustive character pool."),
            ("Uppercase", self.uppercase, "Add A through Z to the exhaustive character pool."),
            ("Digits", self.digits, "Add 0 through 9 to the exhaustive character pool."),
            ("Symbols", self.symbols, "Add ASCII punctuation to the exhaustive character pool."),
        ):
            widget = ttk.Checkbutton(row, text=label, variable=variable)
            widget.pack(side="left", padx=(0, 16))
            Tip(widget, tip)
        for label, variable, tip in (
            ("Additional characters", self.extra, "Characters added to the exhaustive pool, without duplicates."),
            ("Exclude characters", self.exclude, "Remove these characters from exhaustive output and rule candidates."),
        ):
            row = ttk.Frame(lengths)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=22).pack(side="left")
            entry = ttk.Entry(row, textvariable=variable)
            entry.pack(side="left", fill="x", expand=True)
            Tip(entry, tip)

        rules = ttk.LabelFrame(body, text="Keyword rules", padding=12)
        rules.pack(fill="x", pady=5)
        ttk.Label(rules, text="Base words - one per line").grid(row=0, column=0, sticky="w")
        ttk.Label(rules, text="Substitutions - one a=@ mapping per line").grid(row=0, column=1, sticky="w")
        self.words = tk.Text(rules, height=4, width=25, undo=True)
        self.words.grid(row=1, column=0, sticky="ew", padx=(0, 8))
        self.subs = tk.Text(rules, height=4, width=25, undo=True)
        self.subs.grid(row=1, column=1, sticky="ew")
        self.subs.insert("1.0", "a=@\no=0")
        Tip(self.words, "Each base word is used alone. Optional ordered pairs include the same word twice.")
        Tip(self.subs, "Each matching character independently keeps its original value or uses a replacement.")
        for row_number, label, tip in ((2, "Prefixes - one per line", "Attach one prefix or none to each variant."),
                                       (4, "Suffixes - one per line", "Attach one suffix or none to each variant. Years and numbers work here.")):
            ttk.Label(rules, text=label).grid(row=row_number, column=0, sticky="w", pady=(5, 0))
            widget = tk.Text(rules, height=2, width=25, undo=True)
            widget.grid(row=row_number + 1, column=0, columnspan=2, sticky="ew")
            Tip(widget, tip)
            if row_number == 2:
                self.prefixes = widget
            else:
                self.suffixes = widget
        row = ttk.Frame(rules)
        row.grid(row=6, column=0, columnspan=2, sticky="w", pady=(8, 0))
        for label, var, tip in (
            ("Combine ordered pairs", self.combine, "Generate word1+word2 for every ordered pair, including repeated words."),
            ("Case variants", self.cases, "Include original, lower, upper, and title case where distinct."),
        ):
            widget = ttk.Checkbutton(row, text=label, variable=var)
            widget.pack(side="left", padx=(0, 18))
            Tip(widget, tip)
        rules.columnconfigure(0, weight=1)
        rules.columnconfigure(1, weight=1)
        for widget in (self.words, self.subs, self.prefixes, self.suffixes):
            widget.edit_modified(False)
            widget.bind("<<Modified>>", self._rules_modified)

        output_frame = ttk.LabelFrame(body, text="Output", padding=12)
        output_frame.pack(fill="x", pady=5)
        row = ttk.Frame(output_frame)
        row.pack(fill="x")
        ttk.Label(row, text="Destination").pack(side="left", padx=(0, 8))
        ttk.Entry(row, textvariable=self.output).pack(side="left", fill="x", expand=True)
        ttk.Button(row, text="Browse", command=self._browse).pack(side="left", padx=(8, 0))
        row = ttk.Frame(output_frame)
        row.pack(fill="x", pady=(8, 0))
        for label, var, tip in (
            ("Deduplicate on disk", self.deduplicate,
             "Uses a temporary SQLite index for keyword rules. Exhaustive candidates are already unique."),
            ("Compress with gzip", self.compress, "Use gzip level 3. The output file must end in .gz."),
        ):
            widget = ttk.Checkbutton(row, text=label, variable=var)
            widget.pack(side="left", padx=(0, 18))
            Tip(widget, tip)
        ttk.Label(body, textvariable=self.estimate_text, font=("TkDefaultFont", 11, "bold"),
                  wraplength=750).pack(anchor="w", pady=(12, 3))
        ttk.Label(body, textvariable=self.estimate_time).pack(anchor="w", pady=2)
        ttk.Label(body, textvariable=self.estimate_size, wraplength=750).pack(anchor="w", pady=2)
        ttk.Label(body, textvariable=self.estimate_note, wraplength=750).pack(anchor="w", pady=(2, 8))
        self.progress = ttk.Progressbar(body, maximum=100)
        self.progress.pack(fill="x")
        ttk.Label(body, textvariable=self.count).pack(anchor="w", pady=5)
        ttk.Label(body, textvariable=self.status, wraplength=750).pack(anchor="w")
        controls = ttk.Frame(body)
        controls.pack(fill="x", pady=12)
        self.start_button = ttk.Button(controls, text="Generate", style="Accent.TButton", command=self._start)
        self.start_button.pack(side="left", padx=(0, 8))
        self.pause_button = ttk.Button(controls, text="Pause", command=self._pause, state="disabled")
        self.pause_button.pack(side="left", padx=(0, 8))
        self.resume_button = ttk.Button(controls, text="Resume", command=self._resume, state="disabled")
        self.resume_button.pack(side="left", padx=(0, 8))
        self.cancel_button = ttk.Button(controls, text="Cancel", command=self._cancel, state="disabled")
        self.cancel_button.pack(side="left")

    def _read(self):
        try:
            minimum, maximum = int(self.minimum.get()), int(self.maximum.get())
            workers = int(self.workers.get())
        except ValueError as exc:
            raise ValueError("Lengths and workers must be whole numbers.") from exc
        return Config(mode=self.mode.get(), min_length=minimum, max_length=maximum,
                      lowercase=self.lowercase.get(), uppercase=self.uppercase.get(),
                      digits=self.digits.get(), symbols=self.symbols.get(),
                      extra_chars=self.extra.get(), exclude_chars=self.exclude.get(),
                      words=lines(self.words.get("1.0", "end-1c")),
                      combine_words=self.combine.get(),
                      substitutions=substitutions(self.subs.get("1.0", "end-1c")),
                      prefixes=lines(self.prefixes.get("1.0", "end-1c")),
                      suffixes=lines(self.suffixes.get("1.0", "end-1c")),
                      case_variants=self.cases.get(), deduplicate=self.deduplicate.get(),
                      gzip_output=self.compress.get(), workers=workers)

    def _schedule_estimate(self):
        self.estimate_revision += 1
        self.estimate_cache = None
        self.estimate_text.set("Updating estimates...")
        self.estimate_time.set("")
        self.estimate_size.set("")
        self.estimate_note.set("")
        if hasattr(self, "_estimate_timer"):
            self.after_cancel(self._estimate_timer)
        self._estimate_timer = self.after(300, self._estimate)

    def _rules_modified(self, event):
        widget = event.widget
        if widget.edit_modified():
            widget.edit_modified(False)
            self._schedule_estimate()

    def _match_output_extension(self):
        path = self.output.get()
        if path.lower().endswith(".txt") and self.compress.get():
            self.output.set(path + ".gz")
        elif path.lower().endswith(".txt.gz") and not self.compress.get():
            self.output.set(path[:-3])

    def _estimate(self):
        try:
            config = self._read()
        except ValueError as exc:
            self.estimate_text.set(f"Configuration  {exc}")
            self.estimate_time.set("")
            self.estimate_size.set("")
            self.estimate_note.set("")
            return
        revision = self.estimate_revision
        self.estimate_text.set("Estimating candidates and output size...")

        def work():
            try:
                result = estimate_output(config, lambda: revision != self.estimate_revision)
            except EstimateCancelled:
                return
            except ValueError as exc:
                result = exc
            self.messages.put(("estimate", (revision, config, result)))

        threading.Thread(target=work, daemon=True).start()

    def _browse(self):
        extension = ".gz" if self.compress.get() else ".txt"
        path = filedialog.asksaveasfilename(defaultextension=extension,
                                            filetypes=[("Gzip wordlist", "*.gz")] if self.compress.get()
                                            else [("Plain text wordlist", "*.txt")])
        if path:
            self.output.set(path)

    def _start(self):
        try:
            config = self._read()
            if self.estimate_cache is None or self.estimate_cache[0] != config:
                self._schedule_estimate()
                raise ValueError("Please wait for the current estimate, then try again.")
            result = self.estimate_cache[1]
            if isinstance(result, ValueError):
                raise result
            if not result.candidates:
                raise ValueError("No candidates match the selected settings.")
            path = Path(self.output.get()).expanduser()
            if not str(self.output.get()).strip():
                raise ValueError("Choose an output file.")
            if config.gzip_output != (path.suffix.lower() == ".gz") or (
                not config.gzip_output and path.suffix.lower() != ".txt"
            ):
                raise ValueError("Use .gz with compression or .txt for plain text.")
            if path.exists() and not messagebox.askyesno("Replace output", f"Replace {path}?\n"
                                                         "It will be overwritten when generation starts. "
                                                         "Partial output remains if canceled or interrupted."):
                return
        except ValueError as exc:
            messagebox.showerror("Invalid configuration", str(exc))
            return
        self.control = JobControl()
        self.progress["value"] = 0
        self.count.set("Processed 0 | Written 0 | ETA -")
        self.status.set("Generating")
        self.start_button.configure(state="disabled")
        self.pause_button.configure(state="normal")
        self.resume_button.configure(state="disabled")
        self.cancel_button.configure(state="normal")

        def post(kind, payload):
            if kind == "progress":
                try:
                    self.messages.put_nowait((kind, payload))
                except queue.Full:
                    pass
            else:
                self.messages.put((kind, payload))

        def work():
            try:
                summary = run(config, path, self.control, lambda value: post("progress", value))
                post("done", summary)
            except Cancelled as exc:
                post("cancelled", getattr(exc, "output_path", None))
            except Exception as exc:
                post("error", (str(exc), getattr(exc, "output_path", None)))

        self.worker = threading.Thread(target=work, daemon=True)
        self.worker.start()

    def _pause(self):
        self.control.pause()
        self.status.set("Pausing")
        self.pause_button.configure(state="disabled")
        self.resume_button.configure(state="normal")

    def _resume(self):
        self.control.resume()
        self.status.set("Generating")
        self.pause_button.configure(state="normal")
        self.resume_button.configure(state="disabled")

    def _cancel(self):
        self.control.cancel()
        self.status.set("Canceling")
        self.cancel_button.configure(state="disabled")

    def _poll(self):
        while True:
            try:
                kind, value = self.messages.get_nowait()
            except queue.Empty:
                break
            if kind == "estimate":
                revision, config, result = value
                if revision != self.estimate_revision:
                    continue
                if isinstance(result, ValueError):
                    self.estimate_cache = (config, result)
                    self.estimate_text.set(f"Configuration  {result}")
                    self.estimate_time.set("")
                    self.estimate_size.set("")
                    self.estimate_note.set("")
                elif result.candidates:
                    self.estimate_cache = (config, result)
                    self.estimate_text.set(
                        f"Estimated candidates before deduplication  {result.candidates:,}")
                    rate = planning_rate(config)
                    seconds = (result.candidates + rate - 1) // rate
                    self.estimate_time.set(f"Estimated generation time  {format_duration(seconds)}")
                    self.estimate_size.set(
                        f"Estimated final file size  {estimated_file_size(config, result)}")
                    note = (f"Time assumes {rate:,} candidates/s. Actual speed and gzip size "
                            "vary with hardware, storage, and content.")
                    if config.mode == "exhaustive" and config.deduplicate:
                        note += " Disk deduplication is skipped because exhaustive output is unique."
                    self.estimate_note.set(note)
                else:
                    self.estimate_cache = (config, result)
                    self.estimate_text.set("No candidates match the selected settings.")
                    self.estimate_time.set("")
                    self.estimate_size.set("")
                    self.estimate_note.set("")
            elif kind == "progress":
                self.progress["value"] = 100 * value.processed / value.total
                eta = f"{value.eta:.0f}s" if value.eta is not None else "-"
                self.count.set(f"Processed {value.processed:,} / {value.total:,} | "
                               f"Written {value.written:,} | ETA {eta}")
            else:
                self.start_button.configure(state="normal")
                self.pause_button.configure(state="disabled")
                self.resume_button.configure(state="disabled")
                self.cancel_button.configure(state="disabled")
                if kind == "done":
                    self.progress["value"] = 100
                    self.status.set(f"Complete - {value['total_entries']:,} entries, "
                                    f"{value['file_size_bytes']:,} bytes in {value['seconds']:.3f}s")
                    if "summary_error" in value:
                        messagebox.showwarning("Summary log failed", "The wordlist was saved, but "
                                               f"the summary log could not be written.\n{value['summary_error']}")
                elif kind == "cancelled":
                    self.status.set(f"Canceled. Partial output saved to {value}." if value else
                                    "Canceled before output was created.")
                else:
                    error, partial_path = value
                    self.status.set(f"Generation failed. Partial output saved to {partial_path}."
                                    if partial_path else "Generation failed before output was created.")
                    messagebox.showerror("Generation failed", error)
        self.after(200, self._poll)

    def close(self):
        if self.worker is not None and self.worker.is_alive():
            if not messagebox.askyesno("Exit", "Cancel generation and close? Partial output will remain saved."):
                return
            self.control.cancel()
            self.status.set("Canceling. Waiting for cleanup.")
            self._close_when_stopped()
        else:
            self.destroy()

    def _close_when_stopped(self):
        if self.worker.is_alive():
            self.after(100, self._close_when_stopped)
        else:
            self.destroy()


def main():
    App().mainloop()
