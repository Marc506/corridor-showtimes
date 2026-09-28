"""Turn daily automatic updates on or off for this folder, on macOS, Windows or Linux.

    python -m scraper.schedule on                  # update at 01:00 and 13:00 every day
    python -m scraper.schedule on --times 07:30    # choose your own times (this computer's clock)
    python -m scraper.schedule status              # is it on? when did it last run?
    python -m scraper.schedule off

What it installs, per OS (all run `python -m scraper.update` in this folder, output in logs/):
  macOS    a LaunchAgent (~/Library/LaunchAgents/com.corridor-showtimes.update.plist); a run missed
           while the Mac slept happens when it wakes.
  Windows  a Task Scheduler task "Corridor Showtimes update", set to run as soon as possible after a
           missed start, with pythonw (no console window).
  Linux    a systemd user timer (Persistent=true catches up missed runs); cron if systemd isn't there.
Updates only happen while the computer is on (asleep is fine on macOS). Nothing is published.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import plistlib
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from . import i18n
from .i18n import t

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_TIMES = ("01:00", "13:00")
LABEL = "com.corridor-showtimes.update"                     # macOS LaunchAgent
LEGACY_LABEL = "com.cinema.refresh"                         # the author's original job (scripts/refresh.sh)
WIN_TASK = "Corridor Showtimes update"
SYSTEMD_UNIT = "corridor-showtimes-update"
CRON_MARK = "# corridor-showtimes update"

i18n.register({
    "sch.on": {"zh": "已开启自动更新：每天 {times}（这台电脑的时间），只要电脑开着。",
               "en": "Automatic updates are on: every day at {times} (this computer's clock), whenever it's on."},
    "sch.on_mac": {"zh": "Mac 在那个时间睡眠的话，醒来后会补上这一次。",
                   "en": "If the Mac is asleep at that time, the update runs when it wakes."},
    "sch.on_win": {"zh": "电脑在那个时间关机或睡眠的话，下次开机后会尽快补上。",
                   "en": "If the PC is off or asleep then, the update runs as soon as possible afterwards."},
    "sch.on_linux": {"zh": "用的是 {how}。", "en": "Using {how}."},
    "sch.where": {"zh": "文件夹：{root}\n日志：{log}", "en": "Folder: {root}\nLog: {log}"},
    "sch.off": {"zh": "已关闭自动更新。", "en": "Automatic updates are off."},
    "sch.not_on": {"zh": "自动更新没有开启。开启：python -m scraper.schedule on",
                   "en": "Automatic updates are not on. Turn them on: python -m scraper.schedule on"},
    "sch.status_on": {"zh": "自动更新已开启（{how}），文件夹：{root}", "en": "Automatic updates are on ({how}), folder: {root}"},
    "sch.other_folder": {"zh": "注意：定时任务指向的是另一个文件夹 {root}。要改成这个文件夹，运行 python -m scraper.schedule on",
                         "en": "Note: the scheduled job points at another folder, {root}. To use this folder, run python -m scraper.schedule on"},
    "sch.last_data": {"zh": "数据最后更新：{when}", "en": "Data last updated: {when}"},
    "sch.no_data": {"zh": "还没有数据（先运行一次 python -m scraper.update）", "en": "No data yet (run python -m scraper.update once)"},
    "sch.last_run": {"zh": "最近一次运行：{line}", "en": "Last run: {line}"},
    "sch.protected": {
        "zh": "这个文件夹在「{name}」里。macOS 不允许后台任务读取「下载」「文稿」「桌面」和 iCloud 云盘里的文件，"
              "定时更新会失败。请把整个文件夹移到你的个人文件夹（例如 {suggest}），在新位置重新打开，再运行一次这条命令。",
        "en": "This folder is inside {name}. macOS doesn't let background jobs read Downloads, Documents, Desktop "
              "or iCloud Drive, so scheduled updates would fail. Move the whole folder into your home folder "
              "(e.g. {suggest}), reopen it there, and run this command again."},
    "sch.legacy": {"zh": "这台 Mac 上还有作者原来的定时任务 {label}（运行 {script}）。两个都开会每次抓两遍。"
                         "加 --replace-legacy 用新的替换它。",
                   "en": "This Mac also has the author's original job {label} (runs {script}); keeping both would "
                         "scrape twice. Add --replace-legacy to replace it with the new one."},
    "sch.legacy_removed": {"zh": "已移除旧的定时任务 {label}。", "en": "Removed the old job {label}."},
    "sch.bad_time": {"zh": "时间格式不对：{value}（要写成 07:30 这样的 24 小时制）",
                     "en": "Bad time: {value} (use 24-hour HH:MM, e.g. 07:30)"},
    "sch.no_venv": {"zh": "找不到本项目的 Python 环境（.venv）。先按 README 安装，再运行这条命令。",
                    "en": "Can't find this project's Python environment (.venv). Install per the README first."},
    "sch.failed": {"zh": "设置定时任务失败：{detail}", "en": "Couldn't set up the scheduled job: {detail}"},
    "sch.unsupported": {"zh": "不支持这个系统（{system}）。可以手动每天运行 python -m scraper.update。",
                        "en": "Unsupported system ({system}). Run python -m scraper.update daily by hand instead."},
})


# ---------------------------------------------------------------- pure helpers (tested offline)

def parse_times(values: list[str] | tuple[str, ...]) -> list[tuple[int, int]]:
    out = []
    for v in values:
        for part in str(v).split(","):
            part = part.strip()
            m = re.fullmatch(r"(\d{1,2}):(\d{2})", part)
            if not m or not (0 <= int(m[1]) <= 23 and 0 <= int(m[2]) <= 59):
                raise ValueError(t("sch.bad_time", value=part))
            out.append((int(m[1]), int(m[2])))
    return sorted(set(out))


def fmt_times(times: list[tuple[int, int]]) -> str:
    return "、".join(f"{h:02d}:{m:02d}" for h, m in times) if i18n.current_lang() == "zh" \
        else ", ".join(f"{h:02d}:{m:02d}" for h, m in times)


def protected_macos_folder(root: Path, home: Path | None = None) -> str | None:
    """Name of the TCC-protected folder `root` lives in (Downloads/Documents/Desktop/iCloud), else None."""
    home = (home or Path.home()).resolve()
    root = root.resolve()
    for name in ("Downloads", "Documents", "Desktop", "Library/Mobile Documents"):
        base = home / name
        if root == base or base in root.parents:
            return "iCloud Drive" if name.startswith("Library") else name
    return None


def venv_python(root: Path, windowless: bool = False) -> Path | None:
    """The project's own interpreter (never a system Python), preferring pythonw on Windows."""
    cands = ([root / ".venv" / "Scripts" / ("pythonw.exe" if windowless else "python.exe"),
              root / ".venv" / "Scripts" / "python.exe"] if os.name == "nt"
             else [root / ".venv" / "bin" / "python"])
    for c in cands:
        if c.exists():
            return c
    return None


