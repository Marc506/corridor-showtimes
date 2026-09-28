"""Scheduling: config generation for macOS / Windows / Linux, time parsing, folder checks, and the
update runner's housekeeping. Pure functions only — nothing is installed."""
import os
import plistlib
import time
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from scraper import schedule as S
from scraper import update as U

ROOT = Path("/Users/someone/corridor-showtimes-main")
PY = ROOT / ".venv" / "bin" / "python"


def test_parse_times():
    assert S.parse_times(["01:00", "13:00"]) == [(1, 0), (13, 0)]
    assert S.parse_times(["7:30,19:05"]) == [(7, 30), (19, 5)]
    assert S.parse_times(["13:00", "01:00", "13:00"]) == [(1, 0), (13, 0)]      # sorted, deduplicated
    for bad in ("25:00", "7", "07:60", "noon"):
        with pytest.raises(ValueError):
            S.parse_times([bad])


def test_launchd_plist_uses_this_folder_and_never_publishes_by_default():
    p = plistlib.loads(S.launchd_plist(ROOT, PY, [(1, 0), (13, 0)]))
    assert p["Label"] == S.LABEL
    assert p["ProgramArguments"] == [str(PY), "-m", "scraper.update"]
    assert p["WorkingDirectory"] == str(ROOT)
    assert p["StartCalendarInterval"] == [{"Hour": 1, "Minute": 0}, {"Hour": 13, "Minute": 0}]
    assert "/usr/bin" in p["EnvironmentVariables"]["PATH"]                       # curl for screenslate
    assert plistlib.loads(S.launchd_plist(ROOT, PY, [(1, 0)], publish=True))["ProgramArguments"][-1] == "--publish"


def test_windows_task_xml():
    root = Path(r"C:\Users\someone\corridor-showtimes-main")
    py = root / ".venv" / "Scripts" / "pythonw.exe"
    xml = S.windows_task_xml(root, py, [(1, 0), (13, 30)])
    ns = {"t": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
    doc = ET.fromstring(xml.split("?>", 1)[1])
    starts = [e.text for e in doc.findall(".//t:CalendarTrigger/t:StartBoundary", ns)]
    assert starts == ["2026-01-01T01:00:00", "2026-01-01T13:30:00"]
    assert doc.find(".//t:Settings/t:StartWhenAvailable", ns).text == "true"      # catch up missed runs
    assert doc.find(".//t:Settings/t:DisallowStartIfOnBatteries", ns).text == "false"
    assert doc.find(".//t:Exec/t:Command", ns).text.endswith("pythonw.exe")       # no console window
    assert doc.find(".//t:Exec/t:Arguments", ns).text == "-m scraper.update"
    assert doc.find(".//t:Exec/t:WorkingDirectory", ns).text == str(root)


def test_windows_task_xml_escapes_paths():
    root = Path("/Users/a&b/<x>")
    xml = S.windows_task_xml(root, root / "py", [(1, 0)])
    ET.fromstring(xml.split("?>", 1)[1])                                         # still well-formed


def test_systemd_units_catch_up_missed_runs():
    service, timer = S.systemd_units(ROOT, PY, [(1, 0), (13, 0)])
    assert f"WorkingDirectory={ROOT}" in service
    assert f'ExecStart="{PY}" -m scraper.update' in service
    assert "OnCalendar=*-*-* 01:00:00" in timer and "OnCalendar=*-*-* 13:00:00" in timer
    assert "Persistent=true" in timer


def test_cron_block_and_strip_are_idempotent():
    block = S.cron_block(ROOT, PY, [(1, 0), (13, 30)])
    lines = block.strip().splitlines()
    assert lines[0].startswith("0 1 * * * ") and lines[1].startswith("30 13 * * * ")
    assert all(S.CRON_MARK in l and "scraper.update" in l for l in lines)
    other = "15 3 * * * backup.sh\n"
    assert S.strip_cron(other + block) == other                                   # only our lines go


def test_protected_macos_folders(tmp_path):
    home = tmp_path
    for name in ("Downloads", "Documents", "Desktop", "Library/Mobile Documents/com~apple~CloudDocs", "cinema"):
        (home / name / "proj").mkdir(parents=True)
    assert S.protected_macos_folder(home / "Downloads" / "proj", home) == "Downloads"
    assert S.protected_macos_folder(home / "Desktop" / "proj", home) == "Desktop"
    assert S.protected_macos_folder(home / "Library/Mobile Documents/com~apple~CloudDocs/proj", home) == "iCloud Drive"
    assert S.protected_macos_folder(home / "cinema" / "proj", home) is None
    link = home / "Downloads" / "link"                                            # a shortcut into home
    link.symlink_to(home / "cinema" / "proj")
    assert S.protected_macos_folder(link, home) is None                           # judged by the real path


def test_venv_python_is_the_projects_own(tmp_path):
    assert S.venv_python(tmp_path) is None
    if os.name != "nt":
        (tmp_path / ".venv" / "bin").mkdir(parents=True)
        (tmp_path / ".venv" / "bin" / "python").write_text("")
        assert S.venv_python(tmp_path) == tmp_path / ".venv" / "bin" / "python"


def test_last_run_line_reads_both_old_and_new_logs(tmp_path):
    (tmp_path / "logs").mkdir()
    (tmp_path / "logs" / "refresh.log").write_text(
        "2026-09-27 21:30:23 [refresh] done (exit 0)\nnoise\n2026-09-28 01:08:56 [update] done (exit 0)\n")
    assert S.last_run_line(tmp_path).startswith("2026-09-28 01:08:56")
    assert S.last_run_line(tmp_path / "nope") is None


# ---- scraper.update housekeeping

def test_rotate_log_keeps_the_tail(tmp_path):
    log = tmp_path / "refresh.log"
    log.write_text("".join(f"line {i}\n" for i in range(1000)))
    U.rotate_log(log, max_bytes=100, keep_lines=10)
    assert log.read_text().splitlines() == [f"line {i}" for i in range(990, 1000)]
    U.rotate_log(log, max_bytes=10_000, keep_lines=1)                             # small enough: untouched
    assert len(log.read_text().splitlines()) == 10


def test_prune_raw_removes_only_old_folders(tmp_path):
    old, new = tmp_path / "2026-09-01", tmp_path / "2026-09-27"
    old.mkdir()
    new.mkdir()
    (old / "bam.json").write_text("{}")
    past = time.time() - 20 * 86400
    os.utime(old, (past, past))
    assert U.prune_raw(tmp_path, keep_days=14) == ["2026-09-01"]
    assert not old.exists() and new.exists()
    assert U.prune_raw(tmp_path / "missing") == []


def test_update_never_publishes_without_the_flag(monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(U, "LOG", tmp_path / "refresh.log")
    monkeypatch.setattr(U, "RAW", tmp_path / "raw")
    monkeypatch.setattr(U, "_step", lambda fh, *args: calls.append(args) or 0)
    ran = []
    monkeypatch.setattr(U.subprocess, "run", lambda *a, **k: ran.append(a) or type("R", (), {"returncode": 0})())
    assert U.main([]) == 0
    assert calls == [("scraper.run", "--no-export"), ("scraper.export",)]
    assert ran == []                                                              # publish.sh not called
    assert "[update] done (exit 0)" in (tmp_path / "refresh.log").read_text()
