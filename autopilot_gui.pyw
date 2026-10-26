"""Shorts Autopilot - Windows app for setup, review/approval and monitoring (dark, CustomTkinter).

Start it with "Shorts Autopilot.bat" (runs MPT's pythonw, so no console window).
All automation rules live in daily_shorts.py; this file is only the interface.
    pythonw autopilot_gui.pyw                              # open the app
    python  autopilot_gui.pyw --screenshot out.png [Page]  # build every page, save a screenshot, exit
"""

import json
import os
import queue
import re
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
import webbrowser
from datetime import datetime, timedelta
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

try:
    import customtkinter as ctk
except ImportError:  # MPT updates (uv sync) can remove it; say how to fix instead of crashing silently
    messagebox.showerror("Shorts Autopilot", "CustomTkinter is missing from MoneyPrinterTurbo's Python.\n\n"
                         "Run install.bat again (it re-adds it), then reopen the app.")
    raise

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import daily_shorts as eng  # noqa: E402

TASK = "MPT Daily Shorts"
RUN_BAT = HERE / "run_daily.bat"
ENV_BAT = HERE / "env.bat"
NO_WINDOW = 0x08000000  # CREATE_NO_WINDOW
LLM_PROVIDERS = ["claude_code", "deepseek", "gemini", "openai", "openrouter", "ollama"]
NO_KEY_PROVIDERS = {"claude_code", "ollama"}
MUSIC_LABELS = {"auto": "Best fit for each video (AI picks)", "fixed": "Always the same track",
                "none": "No music (voice only)"}
ANSI = re.compile(r"\x1b\[[0-9;]*m")
PAGES = ("Dashboard", "Review", "History", "Music", "Clips", "Settings", "Setup", "Logs")

# ---- Dark theme: warm near-black surfaces, one light accent, muted semantic tones ----------
C = {
    "bg": "#141413", "side": "#0F0F0E", "card": "#1B1B1A", "field": "#232322", "border": "#2C2C2A",
    "hover": "#262624", "select": "#34332F", "text": "#ECEBE7", "muted": "#9A9893", "faint": "#6B6965",
    "primary": "#ECEBE7", "primary_text": "#141413", "primary_hover": "#D3D1CB",
}
TONES = {  # (background, text) - washed-out pastels adapted to a dark canvas
    "ok": ("#1D2A1F", "#8CC293"), "bad": ("#311F1E", "#E8958F"), "warn": ("#2F2817", "#DDB863"),
    "info": ("#1A2733", "#85B9E2"), "plain": ("#242423", "#A9A7A1"),
}
UI, SERIF, MONO = "Segoe UI", "Georgia", "Cascadia Mono"


# ---- Helpers (no UI) ------------------------------------------------------------

def mpt_dir():
    if not ENV_BAT.exists() and (HERE / "env.example.bat").exists():
        shutil.copyfile(HERE / "env.example.bat", ENV_BAT)
    text = ENV_BAT.read_text(encoding="utf-8", errors="ignore") if ENV_BAT.exists() else ""
    m = re.search(r'set\s+"MPT_DIR=([^"]*)"', text, re.I)
    return Path(m.group(1)) if m else Path(r"D:\MPT")


def set_mpt_dir(path):
    ENV_BAT.write_text(
        "@echo off\r\nrem Machine-specific settings (written by the Shorts Autopilot app).\r\n"
        f'set "MPT_DIR={path}"\r\n', encoding="utf-8")


def run_hidden(cmd, timeout=60):
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL,
                       creationflags=NO_WINDOW, encoding="utf-8", errors="replace")
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def powershell(script, timeout=60):
    return run_hidden(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script], timeout)


def task_info():
    script = (
        f"$t=Get-ScheduledTask -TaskName '{TASK}' -ErrorAction SilentlyContinue;"
        "if(!$t){'{}'}else{$i=Get-ScheduledTaskInfo -TaskName $t.TaskName;"
        "$f={param($d) if($d -and $d.Year -gt 2000){$d.ToString('yyyy-MM-dd HH:mm')}else{''}};"
        "[pscustomobject]@{state=\"$($t.State)\";next=(& $f $i.NextRunTime);last=(& $f $i.LastRunTime);"
        "result=$i.LastTaskResult;action=\"$($t.Actions[0].Arguments)\";"
        "times=@($t.Triggers|%{([datetime]$_.StartBoundary).ToString('HH:mm')})}|ConvertTo-Json -Compress}")
    code, out = powershell(script)
    try:
        return json.loads(out.strip().splitlines()[-1]) if code == 0 and out.strip() else {}
    except (ValueError, IndexError):
        return {}


def register_schedule(times):
    quoted = ",".join(f"'{t}'" for t in times)
    return powershell(f"& '{HERE / 'setup_schedule.ps1'}' -Times {quoted}")


def webui_running():
    with socket.socket() as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", 8501)) == 0


def read_mpt_config():
    import toml
    path = mpt_dir() / "config.toml"
    return toml.load(path) if path.exists() else {}


def write_mpt_config(changes):
    """Read config.toml fresh, change only these [app] keys, replace atomically
    (same serializer MPT uses), so values changed elsewhere are never overwritten."""
    import toml
    path = mpt_dir() / "config.toml"
    data = toml.load(path) if path.exists() else {}
    data.setdefault("app", {}).update(changes)
    tmp = path.with_name("config.toml.tmp")
    tmp.write_text(toml.dumps(data), encoding="utf-8")
    os.replace(tmp, path)


def ffmpeg_exe():
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return shutil.which("ffmpeg")


def make_thumb(video, out):
    exe = ffmpeg_exe()
    if not exe:
        return False
    out.parent.mkdir(exist_ok=True)
    run_hidden([exe, "-y", "-v", "error", "-ss", "4", "-i", str(video), "-frames:v", "1",
                "-vf", "scale=360:-1", str(out)], timeout=60)
    return out.exists()


def tail(path, n=400):
    if not Path(path).exists():
        return []
    with open(path, encoding="utf-8", errors="replace") as f:
        return [ANSI.sub("", l.rstrip("\n")) for l in f.readlines()[-n:]]


def human(nbytes):
    for unit in ("B", "KB", "MB", "GB"):
        if nbytes < 1024 or unit == "GB":
            return f"{nbytes:.0f} {unit}" if unit == "B" else f"{nbytes:.1f} {unit}"
        nbytes /= 1024


def open_path(p):
    os.startfile(str(p))  # noqa: S606 - local files/folders only


def when(iso):
    return (iso or "")[:16].replace("T", " ")


# ---- Small UI kit ------------------------------------------------------------------

def font(size=13, weight="normal", family=UI):
    return ctk.CTkFont(family=family, size=size, weight=weight)


def label(parent, text="", size=13, color=None, weight="normal", family=UI, wrap=0, **kw):
    return ctk.CTkLabel(parent, text=text, font=font(size, weight, family), text_color=color or C["text"],
                        wraplength=wrap, justify="left", anchor="w", **kw)


def card(parent, **kw):
    return ctk.CTkFrame(parent, fg_color=C["card"], corner_radius=10, border_width=1, border_color=C["border"], **kw)


def button(parent, text, command, kind="secondary", width=0, **kw):
    styles = {
        "primary": dict(fg_color=C["primary"], hover_color=C["primary_hover"], text_color=C["primary_text"]),
        "secondary": dict(fg_color=C["field"], hover_color=C["select"], text_color=C["text"],
                          border_width=1, border_color=C["border"]),
        "danger": dict(fg_color="transparent", hover_color=TONES["bad"][0], text_color=TONES["bad"][1],
                       border_width=1, border_color="#4A2B29"),
        "ghost": dict(fg_color="transparent", hover_color=C["hover"], text_color=C["muted"]),
    }
    w = width or max(80, 9 * len(text) + 28)
    return ctk.CTkButton(parent, text=text, command=command, corner_radius=6, height=34, width=w,
                         font=font(13, "bold" if kind == "primary" else "normal"), **styles[kind], **kw)


def badge(parent, text, tone="plain"):
    bg, fg = TONES[tone]
    return ctk.CTkLabel(parent, text=f"  {text.upper()}  ", fg_color=bg, text_color=fg, corner_radius=10,
                        height=22, font=font(10, "bold"))


def set_badge(widget, text, tone):
    bg, fg = TONES[tone]
    widget.configure(text=f"  {text.upper()}  ", fg_color=bg, text_color=fg)


def entry(parent, var=None, width=260, show=None, placeholder=""):
    return ctk.CTkEntry(parent, textvariable=var, width=width, height=34, corner_radius=6, show=show,
                        fg_color=C["field"], border_color=C["border"], text_color=C["text"],
                        placeholder_text=placeholder or None, font=font(13))


def textbox(parent, height=90):
    return ctk.CTkTextbox(parent, height=height, corner_radius=6, fg_color=C["field"], border_width=1,
                          border_color=C["border"], text_color=C["text"], font=font(13), wrap="word")


def option(parent, var, values, width=260, command=None):
    return ctk.CTkOptionMenu(parent, variable=var, values=values or ["-"], width=width, height=34, corner_radius=6,
                             fg_color=C["field"], button_color=C["field"], button_hover_color=C["select"],
                             text_color=C["text"], dropdown_fg_color=C["card"], dropdown_hover_color=C["select"],
                             dropdown_text_color=C["text"], font=font(13), dropdown_font=font(13), command=command)


def combo(parent, var, values, width=260):
    return ctk.CTkComboBox(parent, variable=var, values=values or [""], width=width, height=34, corner_radius=6,
                           fg_color=C["field"], border_color=C["border"], button_color=C["field"],
                           button_hover_color=C["select"], text_color=C["text"], dropdown_fg_color=C["card"],
                           dropdown_hover_color=C["select"], dropdown_text_color=C["text"], font=font(13))


def set_text(box, text, readonly=False):
    box.configure(state="normal")
    box.delete("1.0", "end")
    box.insert("1.0", text)
    if readonly:
        box.configure(state="disabled")


