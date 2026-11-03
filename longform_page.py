"""The "Long video" page of the app, as a mixin for App in autopilot_gui.pyw: start a film, watch its progress, watch and
approve or reject it, bring in clips made in Google Vids, copy the upload text. All the work happens in longform.py (run
through run_daily.bat so it logs like everything else); this file is only the interface.
autopilot_gui.pyw sets longform_page.G to its own module, which carries the look (label, button, card, C, ...)."""

import json
import os
import shutil
import subprocess
import webbrowser
from pathlib import Path
from tkinter import filedialog, messagebox

import customtkinter as ctk

import lf_screenplay as sc
import longform as lf

G = None
VIDS_URL = "https://docs.google.com/videos/"
IDEAS = ["What if money disappeared for one week?", "What if every lie came with a visible sign?",
         "What if you never needed to sleep again?", "What if everyone could see each other's net worth?",
         "What if you could replay any day of your life?", "What if nobody could ever forget a face?"]
TONE = {"new": "plain", "screenplay": "info", "voiced": "info", "built": "info", "rendered": "info", "review": "warn",
        "approved": "ok", "rejected": "bad", "posted": "ok"}
WORDS = {"new": "writing the script", "screenplay": "screenplay written", "voiced": "voices recorded", "built": "ready to render",
         "rendered": "picture rendered", "review": "ready to watch", "approved": "approved", "rejected": "rejected", "posted": "posted"}


def clock(seconds):
    return f"{int(seconds // 60)}:{int(seconds % 60):02d}" if seconds else "-"


