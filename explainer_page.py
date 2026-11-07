"""The "Explainer" page of the app, as a mixin for App in autopilot_gui.pyw: find a niche with the master prompt, pick a
topic, then make a narrated explainer (the LLM writes and draws it, Edge voices it, HyperFrames animates it). A Short goes
to Review; a long video is a film on the Long video page, made and approved from there. The work runs in explainer.py
through run_daily.bat; this file is only the interface. autopilot_gui.pyw sets explainer_page.G to its own module."""

import json
from tkinter import messagebox

import customtkinter as ctk

import explainer as ex
import longform as lf

G = None
FORMATS = {"Vertical Short (9:16)": ("short", "seconds", ["30", "45", "55"], "45"),
           "Long video (16:9)": ("long", "minutes", ["1", "3", "5", "8", "10"], "3")}
WRAP = 680


class ExplainerPage:
    def build_explainer(self):
        p = self.tabs["Explainer"]
        self.ex_seen = "not loaded"
        self.header(p, "Explainer", "Narrated explainer videos: the app finds a niche, writes the script, draws every scene, voices it and "
                                    "animates it. No paid video tools. Nothing is posted until you approve it.",
                    actions=[("Find niches", self.ex_find, "secondary"), ("Make a video", lambda: self.ex_make(), "primary")])
        body = ctk.CTkScrollableFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        box, inner, _ = self.section(body, "Find a niche", "the master prompt")
        box.pack(fill="x", pady=(0, 12))
        G.label(inner, "What interests you? Optional: e.g. animals, space, history. Empty means anything.", 12, G.C["muted"], wrap=WRAP).pack(anchor="w", pady=(0, 6))
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.ex_hint = ctk.StringVar(value="")
        G.entry(row, self.ex_hint, 420).pack(side="left")
        G.button(row, "Find niches", self.ex_find, "primary").pack(side="left", padx=8)
        G.label(inner, "Each niche comes with topics. Click one to make a video about it.", 12, G.C["muted"], wrap=WRAP).pack(anchor="w", pady=(8, 0))
        self.ex_niches = ctk.CTkFrame(inner, fg_color="transparent")
        self.ex_niches.pack(fill="x", pady=(6, 0))
        box, inner, _ = self.section(body, "Your explainers", "Shorts go to Review; long videos are made on the Long video page")
        box.pack(fill="x")
        fr, self.ex_tree = self.table(inner, ("Video", "Format", "Stage"), (420, 90, 220), 6)
        fr.pack(fill="x")

    def refresh_explainer(self):
        import story_short
        films = [f for f in lf.list_films() if f.meta.get("kind") == "explainer"]
        films += [lf.Film(p.parent) for p in sorted(story_short.SHORTS.glob("*/film.json"), reverse=True)]
        films = [f for f in films if f.meta.get("kind") == "explainer"]
        self.fill(self.ex_tree, [(f.id, (f.meta.get("title") or f.id, f.meta.get("format", ""), f.meta.get("message") or f.meta["stage"]))
                                 for f in sorted(films, key=lambda f: f.id, reverse=True)[:30]])
        path = ex.niches_file()
        stamp = path.stat().st_mtime if path.exists() else None
        if stamp != self.ex_seen:                       # rebuild the niche cards only when a new list arrived
            self.ex_seen = stamp
            self.ex_show_niches(json.loads(path.read_text(encoding="utf-8")).get("niches", []) if stamp else [])

    def ex_show_niches(self, niches):
        for w in self.ex_niches.winfo_children():
            w.destroy()
        if not niches:
            G.label(self.ex_niches, "No niches yet. Click Find niches.", 13, G.C["faint"]).pack(anchor="w", pady=6)
            return
        for n in niches:
            G.label(self.ex_niches, n["niche"] + (f"  >  {n['sub_niche']}" if n.get("sub_niche") else ""), 14, weight="bold", wrap=WRAP).pack(anchor="w", pady=(12, 0))
            if n.get("why"):
                G.label(self.ex_niches, n["why"], 12, G.C["muted"], wrap=WRAP).pack(anchor="w")
            for t in n["topics"]:
                G.button(self.ex_niches, t, lambda t=t, n=n: self.ex_make(t, n["sub_niche"] or n["niche"]), "ghost").pack(anchor="w", pady=1)

    def ex_find(self):
        self.start_run(["--explainer-niches", *self.ex_hint.get().split()], "Niche finder")

    def ex_make(self, topic_text="", niche=""):
        top, frm = self.dialog("Make an explainer", 560)
        G.label(frm, "What is the video about (e.g. 'The armored fish that didn't need teeth')? Leave it empty and the app picks a topic it "
                     "hasn't used" + (f" in {niche}." if niche else "."), 13, wrap=520).pack(anchor="w")
        topic = ctk.StringVar(value=topic_text)
        G.entry(frm, topic, 520).pack(anchor="w", pady=(6, 10))
        fmt, length = ctk.StringVar(value=next(iter(FORMATS))), ctk.StringVar(value="45")
        row = ctk.CTkFrame(frm, fg_color="transparent")
        row.pack(anchor="w", pady=(0, 10))
        G.label(row, "Format", 12, G.C["muted"]).pack(side="left")
        unit = G.label(row, "", 12, G.C["muted"])
        gates = ctk.BooleanVar(value=True)
        pause = ctk.CTkCheckBox(frm, text="Pause for my review: after the script, and after the storyboard", variable=gates, font=G.font(12),
                                text_color=G.C["muted"])

        def pick(name):
            kind, word, values, default = FORMATS[name]
            unit.configure(text=f"Length ({word})")
            picker.configure(values=values)
            length.set(default)
            pause.configure(state="normal" if kind == "long" else "disabled")
        G.option(row, fmt, list(FORMATS), 200, command=pick).pack(side="left", padx=(8, 20))
        unit.pack(side="left")
        picker = G.option(row, length, FORMATS[fmt.get()][2], 80)
        picker.pack(side="left", padx=8)
        pause.pack(anchor="w", pady=(0, 10))
        pick(fmt.get())
        G.label(frm, "Your Claude writes the script and draws every scene, Edge voices it and HyperFrames animates it: a few minutes for a "
                     "Short, about an hour for ten minutes. A Short waits in Review; a long video on the Long video page.", 12, G.C["faint"],
                wrap=520).pack(anchor="w", pady=(0, 14))

        def go():
            kind, word = FORMATS[fmt.get()][:2]
            seconds = int(length.get()) * (60 if word == "minutes" else 1)
            text = topic.get().strip()[:200]
            top.destroy()
            if kind == "short":
                G.eng.WORK.mkdir(exist_ok=True)
                path = G.eng.WORK / "explainer_job.json"
                path.write_text(json.dumps({"topic": text, "niche": niche, "format": "short", "seconds": seconds}, indent=1), encoding="utf-8")
                self.start_run(["--explainer", str(path)], "Explainer Short")
                return
            if self.lf_running() or lf.busy():
                messagebox.showinfo("Busy", "A long film is being made right now. Wait for it to finish.")
                return
            film = ex.new_film(text, "long", seconds, niche, gates.get())
            self.show("Long video")                     # its progress, review stops and upload pack live there
            self.lf_view = None
            self.refresh_long_video()
            self.lf_tree.selection_set(film.id)
            self.lf_film = film
            self.lf_continue()
        G.button(frm, "Make it", go, "primary").pack(anchor="e")
