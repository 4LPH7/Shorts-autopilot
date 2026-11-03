"""The "Shorts from a video you have the rights to" panel of the Clips page, as a mixin for App in autopilot_gui.pyw.
It only collects the answers and starts the run (run_daily.bat --clipper job.json); clipper.py does the work and refuses
to start unless the rights are stated and confirmed. autopilot_gui.pyw sets clipper_page.G to its own module."""

import json
from tkinter import filedialog, messagebox

import customtkinter as ctk

import clipper

G = None
FRAMES = {"Whole picture on a blurred background": "fit", "Fill the screen (crop to the middle)": "fill"}
NOTE = ("Your own video, one you have permission to use, or one whose licence allows it. The app finds the best moments and adds captions, "
        "effects and music; the Shorts wait in Review. Someone else's famous video isn't yours to repost (Content ID claims, strikes), "
        "and the app never downloads videos.")


class ClipperPanel:
    def build_clipper_panel(self, parent):
        box, inner, _ = self.section(parent, "Shorts from a video you have the rights to", "captions, effects and music added for you")
        box.pack(fill="x", pady=(0, 14))
        G.label(inner, NOTE, 12, G.C["muted"], wrap=760).pack(anchor="w", pady=(0, 6))
        self.cl_file, self.cl_rights, self.cl_credit = ctk.StringVar(), ctk.StringVar(), ctk.StringVar()
        self.cl_n, self.cl_frame, self.cl_ok = ctk.StringVar(value="3"), ctk.StringVar(value=next(iter(FRAMES))), ctk.BooleanVar(value=False)

        def row(name, widget_factory):
            r = ctk.CTkFrame(inner, fg_color="transparent")
            r.pack(fill="x", pady=3)
            G.label(r, name, 12, G.C["muted"], wrap=190).pack(side="left", padx=(0, 10))
            widget_factory(r)

        def chooser(r):
            G.entry(r, self.cl_file, 470).pack(side="left", padx=(0, 8))
            G.button(r, "Choose video...", self.cl_choose, "secondary").pack(side="left")
        row("Video file", chooser)
        row("Where it comes from", lambda r: G.entry(r, self.cl_rights, 620, placeholder="my own recording / CC BY 4.0 from ... / permission from ...").pack(side="left"))
        row("Credit for the description", lambda r: G.entry(r, self.cl_credit, 620, placeholder="only if the licence asks for one").pack(side="left"))

        def options(r):
            G.option(r, self.cl_n, ["1", "2", "3", "4", "5", "6"], 70).pack(side="left", padx=(0, 18))
            G.label(r, "Framing", 12, G.C["muted"]).pack(side="left", padx=(0, 8))
            G.option(r, self.cl_frame, list(FRAMES), 340).pack(side="left")
        row("How many Shorts", options)
        last = ctk.CTkFrame(inner, fg_color="transparent")
        last.pack(fill="x", pady=(8, 0))
        G.button(last, "Make Shorts", self.cl_make, "primary").pack(side="left", padx=(0, 14))
        ctk.CTkCheckBox(last, text="I own this video or have the right to reuse it in monetized YouTube Shorts", variable=self.cl_ok,
                        font=G.font(12), text_color=G.C["text"]).pack(side="left")

    def cl_choose(self):
        exts = " ".join(f"*{e}" for e in sorted(clipper.footage.VIDEO_EXT))
        path = filedialog.askopenfilename(title="Choose a video you have the rights to", filetypes=[("Video", exts), ("All files", "*.*")])
        if path:
            self.cl_file.set(path)

    def cl_make(self):
        job = {"source": self.cl_file.get().strip(), "n": int(self.cl_n.get()), "frame": FRAMES[self.cl_frame.get()], "focus": 0.5,
               "confirmed": self.cl_ok.get(), "rights": self.cl_rights.get().strip(), "credit": self.cl_credit.get().strip()}
        try:
            clipper.check_job(job)
        except clipper.JobError as err:
            messagebox.showinfo("Shorts from a video", str(err).capitalize() + ".")
            return
        G.eng.WORK.mkdir(exist_ok=True)
        path = G.eng.WORK / "clipper_job.json"
        path.write_text(json.dumps(job, indent=1), encoding="utf-8")
        self.start_run(["--clipper", str(path)], "Shorts from a video")
