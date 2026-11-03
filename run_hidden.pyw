"""Starts run_daily.bat with no window at all. Task Scheduler runs this through pythonw.exe (which has no console)
instead of cmd.exe.

Why: a scheduled run used to open a visible console window. Closing it, or pressing Ctrl+C in it, silently killed the
run; logs/crash.log recorded exactly that twice on 2026-11-03, once in the middle of an upload. The run now has no
window to close and its own process group, so no key press can reach it. This script waits for the run and exits with
its exit code, so Task Scheduler's "last result" is the real result of the run."""

import subprocess
import sys
from datetime import datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
NO_WINDOW, NEW_GROUP = 0x08000000, 0x00000200       # CREATE_NO_WINDOW, CREATE_NEW_PROCESS_GROUP


def main(args):
    try:
        return subprocess.run(["cmd", "/c", str(HERE / "run_daily.bat"), *args], cwd=str(HERE),
                              creationflags=NO_WINDOW | NEW_GROUP, stdin=subprocess.DEVNULL,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode
    except Exception as err:                         # nothing can be printed from here: leave a note where the app looks
        (HERE / "logs").mkdir(exist_ok=True)
        with (HERE / "logs" / "crash.log").open("a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] could not start the run: {err}\n")
        return 3


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