# ---- App -----------------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.proc = None
        self.proc_label = ""
        self.task = {}
        self.doctor = {}
        self.current = None              # (folder, stem) shown in the Review detail panel
        self.thumb_img = None
        self.page = None
        root.title("Shorts Autopilot")
        root.configure(fg_color=C["bg"])
        self.scale = ctk.ScalingTracker.get_window_scaling(root)
        w, h = min(1320, int(root.winfo_screenwidth() / self.scale) - 40), \
            min(860, int(root.winfo_screenheight() / self.scale) - 90)
        root.geometry(f"{w}x{h}+20+10")
        root.minsize(1060, 640)
        self.style_tables()

        root.grid_columnconfigure(1, weight=1)
        root.grid_rowconfigure(0, weight=1)
        self.build_sidebar()
        self.content = ctk.CTkFrame(root, fg_color=C["bg"], corner_radius=0)
        self.content.grid(row=0, column=1, sticky="nsew")
        self.content.grid_columnconfigure(0, weight=1)
        self.content.grid_rowconfigure(0, weight=1)
        self.tabs = {}
        for name in PAGES:
            page = ctk.CTkFrame(self.content, fg_color=C["bg"], corner_radius=0)
            page.grid(row=0, column=0, sticky="nsew", padx=28, pady=(22, 18))
            self.tabs[name] = page
        for name in PAGES:
            getattr(self, f"build_{name.lower()}")()
        self.show("Dashboard")

        root.bind("<Control-r>", lambda e: self.refresh_all())
        self.root.after(100, self.poll_queue)
        self.refresh_all()
        self.root.after(30000, self.auto_refresh)

    # -- look ---------------------------------------------------------------------------
    def style_tables(self):
        s = ttk.Style()
        s.theme_use("clam")
        row = int(32 * self.scale)
        s.configure("Treeview", background=C["card"], fieldbackground=C["card"], foreground=C["text"],
                    rowheight=row, borderwidth=0, relief="flat", font=(UI, -int(13 * self.scale)))
        s.configure("Treeview.Heading", background=C["card"], foreground=C["muted"], relief="flat",
                    borderwidth=0, font=(UI, -int(11 * self.scale), "bold"), padding=(6, 6))
        s.map("Treeview", background=[("selected", C["select"])], foreground=[("selected", C["text"])])
        s.map("Treeview.Heading", background=[("active", C["card"])], foreground=[("active", C["text"])])
        s.layout("Treeview", [("Treeview.treearea", {"sticky": "nswe"})])

    def table(self, parent, columns, widths, height=8):
        frame = ctk.CTkFrame(parent, fg_color="transparent")
        t = ttk.Treeview(frame, columns=columns, show="headings", height=height, selectmode="browse")
        for c, w in zip(columns, widths):
            t.heading(c, text=c.upper(), anchor="w")
            t.column(c, width=int(w * self.scale), anchor="w", stretch=w > 150)
        t.tag_configure("odd", background="#1F1F1E")
        t.tag_configure("muted", foreground=C["muted"])
        sb = ctk.CTkScrollbar(frame, command=t.yview, button_color=C["border"], button_hover_color=C["select"])
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, t

    @staticmethod
    def fill(tree, rows):
        sel = tree.selection()
        tree.delete(*tree.get_children())
        for i, (iid, values) in enumerate(rows):
            tree.insert("", "end", iid=iid, values=values, tags=("odd",) if i % 2 else ())
        keep = [s for s in sel if tree.exists(s)]
        if keep:
            tree.selection_set(keep)

    def header(self, page, title, subtitle="", actions=()):
        bar = ctk.CTkFrame(page, fg_color="transparent")
        bar.pack(fill="x", pady=(0, 16))
        for text, cmd, kind in reversed(actions):
            button(bar, text, cmd, kind).pack(side="right", padx=(8, 0), anchor="n")
        left = ctk.CTkFrame(bar, fg_color="transparent")
        left.pack(side="left", fill="x", expand=True)
        label(left, title, 26, family=SERIF).pack(anchor="w")
        sub = label(left, subtitle, 13, C["muted"], wrap=620 - 120 * len(actions) // 2)
        sub.pack(anchor="w", pady=(2, 0))
        return sub

    def section(self, parent, title, note=""):
        """A titled card; returns its inner frame."""
        box = card(parent)
        head = ctk.CTkFrame(box, fg_color="transparent")
        head.pack(fill="x", padx=18, pady=(14, 6))
        label(head, title, 14, weight="bold").pack(side="left")
        if note:
            label(head, note, 12, C["muted"]).pack(side="left", padx=10)
        inner = ctk.CTkFrame(box, fg_color="transparent")
        inner.pack(fill="both", expand=True, padx=18, pady=(0, 16))
        return box, inner, head

    def dialog(self, title, width=560):
        top = ctk.CTkToplevel(self.root)
        top.title(title)
        top.configure(fg_color=C["bg"])
        top.transient(self.root)
        top.resizable(False, False)
        top.after(80, top.grab_set)
        top.after(80, top.focus_force)
        frm = ctk.CTkFrame(top, fg_color="transparent", width=width)
        frm.pack(fill="both", expand=True, padx=22, pady=20)
        return top, frm

    # -- sidebar ------------------------------------------------------------------------
    def build_sidebar(self):
        side = ctk.CTkFrame(self.root, fg_color=C["side"], corner_radius=0, width=220)
        side.grid(row=0, column=0, sticky="nsw")
        side.grid_propagate(False)
        side.pack_propagate(False)
        label(side, "Shorts", 22, family=SERIF).pack(anchor="w", padx=22, pady=(24, 0))
        label(side, "Autopilot", 22, C["muted"], family=SERIF).pack(anchor="w", padx=22, pady=(0, 22))
        self.nav = {}
        for name in PAGES:
            b = ctk.CTkButton(side, text=name, anchor="w", height=36, corner_radius=6, font=font(14),
                              fg_color="transparent", hover_color=C["hover"], text_color=C["muted"],
                              command=lambda n=name: self.show(n))
            b.pack(fill="x", padx=12, pady=1)
            self.nav[name] = b
        bottom = ctk.CTkFrame(side, fg_color="transparent")
        bottom.pack(side="bottom", fill="x", padx=16, pady=18)
        self.run_badge = badge(bottom, "idle", "plain")
        self.run_badge.pack(anchor="w")
        self.status = label(bottom, "", 12, C["muted"], wrap=180)
        self.status.pack(anchor="w", pady=(8, 10))
        label(bottom, "Ctrl+R refresh", 11, C["faint"], family=MONO).pack(anchor="w")

    def show(self, name):
        self.tabs[name].tkraise()
        self.page = name
        for n, b in self.nav.items():
            on = n == name
            b.configure(fg_color=C["select"] if on else "transparent", text_color=C["text"] if on else C["muted"])
        if name == "Logs":
            self.refresh_logs()

    def set_nav_count(self, name, count):
        self.nav[name].configure(text=f"{name}   {count}" if count else name)

    # -- background work: never block the window ---------------------------------------------
    def bg(self, fn, done=None):
        def work():
            try:
                result = fn()
            except Exception as e:  # report instead of dying silently in a thread
                result = e
            if done:
                self.q.put((done, result))
        threading.Thread(target=work, daemon=True).start()

    def poll_queue(self):
        try:
            while True:
                done, result = self.q.get_nowait()
                done(result)
        except queue.Empty:
            pass
        if self.proc and self.proc.poll() is not None:
            code = self.proc.returncode
            self.proc = None
            self.set_status(f"{self.proc_label} finished" + ("." if code == 0 else f" with problems (exit {code}). "
                                                              "See Logs."))
            self.refresh_all()
        self.root.after(200, self.poll_queue)

    def auto_refresh(self):
        self.refresh_all(lists_only=True)
        self.root.after(30000, self.auto_refresh)

    def set_status(self, text):
        self.status.configure(text=text)

    def busy(self):
        return bool(self.proc) or eng.is_running()

    def start_run(self, args, label_text):
        if self.busy():
            messagebox.showinfo("Busy", "A run is already in progress. Wait for it to finish.")
            return
        self.proc = subprocess.Popen(["cmd", "/c", str(RUN_BAT), *args], cwd=str(HERE), creationflags=NO_WINDOW)
        self.proc_label = label_text
        self.set_status(f"{label_text} running. Progress is in Logs.")
        self.refresh_run_badge()

    def refresh_run_badge(self):
        if self.proc:
            set_badge(self.run_badge, f"{self.proc_label} running", "info")
        elif eng.is_running():
            set_badge(self.run_badge, "scheduled run active", "info")
        else:
            set_badge(self.run_badge, "idle", "plain")

    def refresh_all(self, lists_only=False):
        self.refresh_dashboard()
        self.refresh_review_lists()
        self.refresh_history()
        self.refresh_music()
        self.refresh_clips()
        if self.page == "Logs":
            self.refresh_logs()
        if not lists_only:
            self.load_settings_form()
            self.refresh_setup()
        self.refresh_run_badge()
        self.bg(task_info, self.on_task_info)

    def on_task_info(self, info):
        self.task = info if isinstance(info, dict) else {}
        self.refresh_dashboard()
        self.refresh_setup_schedule()

    # ---- Dashboard -----------------------------------------------------------------------
    def build_dashboard(self):
        p = self.tabs["Dashboard"]
        self.dash_sub = self.header(p, "Dashboard", "", actions=[
            ("Dry run", self.dry_run, "ghost"),
            ("Render one video", lambda: self.start_run(["--render"], "Render"), "secondary"),
            ("Run now", self.run_now, "primary")])

        stats = ctk.CTkFrame(p, fg_color="transparent")
        stats.pack(fill="x")
        self.card = {}
        for i, (key, title) in enumerate([("quota", "Uploads this month"), ("next", "Next upload"),
                                          ("queue", "Waiting for you"), ("auto", "Automation")]):
            stats.grid_columnconfigure(i, weight=1, uniform="stat")
            box = card(stats)
            box.grid(row=0, column=i, sticky="nsew", padx=(0 if i == 0 else 6, 0 if i == 3 else 6))
            label(box, title.upper(), 11, C["muted"], weight="bold").pack(anchor="w", padx=18, pady=(16, 4))
            big = label(box, "-", 26, family=SERIF)
            big.pack(anchor="w", padx=18)
            small = label(box, "", 12, C["muted"], wrap=170)
            small.pack(anchor="w", padx=18, pady=(2, 16))
            self.card[key] = (box, big, small)
        self.quota_bar = ctk.CTkProgressBar(self.card["quota"][0], height=6, corner_radius=3,
                                            fg_color=C["field"], progress_color=C["primary"])
        self.quota_bar.pack(fill="x", padx=18, pady=(0, 18))
        self.next_badge = badge(self.card["next"][0], "-", "plain")
        self.next_badge.pack(anchor="w", padx=18, pady=(0, 18))
        button(self.card["queue"][0], "Open Review", lambda: self.show("Review"), "secondary").pack(
            anchor="w", padx=18, pady=(0, 16))
        self.auto_badge = badge(self.card["auto"][0], "-", "plain")
        self.auto_badge.pack(anchor="w", padx=18, pady=(0, 18))

        _, self.alerts, _ = self.section(p, "Needs your attention")
        self.alerts.master.pack(fill="x", pady=(12, 12))

        mid = ctk.CTkFrame(p, fg_color="transparent")
        mid.pack(fill="both", expand=True)
        mid.grid_columnconfigure(0, weight=5, uniform="mid")
        mid.grid_columnconfigure(1, weight=6, uniform="mid")
        mid.grid_rowconfigure(0, weight=1)
        box, inner, _ = self.section(mid, "Monthly uploads calendar")
        box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        self.cal_summary = label(inner, "", 13, C["muted"], wrap=380)
        self.cal_summary.pack(anchor="w", pady=(0, 10))
        fr, self.cal_tree = self.table(inner, ("When", "Video"), (150, 330), height=9)
        fr.pack(fill="both", expand=True)
        box, inner, _ = self.section(mid, "Recent runs")
        box.grid(row=0, column=1, sticky="nsew", padx=(6, 0))
        fr, self.runs_tree = self.table(inner, ("Time", "Mode", "Upload", "Rendered", "Problems"),
                                        (120, 60, 140, 170, 170), height=9)
        fr.pack(fill="both", expand=True)

    def run_now(self):
        if messagebox.askyesno("Run now", "This does exactly what a scheduled run does:\n\n"
                               "- uploads the next approved video IF an upload slot is due\n"
                               "- renders a new video if fewer than the buffer are waiting\n\nContinue?"):
            self.start_run([], "Run")

    def dry_run(self):
        self.start_run(["--dry-run"], "Dry run")
        self.show("Logs")

    def refresh_dashboard(self):
        s = eng.load_settings()
        now = datetime.now()
        ledger = eng.load_ledger()
        limit = int(s["monthly_uploads"])
        used = eng.used_this_month(ledger, now)
        _, big, small = self.card["quota"]
        big.configure(text=f"{used} / {limit}")
        small.configure(text=f"{max(limit - used, 0)} free uploads left in {now:%B}")
        self.quota_bar.set(min(used / max(limit, 1), 1))

        times = []
        try:
            times = eng.parse_times(s["run_times"])
            _, month_end = eng.month_bounds(now)
            _, next_end = eng.month_bounds(month_end + timedelta(days=1))
            plan = eng.plan_uploads(now, ledger, limit, times, next_end)
        except ValueError:
            plan = []
        approved = eng.stems(eng.APPROVED)
        review = eng.stems(eng.REVIEW)
        _, big, small = self.card["next"]
        if plan:
            big.configure(text=plan[0].strftime("%a %d %b"))
            small.configure(text=plan[0].strftime("at %H:%M"))
            set_badge(self.next_badge, "video ready" if approved else "needs approval", "ok" if approved else "warn")
        else:
            big.configure(text="-")
            small.configure(text="no upload slots planned")
            set_badge(self.next_badge, "none", "plain")

        rows = []
        for i, t in enumerate(plan):
            video = ("ready: " + (eng.load_meta(eng.APPROVED, approved[i]).get("title") or approved[i])
                     if i < len(approved) else "needs an approved video")
            rows.append((t.isoformat(), (t.strftime("%a %d %b  %H:%M"), video)))
        self.fill(self.cal_tree, rows)
        self.cal_summary.configure(text=self.calendar_summary(now, ledger, limit, times, plan))

        _, big, small = self.card["queue"]
        big.configure(text=f"{len(review)} to review")
        small.configure(text=f"{len(approved)} approved and queued for upload")
        self.set_nav_count("Review", len(review))

        _, big, small = self.card["auto"]
        state = self.task.get("state") or "Not registered"
        big.configure(text=state)
        runs = eng.recent_runs(30)
        last = runs[-1] if runs else None
        small.configure(text=f"Next run {self.task.get('next') or '-'}  ·  times {', '.join(self.task.get('times') or []) or '-'}")
        if last:
            set_badge(self.auto_badge, f"last run {when(last.get('time'))[11:]} ok" if not last.get("errors")
                      else "last run had problems", "ok" if not last.get("errors") else "bad")
        else:
            set_badge(self.auto_badge, "no runs yet", "plain")
        self.dash_sub.configure(text=f"{now:%A %d %B}.  "
                                     f"{'Schedule active' if state == 'Ready' else 'Schedule: ' + state}.")

        self.fill(self.runs_tree, [
            (str(i), (when(r.get("time")), r.get("mode", ""),
                      f"{r.get('upload') or '-'} {r.get('title') or ''}".strip(),
                      r.get("rendered") or "-", "; ".join(r.get("errors") or []) or "-"))
            for i, r in reversed(list(enumerate(runs)))])
        self.show_alerts(plan, approved)
        self.refresh_run_badge()

    def calendar_summary(self, now, ledger, limit, times, plan):
        """Two plain lines describing how the month is spread, from the same plan the calendar shows."""
        if not times:
            return "Run times are not set correctly (Settings)."
        used = eng.used_this_month(ledger, now)
        rest = [t for t in plan if t.month == now.month]
        lines = [f"This month: {used} of {limit} used, {max(limit - used, 0)} left."]
        if not rest:
            lines.append("No uploads left this month.")
            return "\n".join(lines)
        days = sorted({t.date() for t in rest})
        # A "full spread" is a month that starts fresh (uploads from the 1st week, most of the quota left).
        if rest[0].day <= 7 and len(rest) >= limit - 1 and len(days) > 1:
            gap = (days[-1] - days[0]).days / (len(days) - 1)
            lines.append(f"Full spread: about one upload every {gap:.0f} days, {rest[0]:%d %b} to {rest[-1]:%d %b}.")
        else:
            lines.append(f"Catching up: {len(rest)} left, {rest[0]:%d %b %H:%M} to {rest[-1]:%d %b %H:%M}, "
                         f"{len(times)} run times a day.")
        return "\n".join(lines)

    def show_alerts(self, plan, approved):
        for w in self.alerts.winfo_children():
            w.destroy()
        alerts = []
        if plan and not approved and plan[0] - datetime.now() < timedelta(hours=24):
            alerts.append(("bad", "Upload due", f"{plan[0]:%a %H:%M} needs an approved video. Approve one in Review.",
                           ("Open Review", lambda: self.show("Review"))))
        if eng.stems(eng.CHECK):
            alerts.append(("bad", "Check upload", f"{len(eng.stems(eng.CHECK))} upload(s) had an unclear result. "
                                                  "Confirm them in History.", ("Open History", lambda: self.show("History"))))
        mpt = mpt_dir()
        if not (mpt / ".venv" / "Scripts" / "python.exe").exists():
            alerts.append(("bad", "Setup", f"MoneyPrinterTurbo not found in {mpt}.", ("Open Setup", lambda: self.show("Setup"))))
        try:
            if read_mpt_config().get("app", {}).get("upload_post_auto_upload"):
                alerts.append(("bad", "Unsafe", "MPT auto-upload is on: videos could skip your approval. "
                                                "Save the Upload-Post row in Setup to turn it off.",
                               ("Open Setup", lambda: self.show("Setup"))))
        except Exception as e:
            alerts.append(("warn", "Config", f"Can't read MPT config: {e}", None))
        if webui_running():
            alerts.append(("warn", "WebUI open", "MPT's WebUI rewrites config.toml and can undo changes. Close it.", None))
        if not self.task:
            alerts.append(("warn", "Schedule", "Not registered yet, or still loading.", ("Open Setup", lambda: self.show("Setup"))))
        elif self.task.get("state") == "Disabled":
            alerts.append(("warn", "Paused", "The schedule is paused.", ("Open Settings", lambda: self.show("Settings"))))
        if not eng.usable_tracks():
            alerts.append(("plain", "Voice only", "No approved music, so videos have no background track.",
                           ("Open Music", lambda: self.show("Music"))))
        if not [a for a in alerts if a[0] in ("bad", "warn")]:
            alerts.insert(0, ("ok", "All good", "Nothing needs you right now.", None))
        for tone, tag, text, action in alerts:
            row = ctk.CTkFrame(self.alerts, fg_color="transparent")
            row.pack(fill="x", pady=3)
            badge(row, tag, tone).pack(side="left")
            label(row, text, 13, C["text"] if tone != "plain" else C["muted"]).pack(side="left", padx=12)
            if action:
                button(row, action[0], action[1], "ghost").pack(side="right")

    # ---- Review ----------------------------------------------------------------------------
    def build_review(self):
        p = self.tabs["Review"]
        self.header(p, "Review", "Watch each new video, fix the title if you like, then approve or reject it. "
                                 "Ctrl+S saves, Ctrl+Enter approves.")
        body = ctk.CTkFrame(p, fg_color="transparent")
        body.pack(fill="both", expand=True)
        body.grid_columnconfigure(0, weight=4, uniform="rv")
        body.grid_columnconfigure(1, weight=7, uniform="rv")
        body.grid_rowconfigure(0, weight=1)

        left = card(body)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 8))
        self.list_mode = ctk.StringVar(value="To review")
        self.seg = ctk.CTkSegmentedButton(left, values=["To review", "Approved"], variable=self.list_mode,
                                          command=self.switch_list, font=font(13), height=32,
                                          fg_color=C["field"], selected_color=C["select"],
                                          selected_hover_color=C["select"], unselected_color=C["field"],
                                          unselected_hover_color=C["hover"], text_color=C["text"])
        self.seg.pack(fill="x", padx=16, pady=(16, 10))
        self.review_frame, self.review_tree = self.table(left, ("Rendered", "Title"), (110, 280), height=12)
        self.approved_frame, self.approved_tree = self.table(left, ("#", "Title"), (36, 350), height=12)
        self.review_frame.pack(fill="both", expand=True, padx=16)
        self.review_tree.bind("<<TreeviewSelect>>", lambda e: self.select_video(eng.REVIEW, self.review_tree))
        self.approved_tree.bind("<<TreeviewSelect>>", lambda e: self.select_video(eng.APPROVED, self.approved_tree))
        self.list_empty = label(left, "", 13, C["muted"], wrap=230)
        self.list_empty.pack(anchor="w", padx=16, pady=(8, 0))
        lbar = ctk.CTkFrame(left, fg_color="transparent")
        lbar.pack(fill="x", padx=16, pady=14)
        self.back_btn = button(lbar, "Back to review", self.back_to_review, "secondary")
        button(lbar, "Open folder", lambda: open_path(eng.APPROVED if self.list_mode.get() == "Approved" else eng.REVIEW),
               "ghost").pack(side="right")

        d = card(body)
        d.grid(row=0, column=1, sticky="nsew", padx=(8, 0))
        self.detail = d
        top = ctk.CTkFrame(d, fg_color="transparent")
        top.pack(fill="x", padx=20, pady=(18, 8))
        self.thumb = ctk.CTkLabel(top, text="Select a video", width=150, height=266, fg_color=C["field"],
                                  corner_radius=8, text_color=C["faint"], font=font(12))
        self.thumb.pack(side="left")
        info = ctk.CTkFrame(top, fg_color="transparent")
        info.pack(side="left", fill="both", expand=True, padx=(18, 0))
        self.video_status = badge(info, "nothing selected", "plain")
        self.video_status.pack(anchor="w")
        self.video_topic = label(info, "", 18, family=SERIF, wrap=440)
        self.video_topic.pack(anchor="w", pady=(10, 6))
        self.video_info = label(info, "", 12, C["muted"], wrap=440)
        self.video_info.pack(anchor="w")
        ib = ctk.CTkFrame(info, fg_color="transparent")
        ib.pack(anchor="w", pady=(12, 0))
        button(ib, "Play video", self.play_video, "secondary").pack(side="left")
        button(ib, "Change music", self.change_music, "secondary").pack(side="left", padx=8)

        bar = ctk.CTkFrame(d, fg_color="transparent")
        bar.pack(fill="x", padx=20, pady=16, side="bottom")   # packed first so it always stays visible
        self.approve_btn = button(bar, "Approve", self.approve_video, "primary", width=130)
        self.approve_btn.pack(side="right")
        button(bar, "Save changes", self.save_video, "secondary").pack(side="right", padx=8)
        self.reject_btn = button(bar, "Reject", self.reject_video, "danger")
        self.reject_btn.pack(side="left")
        form = ctk.CTkScrollableFrame(d, fg_color="transparent", scrollbar_button_color=C["border"])
        form.pack(fill="both", expand=True, padx=12)
        trow = ctk.CTkFrame(form, fg_color="transparent")
        trow.pack(fill="x", pady=(6, 2))
        label(trow, "YouTube title", 12, C["muted"]).pack(side="left")
        self.title_count = label(trow, "", 11, C["faint"], family=MONO)
        self.title_count.pack(side="right")
        self.title_var = tk.StringVar()
        self.title_var.trace_add("write", lambda *a: self.update_title_count())
        entry(form, self.title_var, width=600).pack(fill="x")
        label(form, "Description", 12, C["muted"]).pack(anchor="w", pady=(10, 2))
        self.desc_text = textbox(form, 70)
        self.desc_text.pack(fill="x")
        label(form, "Tags, comma separated", 12, C["muted"]).pack(anchor="w", pady=(10, 2))
        self.tags_var = tk.StringVar()
        entry(form, self.tags_var, width=600).pack(fill="x")
        label(form, "Voiceover script", 12, C["muted"]).pack(anchor="w", pady=(10, 2))
        self.script_text = textbox(form, 60)
        self.script_text.pack(fill="both", expand=True)

        self.root.bind("<Control-s>", lambda e: self.page == "Review" and self.save_video())
        self.root.bind("<Control-Return>", lambda e: self.page == "Review" and self.approve_video())

    def switch_list(self, mode=None):
        approved = (mode or self.list_mode.get()) == "Approved"
        (self.review_frame if approved else self.approved_frame).pack_forget()
        (self.approved_frame if approved else self.review_frame).pack(fill="both", expand=True, padx=16,
                                                                    before=self.list_empty)
        if approved:
            self.back_btn.pack(side="left")
        else:
            self.back_btn.pack_forget()
        self.update_list_empty()

    def update_list_empty(self):
        approved = self.list_mode.get() == "Approved"
        n = len(eng.stems(eng.APPROVED if approved else eng.REVIEW))
        if n:
            self.list_empty.configure(text="Top of the list uploads first." if approved else "")
        else:
            self.list_empty.configure(text="Nothing approved yet. Approve videos from To review."
                                      if approved else f"Nothing to review. The next run renders new videos "
                                                       f"({self.task.get('next') or 'see Dashboard'}).")

    def update_title_count(self):
        n = len(self.title_var.get())
        self.title_count.configure(text=f"{n} / 100", text_color=TONES["bad"][1] if n > 100 else C["faint"])

    def refresh_review_lists(self):
        def row(folder, stem):
            meta = eng.load_meta(folder, stem)
            return meta.get("title") or stem, when(meta.get("rendered"))
        self.fill(self.review_tree, [(s, (row(eng.REVIEW, s)[1], row(eng.REVIEW, s)[0]))
                                     for s in eng.stems(eng.REVIEW)])
        self.fill(self.approved_tree, [(s, (i + 1, row(eng.APPROVED, s)[0]))
                                       for i, s in enumerate(eng.stems(eng.APPROVED))])
        self.seg.configure(values=[f"To review", f"Approved"])
        self.update_list_empty()
        if self.current and not eng.pair(*self.current)[0].exists():
            self.clear_detail()

    def clear_detail(self):
        self.current = None
        self.thumb_img = None
        self.thumb.configure(image=None, text="Select a video")
        set_badge(self.video_status, "nothing selected", "plain")
        self.video_topic.configure(text="")
        self.video_info.configure(text="")
        self.title_var.set("")
        set_text(self.desc_text, "")
        self.tags_var.set("")
        set_text(self.script_text, "", readonly=True)

    def select_video(self, folder, tree):
        sel = tree.selection()
        if not sel:
            return
        other = self.approved_tree if tree is self.review_tree else self.review_tree
        other.selection_remove(other.selection())
        stem = sel[0]
        self.current = (folder, stem)
        meta = eng.load_meta(folder, stem)
        self.title_var.set(meta.get("title", ""))
        set_text(self.desc_text, meta.get("description", ""))
        self.tags_var.set(", ".join(meta.get("tags", [])))
        set_text(self.script_text, meta.get("script", ""), readonly=True)
        video = eng.pair(folder, stem)[0]
        size = human(video.stat().st_size) if video.exists() else "missing"
        approved = folder == eng.APPROVED
        set_badge(self.video_status, "approved, queued" if approved else "waiting for review", "ok" if approved else "warn")
        self.video_topic.configure(text=meta.get("topic", stem))
        credits = f"\nCredit: {'; '.join(meta['credits'])}" if meta.get("credits") else ""
        self.video_info.configure(text=f"Music: {meta.get('music', '-')}\n"
                                       f"Footage: {len(meta.get('clips', []))} clips{credits}\n"
                                       f"Rendered {when(meta.get('rendered'))}  ·  {size}")
        self.approve_btn.configure(state="disabled" if approved else "normal")
        self.reject_btn.configure(state="disabled" if approved else "normal")
        self.show_thumb(video, stem)

    def show_thumb(self, video, stem):
        png = eng.THUMBS / f"{stem}.png"

        def done(ok):
            if ok is True and self.current and self.current[1] == stem and png.exists():
                from PIL import Image
                img = Image.open(png)
                w = 150
                self.thumb_img = ctk.CTkImage(light_image=img, dark_image=img, size=(w, int(w * img.height / img.width)))
                self.thumb.configure(image=self.thumb_img, text="")
        if png.exists():
            done(True)
        else:
            self.thumb.configure(image=None, text="Loading preview")
            self.thumb_img = None
            self.bg(lambda: make_thumb(video, png), done)

    def play_video(self):
        if self.current:
            video = eng.pair(*self.current)[0]
            if video.exists():
                open_path(video)

    def change_music(self):
        """Pick another approved track (or none) for the selected video; only the final mix is redone."""
        if not self.current:
            messagebox.showinfo("Select", "Select a video first.")
            return
        folder, stem = self.current
        if not (eng.WORK / stem / "combined.mp4").exists():
            messagebox.showinfo("Not possible", "This video was made before music swapping existed, "
                                                "or its working files were cleaned up.")
            return
        meta = eng.load_meta(folder, stem)
        top, frm = self.dialog("Change music")
        label(frm, "Change music", 20, family=SERIF).pack(anchor="w")
        label(frm, f"{self.title_var.get()}\nNow: {meta.get('music', 'none')}. Only the final mix is redone "
                   "(about a minute).", 12, C["muted"], wrap=520).pack(anchor="w", pady=(4, 12))
        choice = tk.StringVar(value=meta.get("music", "none"))
        lst = ctk.CTkScrollableFrame(frm, fg_color=C["card"], corner_radius=8, height=300, width=520)
        lst.pack(fill="both", expand=True)
        for name, _, tags in [("none", "", "voice only")] + eng.usable_tracks():
            row = ctk.CTkFrame(lst, fg_color="transparent")
            row.pack(fill="x", pady=2)
            ctk.CTkRadioButton(row, text="No music" if name == "none" else name, value=name, variable=choice,
                               font=font(13), text_color=C["text"], fg_color=C["primary"],
                               hover_color=C["primary_hover"], border_color=C["muted"]).pack(side="left")
            label(row, tags, 11, C["muted"]).pack(side="left", padx=8)
            if name != "none":
                button(row, "Listen", lambda n=name: open_path(eng.SAFE_MUSIC / n), "ghost", width=70).pack(side="right")

        def go():
            top.destroy()
            self.start_run(["--remix", stem, choice.get()], "Music change")
        bar = ctk.CTkFrame(frm, fg_color="transparent")
        bar.pack(fill="x", pady=(14, 0))
        button(bar, "Remix", go, "primary").pack(side="right")
        button(bar, "Cancel", top.destroy, "ghost").pack(side="right", padx=8)

    def save_video(self, quiet=False):
        if not self.current:
            return False
        folder, stem = self.current
        if not eng.pair(folder, stem)[0].exists():
            messagebox.showwarning("Gone", "That video was moved or uploaded meanwhile.")
            self.refresh_all(lists_only=True)
            return False
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("Title needed", "The YouTube title can't be empty.")
            return False
        if len(title) > 100:
            messagebox.showwarning("Title too long", "YouTube titles can be at most 100 characters.")
            return False
        eng.save_meta(folder, stem, title, self.desc_text.get("1.0", "end"), self.tags_var.get().split(","))
        if not quiet:
            self.set_status("Changes saved.")
        self.refresh_review_lists()
        return True

    def approve_video(self):
        if self.current and self.current[0] == eng.REVIEW and self.save_video(quiet=True):
            title = self.title_var.get()
            eng.approve(self.current[1])
            self.set_status(f"Approved: {title}")
            self.clear_detail()
            self.refresh_all(lists_only=True)
            self.select_next_review()

    def select_next_review(self):
        kids = self.review_tree.get_children()
        if kids:
            self.review_tree.selection_set(kids[0])

    def reject_video(self):
        if not self.current:
            return
        folder, stem = self.current
        if folder != eng.REVIEW:
            messagebox.showinfo("Approved video", "Move it back to review first, then reject it.")
            return
        reason = self.ask_reject_reason()
        if not reason:
            return
        try:
            eng.reject(stem, *reason)
        except (ValueError, OSError) as e:
            messagebox.showerror("Can't reject", str(e))
            return
        self.set_status("Rejected. Your reason will shape future videos (History > What it learned).")
        self.clear_detail()
        self.refresh_all(lists_only=True)
        self.select_next_review()

    def ask_reject_reason(self):
        """Modal dialog: why is it being rejected? Returns (category, details) or None."""
        top, frm = self.dialog("Why reject this video?")
        result = {}
        label(frm, "Why reject this video?", 20, family=SERIF).pack(anchor="w")
        label(frm, f"{self.title_var.get()}\nThe video is deleted, but your reason is kept and teaches the next "
                   "videos (topics, script and footage).", 12, C["muted"], wrap=520).pack(anchor="w", pady=(4, 12))
        choice = tk.StringVar()
        for key, text in eng.REJECT_REASONS.items():
            ctk.CTkRadioButton(frm, text=text, value=key, variable=choice, font=font(13), text_color=C["text"],
                               fg_color=C["primary"], hover_color=C["primary_hover"],
                               border_color=C["muted"]).pack(anchor="w", pady=3)
        label(frm, "Details (the more specific, the better it learns)", 12, C["muted"]).pack(anchor="w", pady=(12, 2))
        note = textbox(frm, 80)
        note.configure(width=520)
        note.pack(fill="x")
        note.focus_set()
        label(frm, "Voice, caption and music problems can't be learned automatically: change them in "
                   "Settings and Music.", 11, C["faint"], wrap=520).pack(anchor="w", pady=(6, 0))

        def confirm():
            text = note.get("1.0", "end").strip()
            if not choice.get():
                messagebox.showwarning("Reason needed", "Pick what was wrong first.", parent=top)
            elif choice.get() == "other" and not text:
                messagebox.showwarning("Details needed", "Describe what was wrong.", parent=top)
            else:
                result["value"] = (choice.get(), text)
                top.destroy()
        bar = ctk.CTkFrame(frm, fg_color="transparent")
        bar.pack(fill="x", pady=(14, 0))
        button(bar, "Reject and teach", confirm, "primary").pack(side="right")
        button(bar, "Cancel", top.destroy, "ghost").pack(side="right", padx=8)
        self.root.wait_window(top)
        return result.get("value")

    def back_to_review(self):
        sel = self.approved_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select an approved video first.")
            return
        if eng.is_running():
            messagebox.showinfo("Busy", "A run is in progress and may be uploading this video. Try again after it.")
            return
        eng.unapprove(sel[0])
        self.clear_detail()
        self.refresh_all(lists_only=True)

    # ---- History -------------------------------------------------------------------------
    def build_history(self):
        p = self.tabs["History"]
        self.header(p, "History", "Every upload counts against the monthly quota. Rejections teach future videos.",
                    actions=[("Open YouTube Studio", lambda: webbrowser.open("https://studio.youtube.com"), "secondary")])
        grid = ctk.CTkFrame(p, fg_color="transparent")
        grid.pack(fill="both", expand=True)
        grid.grid_columnconfigure(0, weight=1)
        grid.grid_rowconfigure(0, weight=3)
        grid.grid_rowconfigure(2, weight=2)

        box, inner, head = self.section(grid, "Uploads")
        box.grid(row=0, column=0, sticky="nsew")
        button(head, "Posted videos folder", lambda: open_path(eng.POSTED), "ghost").pack(side="right")
        fr, self.hist_tree = self.table(inner, ("Time", "Title", "Status", "Request ID"), (130, 460, 100, 260), 6)
        fr.pack(fill="both", expand=True)

        box, inner, _ = self.section(grid, "Needs checking", "upload result was unclear; never retried automatically")
        box.grid(row=1, column=0, sticky="nsew", pady=12)
        fr, self.check_tree = self.table(inner, ("Video",), (700,), 2)
        fr.pack(fill="x")
        bar = ctk.CTkFrame(inner, fg_color="transparent")
        bar.pack(fill="x", pady=(8, 0))
        button(bar, "It's live on YouTube", lambda: self.resolve(True), "secondary").pack(side="left")
        button(bar, "Not uploaded, back to approved", lambda: self.resolve(False), "ghost").pack(side="left", padx=8)

        box, inner, head = self.section(grid, "Rejected videos", "your reasons teach future videos")
        box.grid(row=2, column=0, sticky="nsew")
        button(head, "What it learned", self.show_lessons, "secondary").pack(side="right")
        fr, self.fb_tree = self.table(inner, ("Time", "Reason", "Details", "Video"), (130, 240, 360, 280), 4)
        fr.pack(fill="both", expand=True)

    def refresh_history(self):
        ledger = eng.load_ledger()
        self.fill(self.hist_tree, [(str(i), (when(e.get("time")), e.get("title", ""), e.get("status", ""),
                                             e.get("request_id") or ""))
                                   for i, e in reversed(list(enumerate(ledger)))])
        self.fill(self.check_tree, [(s, (eng.load_meta(eng.CHECK, s).get("title") or s,))
                                    for s in eng.stems(eng.CHECK)])
        self.fill(self.fb_tree, [(str(i), (when(r.get("time")), eng.REJECT_REASONS.get(r.get("category"), "?"),
                                           r.get("note") or "-", r.get("title") or r.get("topic") or "-"))
                                 for i, r in reversed(list(enumerate(eng.load_feedback())))])

    def show_lessons(self):
        top, frm = self.dialog("What the next videos are being taught", 680)
        label(frm, "What the next videos are being taught", 20, family=SERIF).pack(anchor="w", pady=(0, 10))
        box = textbox(frm, 380)
        box.configure(width=640)
        set_text(box, eng.lessons_summary(), readonly=True)
        box.pack(fill="both", expand=True)
        button(frm, "Close", top.destroy, "secondary").pack(anchor="e", pady=(12, 0))

    def resolve(self, uploaded):
        sel = self.check_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a video in Needs checking first.")
            return
        question = ("Mark it as live? It stays counted in this month's quota." if uploaded else
                    "Move it back to approved? It stops counting against the quota and will be uploaded again "
                    "at a later slot. Only do this if it's NOT in YouTube Studio.")
        if messagebox.askyesno("Confirm", question):
            eng.resolve_check(sel[0], uploaded)
            self.refresh_all(lists_only=True)

    # ---- Music ---------------------------------------------------------------------------
    def build_music(self):
        p = self.tabs["Music"]
        self.header(p, "Music", "Only these tracks are ever used, never MoneyPrinterTurbo's bundled songs (one caused a "
                                "copyright block). Mood tags help the AI match a track to each video. "
                                "Choose how music is picked in Settings.",
                    actions=[("Open folder", lambda: open_path(eng.SAFE_MUSIC), "ghost"),
                             ("Add track", self.add_track, "primary")])
        box, inner, head = self.section(p, "Approved tracks")
        box.pack(fill="both", expand=True)
        button(head, "Remove", self.remove_track, "danger").pack(side="right")
        button(head, "Listen", self.listen_track, "secondary").pack(side="right", padx=8)
        fr, self.music_tree = self.table(inner, ("File", "Mood tags", "Source / license", "File"),
                                         (260, 320, 420, 70), 12)
        fr.pack(fill="both", expand=True)
        foot = ctk.CTkFrame(p, fg_color="transparent")
        foot.pack(fill="x", pady=(12, 0))
        label(foot, "Find more:", 12, C["muted"]).pack(side="left")
        button(foot, "YouTube Audio Library", lambda: webbrowser.open("https://studio.youtube.com/channel/UC/music"),
               "ghost").pack(side="left", padx=4)
        button(foot, "Mixkit energetic", lambda: webbrowser.open("https://mixkit.co/free-stock-music/mood/energetic/"),
               "ghost").pack(side="left")

    def refresh_music(self):
        self.fill(self.music_tree, [(name, (name, tags or "-", src, "ok" if ok else "missing"))
                                    for name, src, tags, ok in eng.music_entries()])
        if hasattr(self, "track_box"):
            self.track_box.configure(values=[n for n, _, _ in eng.usable_tracks()] or ["-"])

    def listen_track(self):
        sel = self.music_tree.selection()
        if sel and (eng.SAFE_MUSIC / sel[0]).exists():
            open_path(eng.SAFE_MUSIC / sel[0])
        elif not sel:
            messagebox.showinfo("Select", "Select a track first.")

    def license_dialog(self, title, filename, fields, confirm_text, on_save):
        """Shared add-dialog: a few labelled inputs plus a license confirmation."""
        top, frm = self.dialog(title)
        label(frm, title, 20, family=SERIF).pack(anchor="w")
        label(frm, filename, 12, C["muted"], family=MONO).pack(anchor="w", pady=(2, 10))
        vars_ = {}
        for key, text, default, values in fields:
            label(frm, text, 12, C["muted"]).pack(anchor="w", pady=(8, 2))
            vars_[key] = tk.StringVar(value=default)
            (combo(frm, vars_[key], values, 520) if values else entry(frm, vars_[key], 520)).pack(fill="x")
        ok = tk.BooleanVar()
        ctk.CTkCheckBox(frm, text=confirm_text, variable=ok, font=font(12), text_color=C["text"],
                        fg_color=C["primary"], hover_color=C["primary_hover"], border_color=C["muted"],
                        checkmark_color=C["primary_text"]).pack(anchor="w", pady=14)

        def save():
            if not ok.get():
                messagebox.showwarning("Confirm", "Tick the confirmation first.", parent=top)
                return
            try:
                on_save({k: v.get() for k, v in vars_.items()})
            except (ValueError, OSError) as e:
                messagebox.showerror("Can't add", str(e), parent=top)
                return
            top.destroy()
            self.refresh_all(lists_only=True)
        bar = ctk.CTkFrame(frm, fg_color="transparent")
        bar.pack(fill="x")
        button(bar, "Add", save, "primary").pack(side="right")
        button(bar, "Cancel", top.destroy, "ghost").pack(side="right", padx=8)

    def add_track(self):
        path = filedialog.askopenfilename(
            title="Choose a cleared music track",
            filetypes=[("Audio", " ".join(f"*{e}" for e in sorted(eng.AUDIO_EXT))), ("All files", "*.*")])
        if path:
            self.license_dialog(
                "Add track", Path(path).name,
                [("src", "Where is it from?", "YouTube Audio Library, attribution not required", None),
                 ("tags", "Mood tags (e.g. energetic, upbeat, fun, fast, calm)", "", None)],
                "This track needs no attribution and is free to use in monetized YouTube videos.",
                lambda v: eng.add_track(path, v["src"], v["tags"]))

    def remove_track(self):
        sel = self.music_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a track first.")
        elif messagebox.askyesno("Remove", f"Remove {sel[0]} from approved music and delete the file?"):
            eng.remove_track(sel[0])
            self.refresh_music()

    # ---- Clips -----------------------------------------------------------------------------
    def build_clips(self):
        p = self.tabs["Clips"]
        self.header(p, "Clips", "Footage comes from Pixabay, plus Coverr when its key is set. Add clips you download "
                                "yourself from Mixkit, Vidsplay or Coverr here; the picker uses them when their tags "
                                "match a scene. Mixkit forbids bots, so the app never fetches from it. Vidsplay's "
                                "required credit is added to the description automatically.",
                    actions=[("Open folder", lambda: open_path(eng.CLIPS), "ghost"),
                             ("Add clip", self.add_clip, "primary")])
        box, inner, head = self.section(p, "Your clip library")
        box.pack(fill="both", expand=True)
        button(head, "Remove", self.remove_clip, "danger").pack(side="right")
        fr, self.clips_tree = self.table(inner, ("File", "Source", "Tags", "File"), (300, 120, 520, 70), 12)
        fr.pack(fill="both", expand=True)
        foot = ctk.CTkFrame(p, fg_color="transparent")
        foot.pack(fill="x", pady=(12, 0))
        label(foot, "Free clips:", 12, C["muted"]).pack(side="left")
        for text, url in (("Mixkit", "https://mixkit.co/free-stock-video/"), ("Vidsplay", "https://www.vidsplay.com/"),
                          ("Coverr", "https://coverr.co/stock-video-footage")):
            button(foot, text, lambda u=url: webbrowser.open(u), "ghost").pack(side="left", padx=2)

    def refresh_clips(self):
        self.fill(self.clips_tree, [(name, (name, src, tags, "ok" if ok else "missing"))
                                    for name, src, tags, ok in eng.clip_entries()])

    def add_clip(self):
        path = filedialog.askopenfilename(
            title="Choose a clip you downloaded",
            filetypes=[("Video", " ".join(f"*{e}" for e in sorted(eng.footage.VIDEO_EXT))), ("All files", "*.*")])
        if path:
            self.license_dialog(
                "Add clip", Path(path).name,
                [("src", "Source", "Mixkit", ["Mixkit", "Vidsplay", "Coverr", "Other"]),
                 ("tags", "Tags: what the clip shows (e.g. money, cash, counting, hands)", "", None)],
                "I downloaded this myself and its license allows monetized YouTube videos.",
                lambda v: eng.add_clip(path, v["src"], v["tags"]))

    def remove_clip(self):
        sel = self.clips_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a clip first.")
        elif messagebox.askyesno("Remove", f"Remove {sel[0]} from your clip library and delete the file?"):
            eng.remove_clip(sel[0])
            self.refresh_clips()

    # ---- Settings ------------------------------------------------------------------------
    def build_settings(self):
        p = self.tabs["Settings"]
        self.header(p, "Settings", "How videos sound and look, and when the automation runs.",
                    actions=[("Reset to defaults", self.reset_settings, "ghost"),
                             ("Save settings", self.save_settings_form, "primary")])
        self.sv = {k: tk.StringVar() for k in ("niche", "language", "voice", "monthly_uploads", "run_times", "buffer",
                                               "music_volume", "clean_after_days", "privacy", "voice_rate",
                                               "music_mode", "music_track")}
        scroll = ctk.CTkScrollableFrame(p, fg_color="transparent", scrollbar_button_color=C["border"])
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(0, weight=1)
        scroll.grid_columnconfigure(1, weight=1)

        def form(parent):
            f = ctk.CTkFrame(parent, fg_color="transparent")
            f.pack(fill="x")
            f.grid_columnconfigure(1, weight=1)
            return f

        def field(f, row, title, widget, hint=""):
            label(f, title, 13).grid(row=row * 2, column=0, sticky="w", pady=(10, 0), padx=(0, 16))
            widget.grid(row=row * 2, column=1, sticky="we", pady=(10, 0))
            if hint:
                label(f, hint, 11, C["faint"], wrap=420).grid(row=row * 2 + 1, column=1, sticky="w")

        box, inner, _ = self.section(scroll, "Content")
        box.grid(row=0, column=0, columnspan=2, sticky="nsew", pady=(0, 12))
        f = form(inner)
        field(f, 0, "Niche", entry(f, self.sv["niche"], 520), "What every video is about.")
        field(f, 1, "Language", entry(f, self.sv["language"], 120), "For example en-US.")
        self.voice_box = combo(f, self.sv["voice"], [], 360)
        field(f, 2, "Voice", self.voice_box, "Run the full check in Setup to fill this list. Avoid Multilingual voices.")
        field(f, 3, "Voice speed", entry(f, self.sv["voice_rate"], 120), "1.0 is normal. 1.12 is a bit fast and lively.")
        label(f, "Script rules", 13).grid(row=8, column=0, sticky="nw", pady=(10, 0))
        self.rules_text = textbox(f, 90)
        self.rules_text.grid(row=8, column=1, sticky="we", pady=(10, 0))

        box, inner, _ = self.section(scroll, "Music")
        box.grid(row=1, column=0, sticky="nsew", padx=(0, 6), pady=(0, 12))
        f = form(inner)
        field(f, 0, "Mode", option(f, self.sv["music_mode"], list(MUSIC_LABELS.values()), 300))
        self.track_box = option(f, self.sv["music_track"], [n for n, _, _ in eng.usable_tracks()], 300)
        field(f, 1, "Fixed track", self.track_box, "Only used with 'Always the same track'.")
        field(f, 2, "Volume", entry(f, self.sv["music_volume"], 120), "0 to 1. 0.2 sits about 5 dB under the voice.")

        box, inner, _ = self.section(scroll, "Uploads and schedule")
        box.grid(row=1, column=1, sticky="nsew", padx=(6, 0), pady=(0, 12))
        f = form(inner)
        field(f, 0, "Uploads a month", entry(f, self.sv["monthly_uploads"], 120), "Upload-Post free plan is 10.")
        field(f, 1, "Run times", entry(f, self.sv["run_times"], 200), "Comma separated, e.g. 09:00, 19:00.")
        field(f, 2, "Videos waiting", entry(f, self.sv["buffer"], 120), "Stop rendering at this many.")
        field(f, 3, "Clean cache after", entry(f, self.sv["clean_after_days"], 120), "Days. 0 means never.")
        field(f, 4, "YouTube privacy", option(f, self.sv["privacy"], ["public", "unlisted", "private"], 200))

        box, inner, _ = self.section(scroll, "Schedule")
        box.grid(row=2, column=0, columnspan=2, sticky="nsew")
        row = ctk.CTkFrame(inner, fg_color="transparent")
        row.pack(fill="x")
        self.sched_badge = badge(row, "-", "plain")
        self.sched_badge.pack(side="left")
        self.sched_label = label(row, "", 13, C["muted"])
        self.sched_label.pack(side="left", padx=12)
        button(row, "Resume", lambda: self.task_cmd("Enable"), "secondary").pack(side="right")
        button(row, "Pause", lambda: self.task_cmd("Disable"), "ghost").pack(side="right", padx=8)

    def load_settings_form(self):
        s = eng.load_settings()
        for k in ("niche", "language", "voice", "monthly_uploads", "buffer", "music_volume", "clean_after_days",
                  "voice_rate", "music_track"):
            self.sv[k].set(str(s[k]))
        self.sv["run_times"].set(", ".join(s["run_times"]))
        self.sv["music_mode"].set(MUSIC_LABELS[s["music_mode"]])
        set_text(self.rules_text, s["script_rules"])
        try:
            self.sv["privacy"].set(read_mpt_config().get("app", {}).get("upload_post_youtube_privacy_status", "public"))
        except Exception:
            self.sv["privacy"].set("public")

    def reset_settings(self):
        if messagebox.askyesno("Reset", "Reset all video and schedule settings to the defaults?"):
            eng.SETTINGS.unlink(missing_ok=True)
            self.load_settings_form()
            self.set_status("Settings reset to defaults.")

    def save_settings_form(self):
        old = eng.load_settings()
        new = {k: self.sv[k].get().strip() for k in ("niche", "language", "voice", "monthly_uploads", "buffer",
                                                     "music_volume", "clean_after_days", "voice_rate", "music_track")}
        new["music_mode"] = {v: k for k, v in MUSIC_LABELS.items()}.get(self.sv["music_mode"].get(), "auto")
        new["script_rules"] = self.rules_text.get("1.0", "end").strip()
        new["run_times"] = [t.strip() for t in self.sv["run_times"].get().split(",") if t.strip()]
        if new["music_track"] == "-":
            new["music_track"] = ""
        try:
            times = eng.parse_times(new["run_times"])
            new["run_times"] = [f"{h:02d}:{m:02d}" for h, m in times]
            if not new["niche"] or not new["voice"]:
                raise ValueError("Niche and voice can't be empty.")
            saved = eng.save_settings(new)
        except (ValueError, TypeError) as e:
            messagebox.showerror("Can't save", str(e))
            return
        msg = "Settings saved."
        privacy = self.sv["privacy"].get()
        try:
            if privacy != read_mpt_config().get("app", {}).get("upload_post_youtube_privacy_status"):
                if self.confirm_config_write():
                    write_mpt_config({"upload_post_youtube_privacy_status": privacy})
                    msg += f" YouTube privacy: {privacy}."
        except Exception as e:
            messagebox.showerror("MPT config", f"Couldn't save privacy: {e}")
        if saved["run_times"] != old["run_times"]:
            code, out = register_schedule(saved["run_times"])
            msg += " Schedule updated." if code == 0 else f" Schedule update failed: {out[-200:]}"
        self.set_status(msg)
        self.refresh_all()

    def confirm_config_write(self):
        if webui_running():
            return messagebox.askyesno("MPT WebUI is open", "MPT's WebUI is running and may overwrite this change. "
                                                            "Close it first if you can. Save anyway?")
        return True

    def task_cmd(self, verb):
        code, out = powershell(f"{verb}-ScheduledTask -TaskName '{TASK}' | Out-Null")
        self.set_status(f"Schedule {'resumed' if verb == 'Enable' else 'paused'}." if code == 0 else f"Failed: {out[-200:]}")
        self.bg(task_info, self.on_task_info)

    def refresh_setup_schedule(self):
        t = self.task
        state = t.get("state", "Not registered")
        set_badge(self.sched_badge, state, "ok" if state == "Ready" else "warn" if t else "bad")
        self.sched_label.configure(text=f"Next run {t.get('next') or '-'}   ·   times {', '.join(t.get('times') or []) or '-'}"
                                        f"   ·   last run {t.get('last') or '-'}")
        if hasattr(self, "rows"):
            ok = bool(t) and str(HERE).lower() in str(t.get("action", "")).lower()
            self.set_row("schedule", ok, f"{state}. Next run {t.get('next') or '-'}." if t else "Not registered.")

    # ---- Setup -------------------------------------------------------------------------------
    def build_setup(self):
        p = self.tabs["Setup"]
        self.doctor_label = self.header(p, "Setup", "Work down the list until every row says OK. "
                                                    "The full check tests the script writer, footage and Upload-Post "
                                                    "(about 20 seconds).",
                                        actions=[("Run full check", self.run_doctor, "primary")])
        scroll = ctk.CTkScrollableFrame(p, fg_color=C["card"], corner_radius=10, border_width=1,
                                        border_color=C["border"], scrollbar_button_color=C["border"])
        scroll.pack(fill="both", expand=True)
        scroll.grid_columnconfigure(1, weight=1)
        self.rows = {}
        self.row_n = 0

        def row(key, title):
            r = self.row_n
            if r:
                ctk.CTkFrame(scroll, height=1, fg_color=C["border"]).grid(row=r * 2 - 1, column=0, columnspan=2,
                                                                         sticky="we", padx=14)
            left = ctk.CTkFrame(scroll, fg_color="transparent", width=210)
            left.grid(row=r * 2, column=0, sticky="nw", padx=(18, 10), pady=14)
            label(left, title, 14, weight="bold").pack(anchor="w")
            b = badge(left, "checking", "plain")
            b.pack(anchor="w", pady=(6, 0))
            cell = ctk.CTkFrame(scroll, fg_color="transparent")
            cell.grid(row=r * 2, column=1, sticky="we", padx=(0, 18), pady=14)
            detail = label(cell, "", 12, C["muted"], wrap=540)
            detail.pack(anchor="w")
            self.rows[key] = (b, detail)
            self.row_n += 1
            return cell

        def line(cell):
            f = ctk.CTkFrame(cell, fg_color="transparent")
            f.pack(anchor="w", pady=(8, 0))
            return f

        cell = row("mpt", "MoneyPrinterTurbo")
        f = line(cell)
        self.mpt_var = tk.StringVar()
        entry(f, self.mpt_var, 360).pack(side="left")
        button(f, "Browse", self.browse_mpt, "ghost").pack(side="left", padx=6)
        button(f, "Save", self.save_mpt, "secondary").pack(side="left")

        cell = row("llm", "Script writer")
        f = line(cell)
        self.llm_var = tk.StringVar()
        option(f, self.llm_var, LLM_PROVIDERS, 160).pack(side="left")
        self.llm_key = tk.StringVar()
        label(f, "  API key", 12, C["muted"]).pack(side="left")
        entry(f, self.llm_key, 220, show="*").pack(side="left", padx=8)
        button(f, "Save", self.save_llm, "secondary").pack(side="left")

        cell = row("footage", "Stock footage")
        f = line(cell)
        self.pixabay_key = tk.StringVar()
        label(f, "Pixabay key ", 12, C["muted"], width=96).pack(side="left")
        entry(f, self.pixabay_key, 220, show="*").pack(side="left")
        button(f, "Save", self.save_pixabay, "secondary").pack(side="left", padx=8)
        button(f, "Get a key", lambda: webbrowser.open("https://pixabay.com/api/docs/"), "ghost").pack(side="left")
        f = line(cell)
        self.coverr_key = tk.StringVar()
        label(f, "Coverr key ", 12, C["muted"], width=96).pack(side="left")
        entry(f, self.coverr_key, 220, show="*").pack(side="left")
        button(f, "Save", self.save_coverr, "secondary").pack(side="left", padx=8)
        button(f, "Request a key", lambda: webbrowser.open("https://api.coverr.co/docs/"), "ghost").pack(side="left")

        cell = row("upload", "Upload-Post")
        f = line(cell)
        self.up_enabled = tk.BooleanVar()
        ctk.CTkSwitch(f, text="Enabled", variable=self.up_enabled, font=font(13), text_color=C["text"],
                      progress_color=C["primary"], button_color=C["text"], fg_color=C["field"]).pack(side="left")
        self.up_key = tk.StringVar()
        label(f, "  key", 12, C["muted"]).pack(side="left")
        entry(f, self.up_key, 160, show="*").pack(side="left", padx=6)
        self.up_profile = tk.StringVar()
        label(f, "profile", 12, C["muted"]).pack(side="left")
        entry(f, self.up_profile, 110).pack(side="left", padx=6)
        button(f, "Save", self.save_upload, "secondary").pack(side="left")
        f = line(cell)
        button(f, "Open Upload-Post users page", lambda: webbrowser.open("https://app.upload-post.com/manage-users"),
               "ghost").pack(side="left")

        cell = row("schedule", "Daily schedule")
        button(line(cell), "Register or repair", self.register, "secondary").pack(side="left")
        row("claude", "Claude CLI")
        row("webui", "MPT WebUI closed")
        cell = row("disk", "Disk space")
        f = line(cell)
        button(f, "Clean MPT cache now", self.clean_now, "secondary").pack(side="left")
        button(f, "Create desktop shortcut", self.make_shortcut, "ghost").pack(side="left", padx=8)

    def set_row(self, key, ok, detail):
        b, text = self.rows[key]
        set_badge(b, {True: "ok", False: "needs attention", None: "not tested"}[ok],
                  {True: "ok", False: "bad", None: "plain"}[ok])
        text.configure(text=detail)

    def refresh_setup(self):
        mpt = mpt_dir()
        self.mpt_var.set(str(mpt))
        py_ok = (mpt / ".venv" / "Scripts" / "python.exe").exists()
        self.set_row("mpt", py_ok, f"Installed in {mpt}." if py_ok else
                     f"No MPT Python in {mpt}. Run install.bat, or browse to your MPT folder.")
        try:
            app_cfg = read_mpt_config().get("app", {})
        except Exception as e:
            app_cfg = {}
            self.set_row("llm", False, f"Can't read MPT config.toml: {e}")
        provider = app_cfg.get("llm_provider", "")
        self.llm_var.set(provider or LLM_PROVIDERS[0])
        key_ok = provider in NO_KEY_PROVIDERS or bool(app_cfg.get(f"{provider}_api_key"))
        d = self.doctor.get("llm") or {}
        self.set_row("llm", d.get("ok") if d else (key_ok or None),
                     f"Provider {provider or '-'}"
                     + ("" if provider in NO_KEY_PROVIDERS else f", key {'saved' if key_ok else 'missing'}")
                     + (f". Test {'passed' if d.get('ok') else 'failed: ' + str(d.get('message') or d.get('error'))}"
                        f" in {d.get('seconds', '?')} s." if d else ". Not tested yet."))
        pix, cov = bool(app_cfg.get("pixabay_api_keys")), bool(app_cfg.get("coverr_api_keys"))
        d = self.doctor.get("footage") or {}
        self.set_row("footage", d.get("ok") if d else (pix or False),
                     f"Pixabay key {'saved' if pix else 'missing'}. Coverr key {'saved' if cov else 'not set (optional)'}. "
                     f"{len(eng.clip_entries())} clip(s) in your library."
                     + (f" Test search: {d.get('sample_results')}." if d else ""))
        self.up_enabled.set(bool(app_cfg.get("upload_post_enabled")))
        self.up_profile.set(app_cfg.get("upload_post_username", ""))
        up_ok = (bool(app_cfg.get("upload_post_enabled")) and bool(app_cfg.get("upload_post_api_key"))
                 and bool(app_cfg.get("upload_post_username")) and "youtube" in app_cfg.get("upload_post_platforms", [])
                 and not app_cfg.get("upload_post_auto_upload"))
        self.set_row("upload", up_ok,
                     f"Key {'saved' if app_cfg.get('upload_post_api_key') else 'missing'}, profile "
                     f"'{app_cfg.get('upload_post_username', '')}', auto-upload "
                     f"{'ON (unsafe)' if app_cfg.get('upload_post_auto_upload') else 'off'}, privacy "
                     f"{app_cfg.get('upload_post_youtube_privacy_status', '-')}. The profile is the user name on "
                     "Upload-Post's Users page, not your email.")
        claude = shutil.which("claude")
        self.set_row("claude", bool(claude) if provider == "claude_code" else True,
                     (claude + ". Also used to look at clips.") if claude else
                     ("Not found. Install Claude Code, or pick another provider." if provider == "claude_code"
                      else "Not needed for this provider, but clips won't be checked visually."))
        running = webui_running()
        self.set_row("webui", not running, "It's open on port 8501. Close it: it rewrites config.toml."
                     if running else "Closed, so it can't overwrite settings.")
        self.bg(lambda: (eng.folder_size(mpt / "storage" / "tasks"), eng.folder_size(mpt / "storage" / "cache_videos"),
                         eng.folder_size(eng.POSTED)), self.on_disk)
        self.refresh_setup_schedule()

    def on_disk(self, sizes):
        if isinstance(sizes, Exception):
            return
        tasks, cache, posted = sizes
        days = eng.load_settings()["clean_after_days"]
        self.set_row("disk", tasks + cache < 20e9, f"MPT task files {human(tasks)}, clip cache {human(cache)}, posted "
                                                   f"videos {human(posted)}. Cache older than {days} days is deleted "
                                                   "after each run.")

    def run_doctor(self):
        self.doctor_label.configure(text="Checking everything, about 20 seconds...")

        def work():
            code, out = run_hidden(["cmd", "/c", str(RUN_BAT), "--doctor"], timeout=240)
            for ln in out.splitlines():
                if ln.startswith("DOCTOR_JSON:"):
                    return json.loads(ln[len("DOCTOR_JSON:"):])
            raise RuntimeError(out[-400:] or f"exit {code}")
        self.bg(work, self.on_doctor)

    def on_doctor(self, report):
        if isinstance(report, Exception):
            self.doctor_label.configure(text=f"Check failed: {report}")
            return
        self.doctor = report
        voices = (report.get("voices") or {}).get("en_US") or []
        if voices:
            self.voice_box.configure(values=voices)
        bad = [k for k in ("mpt", "llm", "footage", "upload_post") if not (report.get(k) or {}).get("ok")]
        self.doctor_label.configure(text=f"Checked at {report.get('time', '')[11:16]}: "
                                         + ("everything works." if not bad else "problems with " + ", ".join(bad) + "."))
        self.refresh_setup()

    def browse_mpt(self):
        path = filedialog.askdirectory(title="MoneyPrinterTurbo folder", initialdir=self.mpt_var.get())
        if path:
            self.mpt_var.set(str(Path(path)))

    def save_mpt(self):
        path = Path(self.mpt_var.get().strip())
        if not (path / "app" / "services" / "material.py").exists():
            messagebox.showerror("Not MPT", f"{path} doesn't look like a MoneyPrinterTurbo folder.")
            return
        set_mpt_dir(path)
        self.refresh_all()

    def save_llm(self):
        provider = self.llm_var.get().strip()
        if not provider or not self.confirm_config_write():
            return
        changes = {"llm_provider": provider}
        if self.llm_key.get().strip():
            changes[f"{provider}_api_key"] = self.llm_key.get().strip()
        write_mpt_config(changes)
        self.llm_key.set("")
        self.doctor.pop("llm", None)
        self.set_status("Script writer saved. Run the full check to test it.")
        self.refresh_setup()

    def save_pixabay(self):
        key = self.pixabay_key.get().strip()
        if not key or not self.confirm_config_write():
            return
        write_mpt_config({"pixabay_api_keys": [key], "video_source": "pixabay"})
        self.pixabay_key.set("")
        self.doctor.pop("footage", None)
        self.set_status("Pixabay key saved.")
        self.refresh_setup()

    def save_coverr(self):
        key = self.coverr_key.get().strip()
        if not key or not self.confirm_config_write():
            return
        write_mpt_config({"coverr_api_keys": [key]})
        self.coverr_key.set("")
        self.doctor.pop("footage", None)
        self.set_status("Coverr key saved. Its videos are searched along with Pixabay's.")
        self.refresh_setup()

    def save_upload(self):
        if not self.up_profile.get().strip():
            messagebox.showwarning("Profile", "Enter the Upload-Post profile (user) name.")
            return
        if not self.confirm_config_write():
            return
        changes = {"upload_post_enabled": self.up_enabled.get(), "upload_post_username": self.up_profile.get().strip(),
                   "upload_post_platforms": ["youtube"], "upload_post_auto_upload": False,   # approval gate
                   "upload_post_youtube_made_for_kids": False}
        if self.up_key.get().strip():
            changes["upload_post_api_key"] = self.up_key.get().strip()
        write_mpt_config(changes)
        self.up_key.set("")
        self.set_status("Upload-Post saved: YouTube only, auto-upload off.")
        self.refresh_all()

    def register(self):
        code, out = register_schedule(eng.load_settings()["run_times"])
        self.set_status("Schedule registered." if code == 0 else f"Failed: {out[-200:]}")
        self.bg(task_info, self.on_task_info)

    def clean_now(self):
        if eng.is_running():
            messagebox.showinfo("Busy", "A run is in progress. Clean after it finishes.")
            return
        days = eng.load_settings()["clean_after_days"] or 14
        if messagebox.askyesno("Clean", f"Delete MPT render files and downloaded clips older than {days} days?\n"
                                        "Your review, approved and posted videos are not touched."):
            freed = eng.clean_mpt_cache(mpt_dir(), days)
            self.set_status(f"Freed {human(freed)}.")
            self.refresh_setup()

    def make_shortcut(self):
        pyw = mpt_dir() / ".venv" / "Scripts" / "pythonw.exe"
        script = ("$d=[Environment]::GetFolderPath('Desktop');"
                  "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\\Shorts Autopilot.lnk\");"
                  f"$s.TargetPath='{pyw}';$s.Arguments='\"{HERE / 'autopilot_gui.pyw'}\"';"
                  f"$s.WorkingDirectory='{HERE}';$s.Save()")
        code, out = powershell(script)
        self.set_status("Desktop shortcut created." if code == 0 else f"Failed: {out[-200:]}")

    # ---- Logs ------------------------------------------------------------------------------
    def build_logs(self):
        p = self.tabs["Logs"]
        self.header(p, "Logs", "Everything each run did. Newest at the bottom.",
                    actions=[("Open folder", lambda: open_path(eng.LOG_DIR), "ghost"),
                             ("Refresh", self.refresh_logs, "secondary")])
        self.errors_only = tk.BooleanVar()
        ctk.CTkSwitch(p, text="Problems only", variable=self.errors_only, command=self.refresh_logs, font=font(13),
                      text_color=C["text"], progress_color=C["primary"], button_color=C["text"],
                      fg_color=C["field"]).pack(anchor="w", pady=(0, 10))
        self.log_text = ctk.CTkTextbox(p, corner_radius=10, fg_color=C["card"], border_width=1, border_color=C["border"],
                                       text_color="#C9C7C1", font=ctk.CTkFont(family=MONO, size=12), wrap="none")
        self.log_text.pack(fill="both", expand=True)

    def refresh_logs(self):
        lines = tail(eng.LOG_DIR / "daily.log", 500)
        if self.errors_only.get():
            lines = [l for l in lines if re.search(r"ERROR|FAIL|WARNING|Traceback|Error|UNCONFIRMED|=====", l)]
        at_end = self.log_text.yview()[1] > 0.98
        set_text(self.log_text, "\n".join(lines) or "No log yet.", readonly=True)
        if at_end or self.proc:
            self.log_text.see("end")


def main():
    ctk.set_appearance_mode("dark")
    root = ctk.CTk()
    app = App(root)
    if "--screenshot" in sys.argv:
        i = sys.argv.index("--screenshot")
        out = Path(sys.argv[i + 1])
        page = sys.argv[i + 2] if len(sys.argv) > i + 2 else "Dashboard"

        def shoot():
            import traceback
            from PIL import ImageGrab
            try:
                for name in PAGES:                 # build and show every page once (smoke test)
                    app.show(name)
                    root.update()
                app.show(page)
                if page == "Review" and app.review_tree.get_children():
                    app.review_tree.selection_set(app.review_tree.get_children()[0])
                    root.update()
                    root.after(2500)               # let the thumbnail render
                root.lift()
                root.attributes("-topmost", True)
                root.update()
                root.after(400)
                root.update()
                x, y = root.winfo_rootx(), root.winfo_rooty()
                ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(out)
                print(f"saved {out}")
            except Exception:
                traceback.print_exc()
            finally:
                root.destroy()
        root.after(6000, shoot)                    # give the schedule query time to load
    root.mainloop()


if __name__ == "__main__":
    main()