def update_args(publish: bool) -> list[str]:
    return ["-m", "scraper.update"] + (["--publish"] if publish else [])


def launchd_plist(root: Path, python: Path, times, publish: bool = False) -> bytes:
    return plistlib.dumps({
        "Label": LABEL,
        "ProgramArguments": [str(python), *update_args(publish)],
        "WorkingDirectory": str(root),
        "StartCalendarInterval": [{"Hour": h, "Minute": m} for h, m in times],
        "StandardOutPath": str(root / "logs" / "scheduler.log"),
        "StandardErrorPath": str(root / "logs" / "scheduler.log"),
        # PATH: curl (screenslate) and gh (publishing) live in these places
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
                                 "PYTHONUNBUFFERED": "1"},
        "LimitLoadToSessionType": "Aqua",      # logged-in session: MoMA's browser path may open a window
        "ProcessType": "Background",
    })


def windows_task_xml(root: Path, python: Path, times, publish: bool = False) -> str:
    triggers = "\n".join(
        f"""    <CalendarTrigger>
      <StartBoundary>2026-01-01T{h:02d}:{m:02d}:00</StartBoundary>
      <Enabled>true</Enabled>
      <ScheduleByDay><DaysInterval>1</DaysInterval></ScheduleByDay>
    </CalendarTrigger>""" for h, m in times)
    return f"""<?xml version="1.0" encoding="UTF-16"?>
<Task version="1.2" xmlns="http://schemas.microsoft.com/windows/2004/02/mit/task">
  <RegistrationInfo><Description>Corridor Showtimes: update showtimes in {escape(str(root))}</Description></RegistrationInfo>
  <Triggers>
{triggers}
  </Triggers>
  <Principals><Principal id="Author"><LogonType>InteractiveToken</LogonType><RunLevel>LeastPrivilege</RunLevel></Principal></Principals>
  <Settings>
    <MultipleInstancesPolicy>IgnoreNew</MultipleInstancesPolicy>
    <DisallowStartIfOnBatteries>false</DisallowStartIfOnBatteries>
    <StopIfGoingOnBatteries>false</StopIfGoingOnBatteries>
    <StartWhenAvailable>true</StartWhenAvailable>
    <RunOnlyIfNetworkAvailable>true</RunOnlyIfNetworkAvailable>
    <ExecutionTimeLimit>PT1H</ExecutionTimeLimit>
    <Enabled>true</Enabled>
  </Settings>
  <Actions Context="Author">
    <Exec>
      <Command>{escape(str(python))}</Command>
      <Arguments>{escape(" ".join(update_args(publish)))}</Arguments>
      <WorkingDirectory>{escape(str(root))}</WorkingDirectory>
    </Exec>
  </Actions>
</Task>
"""