class LongVideoPage:
    def build_long_video(self):
        p = self.tabs["Long video"]
        self.lf_proc, self.lf_film, self.lf_view = None, None, None
        self.header(p, "Long video", "An 8-10 minute animated story with 4-5 characters. The app writes the screenplay, gives every "
                                     "character a voice, animates it with HyperFrames and mixes the sound. Nothing is posted until you approve it.",
                    actions=[("Open folder", lambda: G.open_path(lf.FILMS), "ghost"), ("New film", self.lf_new, "primary")])
        body = ctk.CTkFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(1, weight=1)
        body.grid_rowconfigure(0, weight=1)
        left = G.card(body)
        left.grid(row=0, column=0, sticky="nsw", padx=(0, 14))
        fr, self.lf_tree = self.table(left, ("Film", "Stage", "Length"), (210, 118, 56), 16)
        fr.pack(fill="both", expand=True, padx=6, pady=6)
        self.lf_tree.bind("<<TreeviewSelect>>", lambda e: self.lf_select())
        self.lf_detail = ctk.CTkScrollableFrame(body, fg_color="transparent")
        self.lf_detail.grid(row=0, column=1, sticky="nsew")

    # -- list and selection -----------------------------------------------------------------------------
    def refresh_long_video(self):
        films = lf.list_films()
        self.fill(self.lf_tree, [(f.id, (f.meta.get("title") or f.id, WORDS.get(f.meta["stage"], f.meta["stage"]), clock(f.meta.get("seconds")))) for f in films])
        waiting = sum(1 for f in films if f.meta["stage"] == "review")
        self.set_nav_count("Long video", waiting)
        if not self.lf_tree.selection() and films:
            self.lf_tree.selection_set(films[0].id)
        self.lf_select()

    def lf_select(self):
        sel = self.lf_tree.selection()
        try:
            film = lf.Film(lf.FILMS / sel[0]) if sel else None
        except (OSError, ValueError):
            return                                      # film.json is being rewritten: the next poll shows it
        key = (film.id, film.meta["stage"], bool(self.lf_proc)) if film else None
        if key != self.lf_view:
            self.lf_view, self.lf_film = key, film
            self.lf_build_detail()
        elif film:
            self.lf_film = film
            self.lf_progress()

    def lf_running(self):
        return bool(self.lf_proc) and self.lf_proc.poll() is None

    def lf_poll(self):
        if self.lf_proc and self.lf_proc.poll() is not None:
            self.lf_proc = None
            self.lf_view = None
        if self.lf_running() or self.page == "Long video":
            try:
                self.refresh_long_video()
            except Exception:
                pass
        self.root.after(2000, self.lf_poll)

    # -- the detail panel -------------------------------------------------------------------------------
    def lf_build_detail(self):
        for w in self.lf_detail.winfo_children():
            w.destroy()
        f = self.lf_film
        if not f:
            G.label(self.lf_detail, "No films yet. Click New film.", 14, G.C["muted"]).pack(anchor="w", padx=8, pady=20)
            return
        m = f.meta
        box, inner, head = self.section(self.lf_detail, "Status")
        box.pack(fill="x", pady=(0, 12))
        G.label(inner, m.get("title") or f.id, 16, weight="bold", wrap=640).pack(anchor="w")
        self.lf_badge = G.badge(inner, WORDS.get(m["stage"], m["stage"]), TONE.get(m["stage"], "plain"))
        self.lf_badge.pack(anchor="w", pady=(6, 8))
        self.lf_msg = G.label(inner, "", 13, G.C["muted"], wrap=700)
        self.lf_msg.pack(anchor="w")
        self.lf_bar = ctk.CTkProgressBar(inner, height=8, fg_color=G.C["field"], progress_color=G.C["primary"])
        self.lf_bar.pack(fill="x", pady=(8, 4))
        self.lf_err = G.label(inner, "", 12, G.TONES["bad"][1], wrap=700)
        self.lf_err.pack(anchor="w")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x", pady=(10, 0))
        self.lf_buttons(row, f)
        self.lf_progress()
        if f.screenplay.exists():
            self.lf_cast(f)
            self.lf_brief(f)
        if m.get("storyboard") or m.get("plan_checks"):
            self.lf_storyboard(f)
        if m.get("checks"):
            self.lf_checks(m["checks"])
        if f.screenplay.exists():
            self.lf_vids(f)
        if (f.dir / "manifest.json").exists():
            self.lf_record(f)
        if m["stage"] in ("approved", "posted"):
            self.lf_post(f)

    def lf_progress(self):
        f = self.lf_film
        if not f:
            return
        m = f.meta
        self.lf_msg.configure(text=m.get("message") or "")
        self.lf_bar.set(float(m.get("progress") or 0) if self.lf_running() else 0)
        self.lf_err.configure(text=m.get("error") or "")

    def lf_buttons(self, row, f):
        m, B = f.meta, G.button
        add = lambda text, cmd, kind="secondary": B(row, text, cmd, kind).pack(side="left", padx=(0, 8))       # noqa: E731
        if self.lf_running():
            add("Stop", self.lf_stop, "danger")
            return
        if m["stage"] in ("new", "screenplay", "voiced", "built", "rendered"):
            waiting = m.get("gates") and m["stage"] in lf.GATES and m["stage"] not in m.get("approved", [])
            self.lf_draft = ctk.BooleanVar(value=False)
            add(lf.GATE_BUTTON[m["stage"]] if waiting else "Continue making it", self.lf_approve if waiting else self.lf_continue, "primary")
            ctk.CTkCheckBox(row.master, text="Quick draft picture", variable=self.lf_draft, font=G.font(12), text_color=G.C["muted"]).pack(anchor="w", pady=(10, 0))
        if m["stage"] in ("review", "approved", "posted"):
            add("Watch", lambda: os.startfile(str(f.dir / "out" / "final.mp4")), "primary" if m["stage"] == "review" else "secondary")
        if m["stage"] == "review":
            add("Approve", lambda: self.lf_set(lf.approve, f))
            add("Reject...", self.lf_reject, "danger")
        if f.screenplay.exists():
            add("Edit screenplay", lambda: os.startfile(str(f.screenplay)), "ghost")
            if m["stage"] not in ("new",):
                add("Redo voices and picture", lambda: self.lf_redo(f, "screenplay"), "ghost")
        add("Open folder", lambda: G.open_path(f.dir), "ghost")

    def lf_cast(self, f):
        sp = sc.load(f.screenplay)
        box, inner, _ = self.section(self.lf_detail, "Cast", f"{len(sp['scenes'])} scenes, {sc.spoken_words(sp)} spoken words")
        box.pack(fill="x", pady=(0, 12))
        G.label(inner, f"Narrator: {sp['narrator']['voice']} voice", 13, G.C["muted"]).pack(anchor="w")
        for c in sp["cast"]:
            G.label(inner, f"{c['name']}: {c['role']} ({c['voice']})", 13).pack(anchor="w", pady=1)

    def lf_brief(self, f):
        sp = sc.load(f.screenplay)
        brief, claims = sp.get("brief") or {}, sc.claims(sp)
        if not brief.get("question") and not claims:
            return
        box, inner, _ = self.section(self.lf_detail, "Brief and claims", "read before approving")
        box.pack(fill="x", pady=(0, 12))
        for name, key in (("Question", "question"), ("Angle", "angle"), ("Takeaway", "takeaway"), ("Opening image", "first_frame")):
            if brief.get(key):
                G.label(inner, f"{name}: {brief[key]}", 13, wrap=700).pack(anchor="w", pady=1)
        if brief.get("titles"):
            G.label(inner, "Title options: " + "  |  ".join(brief["titles"]), 12, G.C["muted"], wrap=700).pack(anchor="w", pady=(6, 2))
        if claims:
            check = [c for c in claims if c[3]]
            G.label(inner, f"Claims the writer listed: {len(claims)}, {len(check)} marked to check. Verify before you approve.", 13, weight="bold",
                    wrap=700).pack(anchor="w", pady=(10, 2))
            for _, title, claim, flagged in check + [c for c in claims if not c[3]][:10]:
                G.label(inner, ("CHECK  " if flagged else "") + f"{title}: {claim}", 12, G.TONES["warn" if flagged else "plain"][1], wrap=700).pack(anchor="w", pady=1)

    def lf_storyboard(self, f):
        box, inner, _ = self.section(self.lf_detail, "Storyboard", "one frame from every scene, made before the long render")
        box.pack(fill="x", pady=(0, 12))
        sheet = f.dir / "out" / "storyboard.jpg"
        if sheet.exists():
            from PIL import Image
            img = Image.open(sheet)
            self.lf_img = ctk.CTkImage(light_image=img, dark_image=img, size=(700, int(img.height * 700 / img.width)))
            pic = ctk.CTkLabel(inner, image=self.lf_img, text="", cursor="hand2")
            pic.pack(anchor="w", pady=(0, 6))
            pic.bind("<Button-1>", lambda e: os.startfile(str(sheet)))
        for c in (f.meta.get("plan_checks") or {}).get("checks", []):
            G.label(inner, ("OK   " if c["ok"] else "LOOK ") + f"{c['name']}: {c['detail']}", 13, G.TONES["ok" if c["ok"] else "warn"][1], wrap=700).pack(anchor="w")

    def lf_record(self, f):
        man = json.loads((f.dir / "manifest.json").read_text(encoding="utf-8"))
        box, inner, _ = self.section(self.lf_detail, "What went into this film", "for your records")
        box.pack(fill="x", pady=(0, 12))
        rows = (("Script", man["script"]), ("Voices", ", ".join(f"{k}: {v}" for k, v in man["voices"].items())), ("Picture", man["picture"]),
                ("Sound effects", man["sound_effects"]), ("Music", "; ".join(f"{m['file']} ({m['source']})" for m in man["music"]) or "none"),
                ("Generated clips", ", ".join(man["generated_clips"]) or "none"), ("Before you upload", man["disclosure"]))
        for name, text in rows:
            G.label(inner, f"{name}: {text}", 12, G.C["muted"], wrap=700).pack(anchor="w", pady=1)

    def lf_checks(self, checks):
        box, inner, _ = self.section(self.lf_detail, "Automatic checks")
        box.pack(fill="x", pady=(0, 12))
        for c in checks["checks"]:
            G.label(inner, ("OK   " if c["ok"] else "LOOK ") + f"{c['name']}: {c['detail']}", 13, G.TONES["ok" if c["ok"] else "warn"][1]).pack(anchor="w")

    def lf_vids(self, f):
        sp = sc.load(f.screenplay)
        shots = [s for s in sp["scenes"] if s.get("vids")]
        if not shots:
            return
        box, inner, _ = self.section(self.lf_detail, "Google Vids shots", "optional cutaways")
        box.pack(fill="x", pady=(0, 12))
        G.label(inner, "Vids can't be driven by the app, so this part is by hand: open Vids, choose Blank, then Veo, paste the prompt, "
                       "generate (8 seconds), then File > Download > MP4 and import it here. Without a clip the scene simply stays animated.",
                12, G.C["muted"], wrap=700).pack(anchor="w", pady=(0, 8))
        for s in shots:
            have = (f.dir / "vids" / f"{s['id']}.mp4").exists()
            G.label(inner, f"{s['title']}  ({'imported' if have else 'not yet'})", 13, weight="bold").pack(anchor="w", pady=(6, 0))
            G.label(inner, s["vids"], 12, G.C["muted"], wrap=700).pack(anchor="w")
            r = ctk.CTkFrame(inner, fg_color="transparent")
            r.pack(anchor="w", pady=(4, 0))
            G.button(r, "Copy prompt", lambda t=s["vids"]: self.lf_copy(t), "ghost").pack(side="left", padx=(0, 6))
            G.button(r, "Open Google Vids", lambda: webbrowser.open(VIDS_URL), "ghost").pack(side="left", padx=(0, 6))
            G.button(r, "Import clip...", lambda sid=s["id"]: self.lf_import(f, sid), "secondary").pack(side="left")

    def lf_post(self, f):
        pack_file = f.dir / "upload_pack.json"
        if not pack_file.exists():
            return
        pack = json.loads(pack_file.read_text(encoding="utf-8"))
        box, inner, _ = self.section(self.lf_detail, "Upload by hand", "long films aren't sent through Upload-Post")
        box.pack(fill="x", pady=(0, 12))
        r = ctk.CTkFrame(inner, fg_color="transparent")
        r.pack(anchor="w")
        for text, key in (("Copy title", "title"), ("Copy description", "description"), ("Copy tags", "tags")):
            G.button(r, text, lambda k=key: self.lf_copy(pack[k]), "secondary").pack(side="left", padx=(0, 8))
        G.button(r, "Open YouTube upload", lambda: webbrowser.open("https://www.youtube.com/upload"), "ghost").pack(side="left", padx=(0, 8))
        G.button(r, "Show files", lambda: subprocess.Popen(["explorer", "/select,", os.path.normpath(pack["file"])]), "ghost").pack(side="left", padx=(0, 8))
        if f.meta["stage"] == "approved":
            G.button(r, "I posted it", lambda: self.lf_set(lf.mark_posted, f), "primary").pack(side="left")

    # -- actions ----------------------------------------------------------------------------------------
    def lf_copy(self, text):
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.set_status("Copied.")

    def lf_set(self, fn, film, *args):
        fn(film, *args)
        self.lf_view = None
        self.refresh_long_video()

    def lf_redo(self, film, stage):
        if messagebox.askyesno("Redo", "Record the voices again and render the picture again? It takes a while."):
            lf.redo_from(film, stage)
            self.lf_continue()

    def lf_reject(self):
        top, frm = self.dialog("Reject this film", 520)
        G.label(frm, "What was wrong? The next films are written with this in mind.", 13, wrap=480).pack(anchor="w")
        box = G.textbox(frm, 90)
        box.pack(fill="x", pady=10)

        def go():
            reason = box.get("1.0", "end").strip()
            top.destroy()
            self.lf_set(lf.reject, self.lf_film, reason or "no reason given")
        G.button(frm, "Reject", go, "danger").pack(anchor="e")

    def lf_import(self, film, scene_id):
        path = filedialog.askopenfilename(title="Choose the clip you made in Google Vids", filetypes=[("Video", "*.mp4 *.mov *.webm"), ("All files", "*.*")])
        if not path:
            return
        (film.dir / "vids").mkdir(exist_ok=True)
        shutil.copyfile(path, film.dir / "vids" / f"{scene_id}.mp4")
        if messagebox.askyesno("Clip imported", "Use it now? The picture is rendered again (the voices are kept)."):
            lf.redo_from(film, "voiced")
            self.lf_continue()
        else:
            self.lf_view = None
            self.refresh_long_video()

    def lf_approve(self):
        """The person has read the script or looked at the storyboard: go past that stop."""
        film = self.lf_film
        lf.approve_gate(film, film.meta["stage"])
        self.lf_view = None
        self.lf_continue()

    def lf_continue(self):
        film = self.lf_film
        if self.lf_running() or lf.busy():
            messagebox.showinfo("Busy", "A long film is being made right now. Wait for it to finish.")
            return
        args = ["--longform", "all", film.id] + (["--draft"] if getattr(self, "lf_draft", None) and self.lf_draft.get() else [])
        self.lf_proc = subprocess.Popen(["cmd", "/c", str(G.RUN_BAT), *args], cwd=str(G.HERE), creationflags=G.NO_WINDOW)
        self.lf_view = None
        self.set_status("Making the film. Progress is shown here; details are in Logs.")
        self.refresh_long_video()

    def lf_stop(self):
        if self.lf_proc and messagebox.askyesno("Stop", "Stop making this film? You can continue it later from where it stopped."):
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(self.lf_proc.pid)], capture_output=True, creationflags=G.NO_WINDOW)
            self.lf_proc = None
            self.lf_view = None
            self.refresh_long_video()

    def lf_new(self):
        top, frm = self.dialog("New long film", 560)
        G.label(frm, "What is the film about? A \"What if...\" question works best.", 13, wrap=520).pack(anchor="w")
        topic = ctk.StringVar(value=IDEAS[0])
        G.combo(frm, topic, IDEAS, 520).pack(anchor="w", pady=(6, 10))
        row = ctk.CTkFrame(frm, fg_color="transparent")
        row.pack(anchor="w", pady=(0, 14))
        minutes, cast = ctk.StringVar(value="9"), ctk.StringVar(value="5")
        G.label(row, "Length (minutes)", 12, G.C["muted"]).pack(side="left")
        G.option(row, minutes, ["8", "9", "10"], 80).pack(side="left", padx=(8, 20))
        G.label(row, "Characters", 12, G.C["muted"]).pack(side="left")
        G.option(row, cast, ["4", "5"], 80).pack(side="left", padx=8)
        gates = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(frm, text="Pause for my review: after the script, and after the storyboard", variable=gates, font=G.font(12),
                        text_color=G.C["muted"]).pack(anchor="w", pady=(0, 10))
        G.label(frm, "The script is written by your Claude, then voiced and animated. Expect about half an hour of waiting "
                     "(the PC stays usable). Nothing is posted.", 12, G.C["faint"], wrap=520).pack(anchor="w", pady=(0, 14))

        def go():
            text, pause = topic.get().strip(), gates.get()
            top.destroy()
            if text:
                film = lf.new_film(text, int(minutes.get()), int(cast.get()), pause)
                self.lf_view = None
                self.refresh_long_video()
                self.lf_tree.selection_set(film.id)
                self.lf_film = film
                self.lf_continue()
        G.button(frm, "Make the film", go, "primary").pack(anchor="e")
