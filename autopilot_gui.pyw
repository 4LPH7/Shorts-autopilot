"""Shorts Autopilot - native Windows app for setup, review/approval and monitoring.

Start it with "Shorts Autopilot.bat" (runs MPT's pythonw, so no console window).
All automation rules live in daily_shorts.py; this file is only the interface.
    pythonw autopilot_gui.pyw                     # open the app
    python  autopilot_gui.pyw --screenshot out.png [Tab]  # build every tab, save a screenshot, exit
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


# ---- Helpers (no Tk) ----------------------------------------------------------

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
                "-vf", "scale=200:-1", str(out)], timeout=60)
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


# ---- App -----------------------------------------------------------------------

class App:
    def __init__(self, root):
        self.root = root
        self.q = queue.Queue()
        self.proc = None
        self.proc_label = ""
        self.task = {}
        self.doctor = {}
        self.current = None          # (folder, stem) shown in the Review detail panel
        self.thumb_img = None
        root.title("Shorts Autopilot")
        # DPI-aware: fonts scale with Windows display scaling, so scale pixel sizes too.
        self.f = f = max(1.0, float(root.tk.call("tk", "scaling")) / 1.3333)
        w = min(int(1280 * f), root.winfo_screenwidth() - 40)
        h = min(int(820 * f), root.winfo_screenheight() - int(110 * f))
        root.geometry(f"{w}x{h}+20+10")
        root.minsize(int(980 * f), int(640 * f))
        style = ttk.Style()
        if "vista" in style.theme_names():
            style.theme_use("vista")
        style.configure("Big.TLabel", font=("Segoe UI Semibold", 14))
        style.configure("Head.TLabel", font=("Segoe UI Semibold", 11))
        style.configure("Treeview", rowheight=int(22 * f))

        top = ttk.Frame(root, padding=(12, 8))
        top.pack(fill="x")
        ttk.Label(top, text="Shorts Autopilot", font=("Segoe UI Semibold", 15)).pack(side="left")
        self.status = ttk.Label(top, text="", foreground="#555")
        self.status.pack(side="left", padx=16)
        ttk.Button(top, text="Refresh", command=self.refresh_all).pack(side="right")

        self.nb = ttk.Notebook(root)
        self.nb.pack(fill="both", expand=True, padx=10, pady=(0, 10))
        self.tabs = {}
        for name in ("Dashboard", "Review", "History", "Music", "Clips", "Settings", "Setup", "Logs"):
            f = ttk.Frame(self.nb, padding=10)
            self.nb.add(f, text=name)
            self.tabs[name] = f
        self.build_dashboard()
        self.build_review()
        self.build_history()
        self.build_music()
        self.build_clips()
        self.build_settings()
        self.build_setup()
        self.build_logs()

        self.root.after(100, self.poll_queue)
        self.refresh_all()
        self.root.after(30000, self.auto_refresh)

    # -- background work: never block the window --------------------------------
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
            self.set_status(f"{self.proc_label} finished (exit {code}).")
            self.refresh_all()
        self.root.after(200, self.poll_queue)

    def auto_refresh(self):
        self.refresh_all(lists_only=True)
        self.root.after(30000, self.auto_refresh)

    def set_status(self, text):
        self.status.config(text=text)

    def busy(self):
        return bool(self.proc) or eng.is_running()

    def start_run(self, args, label):
        if self.busy():
            messagebox.showinfo("Busy", "A run is already in progress. Wait for it to finish.")
            return
        self.proc = subprocess.Popen(["cmd", "/c", str(RUN_BAT), *args], cwd=str(HERE),
                                     creationflags=NO_WINDOW)
        self.proc_label = label
        self.set_status(f"{label} running... (progress in the Logs tab)")

    def refresh_all(self, lists_only=False):
        self.refresh_dashboard()
        self.refresh_review_lists()
        self.refresh_history()
        self.refresh_music()
        self.refresh_clips()
        self.refresh_logs()
        if not lists_only:
            self.load_settings_form()
            self.refresh_setup()
        self.bg(task_info, self.on_task_info)

    def on_task_info(self, info):
        self.task = info if isinstance(info, dict) else {}
        self.refresh_dashboard()
        self.refresh_setup_schedule()

    # -- shared widgets ------------------------------------------------------------
    def tree(self, parent, columns, widths, height=8):
        frame = ttk.Frame(parent)
        t = ttk.Treeview(frame, columns=columns, show="headings", height=height)
        for c, w in zip(columns, widths):
            t.heading(c, text=c)
            t.column(c, width=int(w * self.f), anchor="w", stretch=w > 150)
        sb = ttk.Scrollbar(frame, orient="vertical", command=t.yview)
        t.configure(yscrollcommand=sb.set)
        t.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        return frame, t

    @staticmethod
    def fill(tree, rows):
        sel = tree.selection()
        tree.delete(*tree.get_children())
        for iid, values in rows:
            tree.insert("", "end", iid=iid, values=values)
        keep = [s for s in sel if tree.exists(s)]
        if keep:
            tree.selection_set(keep)

    # ---- Dashboard --------------------------------------------------------------
    def build_dashboard(self):
        f = self.tabs["Dashboard"]
        cards = ttk.Frame(f)
        cards.pack(fill="x")
        self.card = {}
        for i, (key, title) in enumerate([("quota", "Uploads this month"), ("next", "Next upload"),
                                          ("queue", "Queue"), ("sched", "Schedule"), ("last", "Last run")]):
            box = ttk.LabelFrame(cards, text=title, padding=10)
            box.grid(row=0, column=i, sticky="nsew", padx=4)
            cards.columnconfigure(i, weight=1)
            big = ttk.Label(box, text="-", style="Big.TLabel")
            big.pack(anchor="w")
            small = ttk.Label(box, text="", foreground="#555", wraplength=int(200 * self.f), justify="left")
            small.pack(anchor="w")
            self.card[key] = (big, small)
        self.quota_bar = ttk.Progressbar(self.card["quota"][0].master, length=180, maximum=10)
        self.quota_bar.pack(anchor="w", pady=(6, 0))

        self.alerts = ttk.LabelFrame(f, text="Alerts", padding=8)
        self.alerts.pack(fill="x", pady=8)

        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=(8, 0))   # packed before the tables so it stays visible
        ttk.Button(bar, text="Run now", command=self.run_now).pack(side="left")
        ttk.Button(bar, text="Render one video now",
                   command=lambda: self.start_run(["--render"], "Render")).pack(side="left", padx=6)
        ttk.Button(bar, text="Dry run (preview)", command=self.dry_run).pack(side="left")
        ttk.Button(bar, text="Open project folder", command=lambda: open_path(HERE)).pack(side="right")
        mid = ttk.Frame(f)
        mid.pack(fill="both", expand=True)
        left = ttk.LabelFrame(mid, text="Monthly uploads calendar", padding=6)
        left.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.cal_summary = ttk.Label(left, text="", foreground="#333", wraplength=int(560 * self.f), justify="left")
        self.cal_summary.pack(anchor="w", pady=(0, 6))
        fr, self.cal_tree = self.tree(left, ("When", "Video"), (150, 380), height=10)
        fr.pack(fill="both", expand=True)
        right = ttk.LabelFrame(mid, text="Recent runs", padding=6)
        right.pack(side="left", fill="both", expand=True, padx=(4, 0))
        fr, self.runs_tree = self.tree(right, ("Time", "Mode", "Upload", "Rendered", "Errors"),
                                       (120, 60, 160, 160, 200), height=10)
        fr.pack(fill="both", expand=True)


    def run_now(self):
        if messagebox.askyesno("Run now", "This does exactly what a scheduled run does:\n\n"
                               "- uploads the next approved video IF an upload slot is due\n"
                               "- renders a new video if fewer than the buffer are waiting\n\nContinue?"):
            self.start_run([], "Run")

    def dry_run(self):
        self.start_run(["--dry-run"], "Dry run")
        self.nb.select(self.tabs["Logs"])

    def refresh_dashboard(self):
        s = eng.load_settings()
        now = datetime.now()
        ledger = eng.load_ledger()
        limit = int(s["monthly_uploads"])
        used = eng.used_this_month(ledger, now)
        big, small = self.card["quota"]
        big.config(text=f"{used} / {limit}")
        small.config(text=f"{max(limit - used, 0)} free uploads left this month")
        self.quota_bar.config(maximum=max(limit, 1), value=min(used, limit))

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
        big, small = self.card["next"]
        if plan:
            big.config(text=plan[0].strftime("%a %d %b %H:%M"))
            small.config(text="video ready" if approved else "needs an approved video")
        else:
            big.config(text="-")
            small.config(text="no slots planned")

        rows = []
        for i, t in enumerate(plan):
            if i < len(approved):
                video = "ready: " + (eng.load_meta(eng.APPROVED, approved[i]).get("title") or approved[i])
            else:
                video = "needs an approved video"
            rows.append((t.isoformat(), (t.strftime("%a %d %b %H:%M"), video)))
        self.fill(self.cal_tree, rows)
        self.cal_summary.config(text=self.calendar_summary(now, ledger, limit, times, plan))

        big, small = self.card["queue"]
        big.config(text=f"{len(review)} to review")
        small.config(text=f"{len(approved)} approved, waiting to upload")

        big, small = self.card["sched"]
        state = self.task.get("state") or "not registered"
        big.config(text=state)
        small.config(text=f"next run: {self.task.get('next') or '-'}\n"
                          f"times: {', '.join(self.task.get('times') or []) or '-'}")

        runs = eng.recent_runs(30)
        big, small = self.card["last"]
        if runs:
            r = runs[-1]
            big.config(text="OK" if not r.get("errors") else "Problem")
            small.config(text=f"{r.get('time', '')[:16].replace('T', ' ')} ({r.get('mode')})\n"
                              + ("; ".join(r.get("errors") or []) or "no errors")[:120])
        else:
            big.config(text="-")
            small.config(text="no runs logged yet")
        self.fill(self.runs_tree, [
            (str(i), (r.get("time", "")[:16].replace("T", " "), r.get("mode", ""),
                      f"{r.get('upload') or '-'} {r.get('title') or ''}".strip(),
                      r.get("rendered") or "-", "; ".join(r.get("errors") or []) or "-"))
            for i, r in reversed(list(enumerate(runs)))])

        self.show_alerts(plan, approved)
        if self.busy() and not self.proc:
            self.set_status("A run is in progress (started by the schedule).")
        elif not self.proc:
            self.set_status("Idle")

    def calendar_summary(self, now, ledger, limit, times, plan):
        """Two plain lines describing how the month is spread, from the same plan the calendar shows."""
        if not times:
            return "Run times are not set correctly (Settings tab)."
        used = eng.used_this_month(ledger, now)
        _, month_end = eng.month_bounds(now)
        rest = [t for t in plan if t.month == now.month]
        lines = [f"This month: {used} of {limit} used, {max(limit - used, 0)} left."]
        if not rest:
            lines.append("No uploads left this month.")
            return "\n".join(lines)
        days = sorted({t.date() for t in rest})
        # A "full spread" is a month that starts fresh (uploads from the 1st week, most of the quota left).
        if rest[0].day <= 7 and len(rest) >= limit - 1 and len(days) > 1:
            gap = (days[-1] - days[0]).days / (len(days) - 1)
            lines.append(f"Full spread: about one upload every {gap:.0f} days, "
                         f"{rest[0]:%d %b} to {rest[-1]:%d %b}.")
        else:
            lines.append(f"Catching up: {len(rest)} left, "
                         f"{rest[0]:%d %b %H:%M} to {rest[-1]:%d %b %H:%M}, "
                         f"{len(times)} run times a day.")
        return "\n".join(lines)

    def show_alerts(self, plan, approved):
        for w in self.alerts.winfo_children():
            w.destroy()
        alerts = []
        if plan and not approved and plan[0] - datetime.now() < timedelta(hours=24):
            alerts.append(("red", f"An upload is due {plan[0]:%a %H:%M} but nothing is approved. "
                                  "Approve a video in the Review tab."))
        if eng.stems(eng.CHECK):
            alerts.append(("red", f"{len(eng.stems(eng.CHECK))} upload(s) need checking in YouTube Studio "
                                  "(History tab)."))
        mpt = mpt_dir()
        if not (mpt / ".venv" / "Scripts" / "python.exe").exists():
            alerts.append(("red", f"MoneyPrinterTurbo not found in {mpt}. See the Setup tab."))
        try:
            if read_mpt_config().get("app", {}).get("upload_post_auto_upload"):
                alerts.append(("red", "MPT auto-upload is ON: videos could skip your approval. "
                                      "Save the Upload-Post section in Setup to turn it off."))
        except Exception as e:
            alerts.append(("orange", f"Can't read MPT config: {e}"))
        if webui_running():
            alerts.append(("orange", "MPT's WebUI is open. Close it: it rewrites config.toml and can undo changes."))
        if not self.task:
            alerts.append(("orange", "The schedule isn't registered yet, or is still loading (Setup tab)."))
        elif self.task.get("state") == "Disabled":
            alerts.append(("orange", "The schedule is paused (Settings tab to resume)."))
        sources = eng.MUSIC_SOURCES.read_text(encoding="utf-8") if eng.MUSIC_SOURCES.exists() else ""
        if not eng.approved_tracks(sources, [p.name for p in eng.SAFE_MUSIC.glob("*")]):
            alerts.append(("#555", "No approved music: videos are voice-only (Music tab to add tracks)."))
        if len(alerts) == 1 and alerts[0][0] == "#555" or not alerts:
            alerts.insert(0, ("green", "All good."))
        for color, text in alerts:
            tk.Label(self.alerts, text="● " + text, fg=color, anchor="w", justify="left",
                     font=("Segoe UI", 10)).pack(fill="x")

    # ---- Review -----------------------------------------------------------------
    def build_review(self):
        f = self.tabs["Review"]
        left = ttk.Frame(f)
        left.pack(side="left", fill="both", expand=False)
        ttk.Label(left, text="Waiting for your review", style="Head.TLabel").pack(anchor="w")
        fr, self.review_tree = self.tree(left, ("Rendered", "Title"), (110, 330), height=9)
        fr.pack(fill="both", expand=True)
        self.review_tree.bind("<<TreeviewSelect>>", lambda e: self.select_video(eng.REVIEW, self.review_tree))
        ttk.Label(left, text="Approved queue (top uploads first)", style="Head.TLabel").pack(anchor="w", pady=(10, 0))
        fr, self.approved_tree = self.tree(left, ("#", "Title"), (40, 400), height=7)
        fr.pack(fill="both", expand=True)
        self.approved_tree.bind("<<TreeviewSelect>>",
                                lambda e: self.select_video(eng.APPROVED, self.approved_tree))
        bar = ttk.Frame(left)
        bar.pack(fill="x", pady=4)
        ttk.Button(bar, text="Back to review", command=self.back_to_review).pack(side="left")
        ttk.Button(bar, text="Open folder", command=lambda: open_path(eng.APPROVED)).pack(side="right")

        d = ttk.LabelFrame(f, text="Video", padding=10)
        d.pack(side="left", fill="both", expand=True, padx=(10, 0))
        row = ttk.Frame(d)
        row.pack(fill="x")
        self.thumb = ttk.Label(row, text="(select a video)", width=28, anchor="center")
        self.thumb.pack(side="left")
        info = ttk.Frame(row)
        info.pack(side="left", fill="x", expand=True, padx=10)
        self.video_info = ttk.Label(info, text="", foreground="#555", justify="left")
        self.video_info.pack(anchor="w")
        btns = ttk.Frame(info)
        btns.pack(anchor="w", pady=6)
        ttk.Button(btns, text="▶ Play video", command=self.play_video).pack(side="left")
        ttk.Button(btns, text="♪ Change music...", command=self.change_music).pack(side="left", padx=6)

        ttk.Label(d, text="YouTube title").pack(anchor="w", pady=(8, 0))
        self.title_var = tk.StringVar()
        ttk.Entry(d, textvariable=self.title_var).pack(fill="x")
        ttk.Label(d, text="Description").pack(anchor="w", pady=(6, 0))
        self.desc_text = tk.Text(d, height=4, wrap="word", font=("Segoe UI", 10))
        self.desc_text.pack(fill="x")
        ttk.Label(d, text="Tags (comma separated)").pack(anchor="w", pady=(6, 0))
        self.tags_var = tk.StringVar()
        ttk.Entry(d, textvariable=self.tags_var).pack(fill="x")
        ttk.Label(d, text="Script (voiceover)").pack(anchor="w", pady=(6, 0))
        self.script_text = tk.Text(d, height=7, wrap="word", font=("Segoe UI", 10), background="#f4f4f4")
        self.script_text.pack(fill="both", expand=True)
        bar = ttk.Frame(d)
        bar.pack(fill="x", pady=(8, 0))
        ttk.Button(bar, text="Save changes", command=self.save_video).pack(side="left")
        self.approve_btn = ttk.Button(bar, text="✔ Approve", command=self.approve_video)
        self.approve_btn.pack(side="left", padx=6)
        ttk.Button(bar, text="✖ Reject (delete)", command=self.reject_video).pack(side="left")

    def refresh_review_lists(self):
        def row(folder, stem):
            meta = eng.load_meta(folder, stem)
            return meta.get("title") or stem, (meta.get("rendered") or "")[:16].replace("T", " ")
        self.fill(self.review_tree, [(s, (row(eng.REVIEW, s)[1], row(eng.REVIEW, s)[0]))
                                     for s in eng.stems(eng.REVIEW)])
        self.fill(self.approved_tree, [(s, (i + 1, row(eng.APPROVED, s)[0]))
                                       for i, s in enumerate(eng.stems(eng.APPROVED))])

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
        self.desc_text.delete("1.0", "end")
        self.desc_text.insert("1.0", meta.get("description", ""))
        self.tags_var.set(", ".join(meta.get("tags", [])))
        self.script_text.config(state="normal")
        self.script_text.delete("1.0", "end")
        self.script_text.insert("1.0", meta.get("script", ""))
        self.script_text.config(state="disabled")
        video = eng.pair(folder, stem)[0]
        size = human(video.stat().st_size) if video.exists() else "missing"
        self.video_info.config(text=f"Topic: {meta.get('topic', '-')}\nMusic: {meta.get('music', '-')}\n"
                                    f"Rendered: {meta.get('rendered', '-')}\nFile: {video.name} ({size})\n"
                                    f"Footage: {len(meta.get('clips', []))} clips"
                                    f"{', credit: ' + '; '.join(meta['credits']) if meta.get('credits') else ''}\n"
                                    f"Status: {'approved' if folder == eng.APPROVED else 'waiting for review'}")
        self.approve_btn.config(state="normal" if folder == eng.REVIEW else "disabled")
        self.show_thumb(video, stem)

    def show_thumb(self, video, stem):
        png = eng.THUMBS / f"{stem}.png"

        def done(ok):
            if ok is True and self.current and self.current[1] == stem:
                self.thumb_img = tk.PhotoImage(file=str(png))
                self.thumb.config(image=self.thumb_img, text="")
        if png.exists():
            done(True)
        else:
            self.thumb.config(image="", text="loading preview...")
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
        tracks = eng.usable_tracks()
        meta = eng.load_meta(folder, stem)
        dlg = tk.Toplevel(self.root)
        dlg.title("Change music")
        dlg.transient(self.root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=f"Music for: {self.title_var.get()}", style="Head.TLabel",
                  wraplength=int(520 * self.f)).pack(anchor="w")
        ttk.Label(frm, text=f"Now: {meta.get('music', 'none')}. Use ▶ to listen to a track first.",
                  foreground="#555").pack(anchor="w", pady=(0, 8))
        choice = tk.StringVar(value=meta.get("music", "none"))
        for name, _, tags in [("none", "", "voice only")] + tracks:
            row = ttk.Frame(frm)
            row.pack(fill="x", pady=1)
            ttk.Radiobutton(row, text=f"{name}   ({tags})" if name != "none" else "No music (voice only)",
                            value=name, variable=choice).pack(side="left")
            if name != "none":
                ttk.Button(row, text="▶", width=3, command=lambda n=name: open_path(eng.SAFE_MUSIC / n)
                           ).pack(side="right")

        def go():
            dlg.destroy()
            self.start_run(["--remix", stem, choice.get()], "Music change")
        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Remix (about a minute)", command=go).pack(side="right")
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)

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
        eng.save_meta(folder, stem, title, self.desc_text.get("1.0", "end"),
                      self.tags_var.get().split(","))
        if not quiet:
            self.set_status("Saved.")
        self.refresh_review_lists()
        return True

    def approve_video(self):
        if self.current and self.current[0] == eng.REVIEW and self.save_video(quiet=True):
            eng.approve(self.current[1])
            self.set_status(f"Approved: {self.title_var.get()}")
            self.current = None
            self.refresh_all(lists_only=True)

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
        self.set_status("Rejected. Your reason will shape future videos (see History > What it learned).")
        self.current = None
        self.thumb.config(image="", text="(select a video)")
        self.refresh_all(lists_only=True)

    def ask_reject_reason(self):
        """Modal dialog: why is it being rejected? Returns (category, details) or None."""
        dlg = tk.Toplevel(self.root)
        dlg.title("Why reject this video?")
        dlg.transient(self.root)
        dlg.grab_set()
        result = {}
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        wrap = int(560 * self.f)
        ttk.Label(frm, text=self.title_var.get(), style="Head.TLabel", wraplength=wrap).pack(anchor="w")
        ttk.Label(frm, text="The video is deleted, but your reason is kept and teaches the next videos "
                            "(topics, script and footage).", foreground="#555", wraplength=wrap
                  ).pack(anchor="w", pady=(2, 8))
        choice = tk.StringVar()
        for key, label in eng.REJECT_REASONS.items():
            ttk.Radiobutton(frm, text=label, value=key, variable=choice).pack(anchor="w", pady=1)
        ttk.Label(frm, text="Details (the more specific, the better it learns)").pack(anchor="w", pady=(10, 0))
        note = tk.Text(frm, height=4, width=62, wrap="word", font=("Segoe UI", 10))
        note.pack(fill="x")
        note.focus_set()
        ttk.Label(frm, text="Voice, caption and music problems can't be learned automatically: "
                            "change them in Settings and Music.", foreground="#777", wraplength=wrap
                  ).pack(anchor="w", pady=(6, 0))

        def confirm():
            text = note.get("1.0", "end").strip()
            if not choice.get():
                messagebox.showwarning("Reason needed", "Pick what was wrong first.", parent=dlg)
            elif choice.get() == "other" and not text:
                messagebox.showwarning("Details needed", "Describe what was wrong.", parent=dlg)
            else:
                result["value"] = (choice.get(), text)
                dlg.destroy()
        bar = ttk.Frame(frm)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="Reject and teach", command=confirm).pack(side="right")
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)
        self.root.wait_window(dlg)
        return result.get("value")

    def back_to_review(self):
        sel = self.approved_tree.selection()
        if not sel:
            return
        if eng.is_running():
            messagebox.showinfo("Busy", "A run is in progress and may be uploading this video. Try again after it.")
            return
        eng.unapprove(sel[0])
        self.current = None
        self.refresh_all(lists_only=True)

    # ---- History ------------------------------------------------------------------
    def build_history(self):
        f = self.tabs["History"]
        ttk.Label(f, text="Uploads (they count against the monthly quota)", style="Head.TLabel").pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=(6, 0))     # packed first so it stays visible
        ttk.Button(bar, text="Open YouTube Studio",
                   command=lambda: webbrowser.open("https://studio.youtube.com")).pack(side="left")
        ttk.Button(bar, text="Open posted videos folder",
                   command=lambda: open_path(eng.POSTED)).pack(side="left", padx=6)
        fb = ttk.LabelFrame(f, text="Rejected videos (your reasons teach future videos)", padding=8)
        fb.pack(side="bottom", fill="x", pady=(6, 0))
        fr, self.fb_tree = self.tree(fb, ("Time", "Reason", "Details", "Video"), (130, 250, 380, 300), 4)
        fr.pack(fill="x")
        ttk.Button(fb, text="What it learned...", command=self.show_lessons).pack(anchor="w", pady=(6, 0))
        fr, self.hist_tree = self.tree(f, ("Time", "Title", "Status", "Request ID"), (140, 520, 100, 280), 8)
        fr.pack(fill="both", expand=True)
        box = ttk.LabelFrame(f, text="Needs checking (upload outcome was unclear; never retried automatically)",
                             padding=8)
        box.pack(fill="x", pady=8)
        fr, self.check_tree = self.tree(box, ("Video",), (700,), 3)
        fr.pack(fill="x")
        bar = ttk.Frame(box)
        bar.pack(fill="x", pady=(6, 0))
        ttk.Button(bar, text="It's live on YouTube", command=lambda: self.resolve(True)).pack(side="left")
        ttk.Button(bar, text="Not uploaded (back to approved)",
                   command=lambda: self.resolve(False)).pack(side="left", padx=6)

    def show_lessons(self):
        dlg = tk.Toplevel(self.root)
        dlg.title("What the next videos are being taught")
        dlg.transient(self.root)
        text = tk.Text(dlg, width=84, height=22, wrap="word", font=("Segoe UI", 10), padx=10, pady=10)
        text.insert("1.0", eng.lessons_summary())
        text.config(state="disabled")
        text.pack(fill="both", expand=True)
        ttk.Button(dlg, text="Close", command=dlg.destroy).pack(pady=8)

    def refresh_history(self):
        self.fill(self.fb_tree, [
            (str(i), (r.get("time", "").replace("T", " "), eng.REJECT_REASONS.get(r.get("category"), "?"),
                      r.get("note") or "-", r.get("title") or r.get("topic") or "-"))
            for i, r in reversed(list(enumerate(eng.load_feedback())))])
        ledger = eng.load_ledger()
        self.fill(self.hist_tree, [
            (str(i), (e.get("time", "").replace("T", " "), e.get("title", ""), e.get("status", ""),
                      e.get("request_id") or ""))
            for i, e in reversed(list(enumerate(ledger)))])
        self.fill(self.check_tree, [(s, (eng.load_meta(eng.CHECK, s).get("title") or s,))
                                    for s in eng.stems(eng.CHECK)])

    def resolve(self, uploaded):
        sel = self.check_tree.selection()
        if not sel:
            messagebox.showinfo("Select", "Select a video in the 'Needs checking' list first.")
            return
        question = ("Mark it as live? It stays counted in this month's quota." if uploaded else
                    "Move it back to approved? It stops counting against the quota and will be "
                    "uploaded again at a later slot. Only do this if it's NOT in YouTube Studio.")
        if messagebox.askyesno("Confirm", question):
            eng.resolve_check(sel[0], uploaded)
            self.refresh_all(lists_only=True)

    # ---- Music ---------------------------------------------------------------------
    def build_music(self):
        f = self.tabs["Music"]
        ttk.Label(f, text="Only tracks listed here are ever used (never MPT's bundled songs, which caused a Content ID "
                          "block). The mood tags tell the AI which video each track fits. Choose how music is "
                          "picked, or fix one track, in Settings. You can also swap the music of a single video "
                          "in Review.", wraplength=int(1100 * self.f), foreground="#555").pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bar, text="Add track...", command=self.add_track).pack(side="left")
        ttk.Button(bar, text="Remove selected", command=self.remove_track).pack(side="left", padx=6)
        ttk.Button(bar, text="▶ Listen", command=self.listen_track).pack(side="left")
        ttk.Button(bar, text="Free music: YouTube Audio Library",
                   command=lambda: webbrowser.open("https://studio.youtube.com/channel/UC/music")
                   ).pack(side="left", padx=6)
        ttk.Button(bar, text="Free music: Mixkit",
                   command=lambda: webbrowser.open("https://mixkit.co/free-stock-music/mood/energetic/")).pack(side="left")
        ttk.Button(bar, text="Open music folder", command=lambda: open_path(eng.SAFE_MUSIC)).pack(side="right")
        fr, self.music_tree = self.tree(f, ("File", "Mood tags", "Source / license", "File present"),
                                        (250, 330, 430, 90), 14)
        fr.pack(fill="both", expand=True, pady=6)

    def refresh_music(self):
        self.fill(self.music_tree, [(name, (name, tags or "-", src, "yes" if ok else "MISSING"))
                                    for name, src, tags, ok in eng.music_entries()])
        if hasattr(self, "track_box"):
            self.track_box.config(values=[n for n, _, _ in eng.usable_tracks()])

    def listen_track(self):
        sel = self.music_tree.selection()
        if sel and (eng.SAFE_MUSIC / sel[0]).exists():
            open_path(eng.SAFE_MUSIC / sel[0])

    def add_track(self):
        path = filedialog.askopenfilename(
            title="Choose a cleared music track",
            filetypes=[("Audio", " ".join(f"*{e}" for e in sorted(eng.AUDIO_EXT))), ("All files", "*.*")])
        if not path:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Add track")
        dlg.transient(self.root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=Path(path).name, style="Head.TLabel").pack(anchor="w")
        ttk.Label(frm, text="Where is it from? (e.g. YouTube Audio Library, attribution not required)").pack(
            anchor="w", pady=(8, 0))
        src = tk.StringVar(value="YouTube Audio Library, attribution not required")
        ttk.Entry(frm, textvariable=src, width=70).pack(fill="x")
        ttk.Label(frm, text="Mood tags (e.g. energetic, upbeat, fun, fast, calm, cinematic)").pack(anchor="w", pady=(8, 0))
        tags = tk.StringVar()
        ttk.Entry(frm, textvariable=tags, width=70).pack(fill="x")
        ok = tk.BooleanVar()
        ttk.Checkbutton(frm, variable=ok, text="I confirm this track needs no attribution and is free "
                                               "to use in monetized YouTube videos.").pack(anchor="w", pady=10)

        def save():
            if not ok.get():
                messagebox.showwarning("Confirm", "Tick the confirmation first.", parent=dlg)
                return
            try:
                eng.add_track(path, src.get(), tags.get())
            except (ValueError, OSError) as e:
                messagebox.showerror("Can't add", str(e), parent=dlg)
                return
            dlg.destroy()
            self.refresh_music()
            self.refresh_dashboard()
        bar = ttk.Frame(frm)
        bar.pack(fill="x")
        ttk.Button(bar, text="Add", command=save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)

    def remove_track(self):
        sel = self.music_tree.selection()
        if sel and messagebox.askyesno("Remove", f"Remove {sel[0]} from approved music and delete the file?"):
            eng.remove_track(sel[0])
            self.refresh_music()

    # ---- Clips (your own library) ---------------------------------------------------------
    def build_clips(self):
        f = self.tabs["Clips"]
        ttk.Label(f, text="Footage comes from Pixabay (and Coverr if you add its key in Setup). You can add your own "
                          "clips here: download them by hand from Mixkit, Vidsplay or Coverr, then add them with a few "
                          "tags. The picker considers them whenever their tags match what a scene is about. Mixkit's "
                          "terms ban bots, so the app never downloads from Mixkit itself. Vidsplay requires a visible "
                          "credit: it's added to the video description automatically.",
                  wraplength=int(1100 * self.f), foreground="#555").pack(anchor="w")
        bar = ttk.Frame(f)
        bar.pack(side="bottom", fill="x", pady=(6, 0))
        ttk.Button(bar, text="Add clip...", command=self.add_clip).pack(side="left")
        ttk.Button(bar, text="Remove selected", command=self.remove_clip).pack(side="left", padx=6)
        for label, url in (("Mixkit", "https://mixkit.co/free-stock-video/"), ("Vidsplay", "https://www.vidsplay.com/"),
                           ("Coverr", "https://coverr.co/stock-video-footage")):
            ttk.Button(bar, text=f"Free clips: {label}", command=lambda u=url: webbrowser.open(u)).pack(side="left", padx=2)
        ttk.Button(bar, text="Open clips folder", command=lambda: open_path(eng.CLIPS)).pack(side="right")
        fr, self.clips_tree = self.tree(f, ("File", "Source", "Tags", "File present"), (300, 130, 530, 90), 14)
        fr.pack(fill="both", expand=True, pady=6)

    def refresh_clips(self):
        self.fill(self.clips_tree, [(name, (name, src, tags, "yes" if ok else "MISSING"))
                                    for name, src, tags, ok in eng.clip_entries()])

    def add_clip(self):
        path = filedialog.askopenfilename(
            title="Choose a clip you downloaded",
            filetypes=[("Video", " ".join(f"*{e}" for e in sorted(eng.footage.VIDEO_EXT))), ("All files", "*.*")])
        if not path:
            return
        dlg = tk.Toplevel(self.root)
        dlg.title("Add clip")
        dlg.transient(self.root)
        dlg.grab_set()
        frm = ttk.Frame(dlg, padding=14)
        frm.pack(fill="both", expand=True)
        ttk.Label(frm, text=Path(path).name, style="Head.TLabel").pack(anchor="w")
        ttk.Label(frm, text="Source").pack(anchor="w", pady=(8, 0))
        src = tk.StringVar(value="Mixkit")
        ttk.Combobox(frm, textvariable=src, values=["Mixkit", "Vidsplay", "Coverr", "Other"], width=20).pack(anchor="w")
        ttk.Label(frm, text="Tags: what the clip shows (e.g. money, cash, counting, hands)").pack(anchor="w", pady=(8, 0))
        tags = tk.StringVar()
        ttk.Entry(frm, textvariable=tags, width=70).pack(fill="x")
        ok = tk.BooleanVar()
        ttk.Checkbutton(frm, variable=ok, text="I downloaded this myself and its license allows use in monetized "
                                               "YouTube videos.").pack(anchor="w", pady=10)

        def save():
            if not ok.get():
                messagebox.showwarning("Confirm", "Tick the confirmation first.", parent=dlg)
                return
            try:
                eng.add_clip(path, src.get(), tags.get())
            except (ValueError, OSError) as e:
                messagebox.showerror("Can't add", str(e), parent=dlg)
                return
            dlg.destroy()
            self.refresh_clips()
        bar = ttk.Frame(frm)
        bar.pack(fill="x")
        ttk.Button(bar, text="Add", command=save).pack(side="right")
        ttk.Button(bar, text="Cancel", command=dlg.destroy).pack(side="right", padx=6)

    def remove_clip(self):
        sel = self.clips_tree.selection()
        if sel and messagebox.askyesno("Remove", f"Remove {sel[0]} from your clip library and delete the file?"):
            eng.remove_clip(sel[0])
            self.refresh_clips()

    # ---- Settings ------------------------------------------------------------------
    def build_settings(self):
        f = self.tabs["Settings"]
        form = ttk.LabelFrame(f, text="Video and schedule settings (settings.json)", padding=12)
        form.pack(fill="x")
        form.columnconfigure(1, weight=1)
        self.sv = {k: tk.StringVar() for k in ("niche", "language", "voice", "monthly_uploads", "run_times",
                                               "buffer", "music_volume", "clean_after_days", "privacy", "voice_rate",
                                               "music_mode", "music_track")}
        r = 0

        def field(label, widget, hint=""):
            nonlocal r
            ttk.Label(form, text=label).grid(row=r, column=0, sticky="nw", pady=4, padx=(0, 10))
            widget.grid(row=r, column=1, sticky="we", pady=4)
            if hint:
                ttk.Label(form, text=hint, foreground="#777").grid(row=r, column=2, sticky="w", padx=8)
            r += 1

        field("Niche", ttk.Entry(form, textvariable=self.sv["niche"]), "what every video is about")
        field("Language", ttk.Entry(form, textvariable=self.sv["language"], width=12), "e.g. en-US")
        self.voice_box = ttk.Combobox(form, textvariable=self.sv["voice"])
        field("Voice", self.voice_box, "list fills after 'Run full check' in Setup")
        field("Voice speed", ttk.Spinbox(form, from_=0.7, to=1.5, increment=0.02, textvariable=self.sv["voice_rate"],
                                         width=8), "1.0 = normal, 1.12 = a bit fast and energetic")
        self.rules_text = tk.Text(form, height=4, wrap="word", font=("Segoe UI", 10))
        field("Script rules", self.rules_text, "instructions for the script writer")
        field("Uploads per month", ttk.Spinbox(form, from_=1, to=1000, textvariable=self.sv["monthly_uploads"],
                                               width=8), "Upload-Post free plan = 10")
        field("Run times", ttk.Entry(form, textvariable=self.sv["run_times"], width=20),
              "comma separated, e.g. 09:00, 19:00 (re-registers the schedule)")
        field("Videos kept waiting", ttk.Spinbox(form, from_=0, to=20, textvariable=self.sv["buffer"], width=8),
              "renders stop when this many are in review + approved")
        field("Music", ttk.Combobox(form, textvariable=self.sv["music_mode"], state="readonly", width=34,
                                    values=list(MUSIC_LABELS.values())), "how the background track is chosen")
        self.track_box = ttk.Combobox(form, textvariable=self.sv["music_track"], state="readonly", width=40,
                                      values=[n for n, _, _ in eng.usable_tracks()])
        field("Track to always use", self.track_box, "only used with 'Always the same track'")
        field("Music volume", ttk.Spinbox(form, from_=0, to=1, increment=0.01,
                                          textvariable=self.sv["music_volume"], width=8), "0-1, voice stays louder")
        field("Clean MPT cache after", ttk.Spinbox(form, from_=0, to=365, textvariable=self.sv["clean_after_days"],
                                                   width=8), "days (0 = never)")
        field("YouTube privacy", ttk.Combobox(form, textvariable=self.sv["privacy"], state="readonly", width=12,
                                              values=["public", "unlisted", "private"]), "saved to MPT's config")
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=8)
        ttk.Button(bar, text="Save settings", command=self.save_settings_form).pack(side="left")
        ttk.Button(bar, text="Reset to defaults", command=self.reset_settings).pack(side="left", padx=6)

        sched = ttk.LabelFrame(f, text="Schedule", padding=10)
        sched.pack(fill="x")
        self.sched_label = ttk.Label(sched, text="")
        self.sched_label.pack(side="left")
        ttk.Button(sched, text="Resume", command=lambda: self.task_cmd("Enable")).pack(side="right")
        ttk.Button(sched, text="Pause", command=lambda: self.task_cmd("Disable")).pack(side="right", padx=6)

    def load_settings_form(self):
        s = eng.load_settings()
        for k in ("niche", "language", "voice", "monthly_uploads", "buffer", "music_volume", "clean_after_days"):
            self.sv[k].set(str(s[k]))
        self.sv["run_times"].set(", ".join(s["run_times"]))
        self.sv["voice_rate"].set(str(s["voice_rate"]))
        self.sv["music_mode"].set(MUSIC_LABELS[s["music_mode"]])
        self.sv["music_track"].set(s["music_track"])
        self.rules_text.delete("1.0", "end")
        self.rules_text.insert("1.0", s["script_rules"])
        try:
            self.sv["privacy"].set(read_mpt_config().get("app", {}).get("upload_post_youtube_privacy_status",
                                                                        "public"))
        except Exception:
            self.sv["privacy"].set("public")

    def reset_settings(self):
        if messagebox.askyesno("Reset", "Reset all video and schedule settings to the defaults?"):
            eng.SETTINGS.unlink(missing_ok=True)
            self.load_settings_form()

    def save_settings_form(self):
        old = eng.load_settings()
        new = {k: self.sv[k].get().strip() for k in ("niche", "language", "voice", "monthly_uploads",
                                                     "buffer", "music_volume", "clean_after_days")}
        new["voice_rate"] = self.sv["voice_rate"].get().strip()
        new["music_mode"] = {v: k for k, v in MUSIC_LABELS.items()}.get(self.sv["music_mode"].get(), "auto")
        new["music_track"] = self.sv["music_track"].get().strip()
        new["script_rules"] = self.rules_text.get("1.0", "end").strip()
        new["run_times"] = [t.strip() for t in self.sv["run_times"].get().split(",") if t.strip()]
        try:
            times = eng.parse_times(new["run_times"])
            new["run_times"] = [f"{h:02d}:{m:02d}" for h, m in times]
            if not new["niche"] or not new["voice"]:
                raise ValueError("niche and voice can't be empty")
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
            msg += " Schedule re-registered." if code == 0 else f" Schedule update FAILED: {out[-200:]}"
        self.set_status(msg)
        self.refresh_all()

    def confirm_config_write(self):
        if webui_running():
            return messagebox.askyesno(
                "MPT WebUI is open", "MPT's WebUI is running and may overwrite this change. "
                                     "Close it first if you can. Save anyway?")
        return True

    def task_cmd(self, verb):
        code, out = powershell(f"{verb}-ScheduledTask -TaskName '{TASK}' | Out-Null")
        self.set_status(f"Schedule {'resumed' if verb == 'Enable' else 'paused'}." if code == 0
                        else f"Failed: {out[-200:]}")
        self.bg(task_info, self.on_task_info)

    def refresh_setup_schedule(self):
        t = self.task
        text = (f"State: {t.get('state', 'not registered')}   Next run: {t.get('next') or '-'}   "
                f"Times: {', '.join(t.get('times') or []) or '-'}   Last run: {t.get('last') or '-'}")
        self.sched_label.config(text=text)
        if hasattr(self, "setup_rows"):
            ok = bool(t) and str(HERE).lower() in str(t.get("action", "")).lower()
            self.set_row("schedule", ok, text if t else "Not registered")

    # ---- Setup ---------------------------------------------------------------------
    def build_setup(self):
        outer = self.tabs["Setup"]
        top = ttk.Frame(outer)
        top.pack(fill="x")
        ttk.Button(top, text="Run full check", command=self.run_doctor).pack(side="left")
        self.doctor_label = ttk.Label(top, text="Tests the LLM, footage key and Upload-Post (about 20 s).",
                                      foreground="#555")
        self.doctor_label.pack(side="left", padx=10)

        f = ttk.Frame(outer)
        f.pack(fill="both", expand=True, pady=8)
        f.columnconfigure(2, weight=1)
        self.setup_rows = {}
        self.setup_r = 0

        def row(key, title):
            icon = tk.Label(f, text="?", fg="#999", font=("Segoe UI Semibold", 13), width=2)
            icon.grid(row=self.setup_r, column=0, sticky="nw", pady=6)
            ttk.Label(f, text=title, style="Head.TLabel").grid(row=self.setup_r, column=1, sticky="nw",
                                                              pady=6, padx=(0, 12))
            cell = ttk.Frame(f)
            cell.grid(row=self.setup_r, column=2, sticky="we", pady=6)
            detail = ttk.Label(cell, text="", foreground="#555", wraplength=int(760 * self.f), justify="left")
            detail.pack(anchor="w")
            self.setup_rows[key] = (icon, detail)
            self.setup_r += 1
            return cell

        cell = row("mpt", "MoneyPrinterTurbo")
        line = ttk.Frame(cell)
        line.pack(anchor="w", pady=2)
        self.mpt_var = tk.StringVar()
        ttk.Entry(line, textvariable=self.mpt_var, width=50).pack(side="left")
        ttk.Button(line, text="Browse...", command=self.browse_mpt).pack(side="left", padx=4)
        ttk.Button(line, text="Save", command=self.save_mpt).pack(side="left")

        cell = row("llm", "Script writer (LLM)")
        line = ttk.Frame(cell)
        line.pack(anchor="w", pady=2)
        self.llm_var = tk.StringVar()
        ttk.Combobox(line, textvariable=self.llm_var, values=LLM_PROVIDERS, width=14).pack(side="left")
        self.llm_key = tk.StringVar()
        ttk.Label(line, text=" API key:").pack(side="left")
        ttk.Entry(line, textvariable=self.llm_key, show="•", width=40).pack(side="left", padx=4)
        ttk.Button(line, text="Save", command=self.save_llm).pack(side="left")

        cell = row("footage", "Stock footage")
        line = ttk.Frame(cell)
        line.pack(anchor="w", pady=2)
        self.pixabay_key = tk.StringVar()
        ttk.Label(line, text="Pixabay key:").pack(side="left")
        ttk.Entry(line, textvariable=self.pixabay_key, show="•", width=34).pack(side="left", padx=4)
        ttk.Button(line, text="Save", command=self.save_pixabay).pack(side="left")
        ttk.Button(line, text="Get a key", command=lambda: webbrowser.open("https://pixabay.com/api/docs/")
                   ).pack(side="left", padx=4)
        line = ttk.Frame(cell)
        line.pack(anchor="w", pady=2)
        self.coverr_key = tk.StringVar()
        ttk.Label(line, text="Coverr key (optional):").pack(side="left")
        ttk.Entry(line, textvariable=self.coverr_key, show="•", width=34).pack(side="left", padx=4)
        ttk.Button(line, text="Save", command=self.save_coverr).pack(side="left")
        ttk.Button(line, text="Request a key", command=lambda: webbrowser.open("https://api.coverr.co/docs/")
                   ).pack(side="left", padx=4)

        cell = row("upload", "Upload-Post")
        line = ttk.Frame(cell)
        line.pack(anchor="w", pady=2)
        self.up_enabled = tk.BooleanVar()
        ttk.Checkbutton(line, text="Enabled", variable=self.up_enabled).pack(side="left")
        ttk.Label(line, text="  API key:").pack(side="left")
        self.up_key = tk.StringVar()
        ttk.Entry(line, textvariable=self.up_key, show="•", width=30).pack(side="left", padx=4)
        ttk.Label(line, text="Profile:").pack(side="left")
        self.up_profile = tk.StringVar()
        ttk.Entry(line, textvariable=self.up_profile, width=16).pack(side="left", padx=4)
        ttk.Button(line, text="Save", command=self.save_upload).pack(side="left")
        ttk.Button(line, text="Open Upload-Post",
                   command=lambda: webbrowser.open("https://app.upload-post.com/manage-users")
                   ).pack(side="left", padx=4)

        cell = row("schedule", "Daily schedule")
        ttk.Button(cell, text="Register / repair schedule", command=self.register).pack(anchor="w", pady=2)

        row("claude", "Claude CLI")
        row("webui", "MPT WebUI closed")

        cell = row("disk", "Disk space")
        line = ttk.Frame(cell)
        line.pack(anchor="w", pady=2)
        ttk.Button(line, text="Clean MPT cache now", command=self.clean_now).pack(side="left")
        ttk.Button(line, text="Create desktop shortcut", command=self.make_shortcut).pack(side="left", padx=6)

    def set_row(self, key, ok, detail):
        icon, label = self.setup_rows[key]
        icon.config(text={True: "✔", False: "✖", None: "?"}[ok],
                    fg={True: "green", False: "red", None: "#999"}[ok])
        label.config(text=detail)

    def refresh_setup(self):
        mpt = mpt_dir()
        self.mpt_var.set(str(mpt))
        py_ok = (mpt / ".venv" / "Scripts" / "python.exe").exists()
        self.set_row("mpt", py_ok, f"Installed in {mpt}" if py_ok else
                     f"No MPT Python in {mpt}. Run install.bat, or browse to your MPT folder.")
        try:
            app_cfg = read_mpt_config().get("app", {})
        except Exception as e:
            app_cfg = {}
            self.set_row("llm", False, f"Can't read MPT config.toml: {e}")
        provider = app_cfg.get("llm_provider", "")
        self.llm_var.set(provider)
        key_ok = provider in NO_KEY_PROVIDERS or bool(app_cfg.get(f"{provider}_api_key"))
        d = self.doctor.get("llm") or {}
        self.set_row("llm", d.get("ok") if d else (key_ok or None),
                     f"Provider: {provider or '-'}"
                     + ("" if provider in NO_KEY_PROVIDERS else f", key {'saved' if key_ok else 'missing'}")
                     + (f". Test: {'OK' if d.get('ok') else 'FAILED ' + str(d.get('message') or d.get('error'))}"
                        f" ({d.get('seconds', '?')} s)" if d else ". Not tested yet."))
        pix = bool(app_cfg.get("pixabay_api_keys"))
        d = self.doctor.get("footage") or {}
        cov = bool(app_cfg.get("coverr_api_keys"))
        self.set_row("footage", d.get("ok") if d else (pix or False),
                     f"Pixabay key {'saved' if pix else 'MISSING'}, Coverr key {'saved' if cov else 'not set (optional)'}, "
                     f"{len(eng.clip_entries())} clip(s) in your library"
                     + (f". Test search: {d.get('sample_results')}" if d else ". Not tested yet."))
        self.up_enabled.set(bool(app_cfg.get("upload_post_enabled")))
        self.up_profile.set(app_cfg.get("upload_post_username", ""))
        up_ok = (bool(app_cfg.get("upload_post_enabled")) and bool(app_cfg.get("upload_post_api_key"))
                 and bool(app_cfg.get("upload_post_username")) and "youtube" in app_cfg.get("upload_post_platforms", [])
                 and not app_cfg.get("upload_post_auto_upload"))
        self.set_row("upload", up_ok,
                     f"Key {'saved' if app_cfg.get('upload_post_api_key') else 'missing'}, profile "
                     f"'{app_cfg.get('upload_post_username', '')}', platforms {app_cfg.get('upload_post_platforms')}, "
                     f"auto-upload {'ON (unsafe)' if app_cfg.get('upload_post_auto_upload') else 'off'}, "
                     f"privacy {app_cfg.get('upload_post_youtube_privacy_status', '-')}. "
                     "Profile = the user name on Upload-Post's Users page, not your email.")
        claude = shutil.which("claude")
        self.set_row("claude", bool(claude) if provider == "claude_code" else True,
                     claude or ("Not found. Install Claude Code, or pick another LLM provider."
                                if provider == "claude_code" else "Not needed for this provider."))
        running = webui_running()
        self.set_row("webui", not running, "It's open on port 8501: close it, it rewrites config.toml."
                     if running else "Closed (good: it can't overwrite settings).")
        self.bg(lambda: (eng.folder_size(mpt / "storage" / "tasks"), eng.folder_size(mpt / "storage" / "cache_videos"),
                         eng.folder_size(eng.POSTED)), self.on_disk)
        self.refresh_setup_schedule()

    def on_disk(self, sizes):
        if isinstance(sizes, Exception):
            return
        tasks, cache, posted = sizes
        days = eng.load_settings()["clean_after_days"]
        self.set_row("disk", tasks + cache < 20e9,
                     f"MPT task files {human(tasks)}, clip cache {human(cache)}, posted videos {human(posted)}. "
                     f"Cache older than {days} days is deleted after each run.")

    def run_doctor(self):
        self.doctor_label.config(text="Checking... (about 20 s)")

        def work():
            code, out = run_hidden(["cmd", "/c", str(RUN_BAT), "--doctor"], timeout=240)
            for line in out.splitlines():
                if line.startswith("DOCTOR_JSON:"):
                    return json.loads(line[len("DOCTOR_JSON:"):])
            raise RuntimeError(out[-400:] or f"exit {code}")
        self.bg(work, self.on_doctor)

    def on_doctor(self, report):
        if isinstance(report, Exception):
            self.doctor_label.config(text=f"Check failed: {report}")
            return
        self.doctor = report
        voices = (report.get("voices") or {}).get("en_US") or []
        if voices:
            self.voice_box.config(values=voices)
        bad = [k for k in ("mpt", "llm", "footage", "upload_post") if not (report.get(k) or {}).get("ok")]
        self.doctor_label.config(text=f"Checked {report.get('time', '')[11:16]}: "
                                      + ("everything works." if not bad else "problems: " + ", ".join(bad)))
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
        self.set_status("LLM settings saved. Click 'Run full check' to test.")
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
        self.set_status("Coverr key saved. Its videos will be searched along with Pixabay's.")
        self.refresh_setup()

    def save_upload(self):
        if not self.up_profile.get().strip():
            messagebox.showwarning("Profile", "Enter the Upload-Post profile (user) name.")
            return
        if not self.confirm_config_write():
            return
        changes = {"upload_post_enabled": self.up_enabled.get(),
                   "upload_post_username": self.up_profile.get().strip(),
                   "upload_post_platforms": ["youtube"],
                   "upload_post_auto_upload": False,          # approval gate
                   "upload_post_youtube_made_for_kids": False}
        if self.up_key.get().strip():
            changes["upload_post_api_key"] = self.up_key.get().strip()
        write_mpt_config(changes)
        self.up_key.set("")
        self.set_status("Upload-Post settings saved (YouTube only, auto-upload off).")
        self.refresh_all()

    def register(self):
        code, out = register_schedule(eng.load_settings()["run_times"])
        self.set_status("Schedule registered." if code == 0 else f"Failed: {out[-200:]}")
        self.bg(task_info, self.on_task_info)

    def clean_now(self):
        if eng.is_running():
            messagebox.showinfo("Busy", "A run is in progress; clean after it finishes.")
            return
        days = eng.load_settings()["clean_after_days"] or 14
        if messagebox.askyesno("Clean", f"Delete MPT render files and downloaded clips older than {days} days?\n"
                                        "Your review/approved/posted videos are not touched."):
            freed = eng.clean_mpt_cache(mpt_dir(), days)
            self.set_status(f"Freed {human(freed)}.")
            self.refresh_setup()

    def make_shortcut(self):
        pyw = mpt_dir() / ".venv" / "Scripts" / "pythonw.exe"
        script = (
            "$d=[Environment]::GetFolderPath('Desktop');"
            "$s=(New-Object -ComObject WScript.Shell).CreateShortcut(\"$d\\Shorts Autopilot.lnk\");"
            f"$s.TargetPath='{pyw}';$s.Arguments='\"{HERE / 'autopilot_gui.pyw'}\"';"
            f"$s.WorkingDirectory='{HERE}';$s.Save()")
        code, out = powershell(script)
        self.set_status("Desktop shortcut created." if code == 0 else f"Failed: {out[-200:]}")

    # ---- Logs ----------------------------------------------------------------------
    def build_logs(self):
        f = self.tabs["Logs"]
        bar = ttk.Frame(f)
        bar.pack(fill="x")
        self.errors_only = tk.BooleanVar()
        ttk.Checkbutton(bar, text="Problems only", variable=self.errors_only,
                        command=self.refresh_logs).pack(side="left")
        ttk.Button(bar, text="Refresh", command=self.refresh_logs).pack(side="left", padx=6)
        ttk.Button(bar, text="Open logs folder", command=lambda: open_path(eng.LOG_DIR)).pack(side="right")
        frame = ttk.Frame(f)
        frame.pack(fill="both", expand=True, pady=6)
        self.log_text = tk.Text(frame, wrap="none", font=("Consolas", 9), background="#fbfbfb")
        sb = ttk.Scrollbar(frame, orient="vertical", command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=sb.set)
        self.log_text.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")

    def refresh_logs(self):
        lines = tail(eng.LOG_DIR / "daily.log", 500)
        if self.errors_only.get():
            lines = [l for l in lines if re.search(r"ERROR|FAIL|WARNING|Traceback|Error|UNCONFIRMED|=====", l)]
        at_end = self.log_text.yview()[1] > 0.98
        self.log_text.config(state="normal")
        self.log_text.delete("1.0", "end")
        self.log_text.insert("1.0", "\n".join(lines) or "No log yet.")
        self.log_text.config(state="disabled")
        if at_end or self.proc:
            self.log_text.see("end")


def main():
    try:  # crisp text on high-DPI screens, and real pixel coordinates for screenshots
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    root = tk.Tk()
    app = App(root)
    if "--screenshot" in sys.argv:
        i = sys.argv.index("--screenshot")
        out = Path(sys.argv[i + 1])
        tab = sys.argv[i + 2] if len(sys.argv) > i + 2 else "Dashboard"

        def shoot():
            import traceback
            from PIL import ImageGrab
            try:
                for frame in app.tabs.values():    # render every tab once (smoke test)
                    app.nb.select(frame)
                    root.update()
                app.nb.select(app.tabs[tab])
                if tab == "Review" and app.review_tree.get_children():
                    app.review_tree.selection_set(app.review_tree.get_children()[0])
                    root.update()
                    root.after(3000)               # let the thumbnail render
                root.update()
                x, y = root.winfo_rootx(), root.winfo_rooty()
                ImageGrab.grab(bbox=(x, y, x + root.winfo_width(), y + root.winfo_height())).save(out)
                print(f"saved {out}")
            except Exception:
                traceback.print_exc()
                root.after(0, lambda: sys.exit(1))
            finally:
                root.destroy()
        root.after(6000, shoot)                    # give the schedule query time to load
    root.mainloop()


if __name__ == "__main__":
    main()