def systemd_units(root: Path, python: Path, times, publish: bool = False) -> tuple[str, str]:
    service = f"""[Unit]
Description=Corridor Showtimes update ({root})
Wants=network-online.target
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory={root}
ExecStart="{python}" {" ".join(update_args(publish))}
"""
    calendars = "\n".join(f"OnCalendar=*-*-* {h:02d}:{m:02d}:00" for h, m in times)
    timer = f"""[Unit]
Description=Run Corridor Showtimes update daily

[Timer]
{calendars}
Persistent=true

[Install]
WantedBy=timers.target
"""
    return service, timer


def cron_block(root: Path, python: Path, times, publish: bool = False) -> str:
    cmd = f'cd "{root}" && "{python}" {" ".join(update_args(publish))} >> "{root}/logs/scheduler.log" 2>&1'
    return "\n".join(f"{m} {h} * * * {cmd}  {CRON_MARK}" for h, m in times) + "\n"


def strip_cron(crontab: str) -> str:
    return "".join(l for l in crontab.splitlines(keepends=True) if CRON_MARK not in l)


def last_data_update(root: Path = ROOT) -> str | None:
    try:
        gen = json.loads((root / "data" / "showtimes.json").read_text(encoding="utf-8"))["generated_at"]
        return datetime.fromisoformat(gen.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except (OSError, ValueError, KeyError):
        return None


def last_run_line(root: Path = ROOT) -> str | None:
    try:
        lines = (root / "logs" / "refresh.log").read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return None
    done = [l for l in lines if "[update] done" in l or "[refresh] done" in l]
    return done[-1] if done else None


# ---------------------------------------------------------------- per-OS install / remove / status

def _run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, **kw)


class Mac:
    how = "launchd"

    def __init__(self):
        self.domain = f"gui/{os.getuid()}"
        self.plist = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
        self.legacy = Path.home() / "Library" / "LaunchAgents" / f"{LEGACY_LABEL}.plist"

    def installed_root(self) -> Path | None:
        try:
            return Path(plistlib.loads(self.plist.read_bytes())["WorkingDirectory"])
        except (OSError, KeyError, plistlib.InvalidFileException):
            return None

    def legacy_script(self) -> str | None:
        try:
            return plistlib.loads(self.legacy.read_bytes())["ProgramArguments"][-1]
        except (OSError, KeyError, IndexError, plistlib.InvalidFileException):
            return None

    def remove_legacy(self) -> None:
        _run(["launchctl", "bootout", f"{self.domain}/{LEGACY_LABEL}"])
        self.legacy.unlink(missing_ok=True)

    def install(self, root, python, times, publish):
        self.plist.parent.mkdir(parents=True, exist_ok=True)
        _run(["launchctl", "bootout", f"{self.domain}/{LABEL}"])          # replace if already there
        self.plist.write_bytes(launchd_plist(root, python, times, publish))
        r = _run(["launchctl", "bootstrap", self.domain, str(self.plist)])
        if r.returncode != 0:
            raise RuntimeError(r.stderr.strip() or f"launchctl exit {r.returncode}")

    def uninstall(self):
        _run(["launchctl", "bootout", f"{self.domain}/{LABEL}"])
        self.plist.unlink(missing_ok=True)

    def state(self) -> str | None:
        r = _run(["launchctl", "print", f"{self.domain}/{LABEL}"])
        if r.returncode != 0:
            return None
        bits = [m.group(0).strip() for m in re.finditer(r"(state = [^\n]+|last exit code = [^\n]+)", r.stdout)]
        return ", ".join(bits) or "loaded"


class Windows:
    how = "Task Scheduler"

    def installed_root(self) -> Path | None:
        r = _run(["schtasks", "/Query", "/TN", WIN_TASK, "/XML"])
        m = re.search(r"<WorkingDirectory>(.*?)</WorkingDirectory>", r.stdout or "")
        return Path(m.group(1)) if r.returncode == 0 and m else None

    def install(self, root, python, times, publish):
        with tempfile.NamedTemporaryFile("w", suffix=".xml", delete=False, encoding="utf-16") as f:
            f.write(windows_task_xml(root, python, times, publish))
        try:
            r = _run(["schtasks", "/Create", "/TN", WIN_TASK, "/XML", f.name, "/F"])
        finally:
            os.unlink(f.name)
        if r.returncode != 0:
            raise RuntimeError((r.stderr or r.stdout).strip())

    def uninstall(self):
        _run(["schtasks", "/Delete", "/TN", WIN_TASK, "/F"])

    def state(self) -> str | None:
        r = _run(["schtasks", "/Query", "/TN", WIN_TASK, "/FO", "LIST", "/V"])
        if r.returncode != 0:
            return None
        keep = [l.strip() for l in r.stdout.splitlines() if re.match(r"\s*(Status|Next Run Time|Last Run Time|Last Result):", l)]
        return "; ".join(keep) or "installed"


class Linux:
    def __init__(self):
        self.unit_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd" / "user"
        self.systemd = shutil.which("systemctl") is not None and _run(["systemctl", "--user", "is-system-running"]).returncode in (0, 1)
        self.how = "systemd timer" if self.systemd else "cron"

    def _svc(self):
        return self.unit_dir / f"{SYSTEMD_UNIT}.service", self.unit_dir / f"{SYSTEMD_UNIT}.timer"

    def installed_root(self) -> Path | None:
        svc, _ = self._svc()
        text = svc.read_text() if svc.exists() else (_run(["crontab", "-l"]).stdout or "")
        m = re.search(r"WorkingDirectory=(.+)", text) or re.search(r'cd "([^"]+)" .*' + re.escape(CRON_MARK), text)
        return Path(m.group(1).strip()) if m else None

    def install(self, root, python, times, publish):
        if self.systemd:
            svc, tmr = self._svc()
            svc.parent.mkdir(parents=True, exist_ok=True)
            s, tm = systemd_units(root, python, times, publish)
            svc.write_text(s)
            tmr.write_text(tm)
            for cmd in (["systemctl", "--user", "daemon-reload"],
                        ["systemctl", "--user", "enable", "--now", f"{SYSTEMD_UNIT}.timer"]):
                r = _run(cmd)
                if r.returncode != 0:
                    raise RuntimeError(r.stderr.strip())
        else:
            current = _run(["crontab", "-l"]).stdout or ""
            r = _run(["crontab", "-"], input=strip_cron(current) + cron_block(root, python, times, publish))
            if r.returncode != 0:
                raise RuntimeError(r.stderr.strip())

    def uninstall(self):
        svc, tmr = self._svc()
        if tmr.exists():
            _run(["systemctl", "--user", "disable", "--now", f"{SYSTEMD_UNIT}.timer"])
            svc.unlink(missing_ok=True)
            tmr.unlink(missing_ok=True)
            _run(["systemctl", "--user", "daemon-reload"])
        current = _run(["crontab", "-l"]).stdout or ""
        if CRON_MARK in current:
            _run(["crontab", "-"], input=strip_cron(current))

    def state(self) -> str | None:
        if self.systemd and self._svc()[1].exists():
            r = _run(["systemctl", "--user", "list-timers", f"{SYSTEMD_UNIT}.timer", "--no-legend"])
            return r.stdout.strip() or "enabled"
        return "cron" if CRON_MARK in (_run(["crontab", "-l"]).stdout or "") else None


def backend():
    system = platform.system()
    if system == "Darwin":
        return Mac()
    if system == "Windows":
        return Windows()
    if system == "Linux":
        return Linux()
    raise SystemExit(t("sch.unsupported", system=system))


# ---------------------------------------------------------------- commands

def cmd_on(times, publish: bool, replace_legacy: bool, root: Path = ROOT) -> int:
    be = backend()
    if isinstance(be, Mac):
        protected = protected_macos_folder(root)
        if protected:
            print(t("sch.protected", name=protected, suggest=Path.home() / root.name))
            return 2
        legacy = be.legacy_script()
        if legacy and Path(legacy).resolve().parent.parent == root.resolve():
            if not replace_legacy:
                print(t("sch.legacy", label=LEGACY_LABEL, script=legacy))
                return 2
            be.remove_legacy()
            print(t("sch.legacy_removed", label=LEGACY_LABEL))
    python = venv_python(root, windowless=True)
    if not python:
        print(t("sch.no_venv"))
        return 2
    (root / "logs").mkdir(exist_ok=True)
    try:
        be.install(root, python, times, publish)
    except (RuntimeError, OSError) as e:
        print(t("sch.failed", detail=e))
        return 1
    print(t("sch.on", times=fmt_times(times)))
    print(t("sch.on_mac") if isinstance(be, Mac) else t("sch.on_win") if isinstance(be, Windows)
          else t("sch.on_linux", how=be.how))
    print(t("sch.where", root=root, log=root / "logs" / "refresh.log"))
    return 0


def cmd_off() -> int:
    backend().uninstall()
    print(t("sch.off"))
    return 0


def is_on(root: Path = ROOT) -> bool:
    """True if a scheduled update for this folder is installed (used by the add-venue wizard)."""
    try:
        be = backend()
    except SystemExit:
        return False
    installed = be.installed_root()
    if installed and installed.resolve() == root.resolve():
        return True
    return isinstance(be, Mac) and bool(be.legacy_script()) and \
        Path(be.legacy_script()).resolve().parent.parent == root.resolve()


def cmd_status(root: Path = ROOT) -> int:
    be = backend()
    installed = be.installed_root()
    state = be.state()
    if installed and state:
        if installed.resolve() != root.resolve():
            print(t("sch.other_folder", root=installed))
        else:
            print(t("sch.status_on", how=be.how, root=installed))
        print(f"  {state}")
    elif isinstance(be, Mac) and be.legacy_script():
        print(t("sch.status_on", how=f"launchd, {LEGACY_LABEL}", root=Path(be.legacy_script()).parent.parent))
    else:
        print(t("sch.not_on"))
    when = last_data_update(root)
    print(t("sch.last_data", when=when) if when else t("sch.no_data"))
    line = last_run_line(root)
    if line:
        print(t("sch.last_run", line=line))
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m scraper.schedule",
                                 description="Turn daily automatic updates on or off (macOS, Windows, Linux).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    on = sub.add_parser("on", help="update every day at the given times")
    on.add_argument("--times", nargs="+", default=list(DEFAULT_TIMES), metavar="HH:MM",
                    help="24-hour times on this computer's clock (default: 01:00 13:00)")
    on.add_argument("--publish", action="store_true", help="also publish to GitHub Pages after each update")
    on.add_argument("--replace-legacy", action="store_true", help=f"macOS: replace the old {LEGACY_LABEL} job")
    sub.add_parser("off", help="stop automatic updates")
    sub.add_parser("status", help="show whether automatic updates are on and when data last changed")
    args = ap.parse_args(argv)
    if args.cmd == "on":
        try:
            times = parse_times(args.times)
        except ValueError as e:
            print(e)
            return 2
        return cmd_on(times, args.publish, args.replace_legacy)
    return cmd_off() if args.cmd == "off" else cmd_status()


if __name__ == "__main__":
    sys.exit(main())
