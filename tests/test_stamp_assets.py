"""Published pages reference their own files with a content version (scripts/stamp_assets.py)."""
import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
_spec = importlib.util.spec_from_file_location("stamp_assets", ROOT / "scripts" / "stamp_assets.py")
stamp_assets = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(stamp_assets)


def test_stamps_every_page_file_and_leaves_others(tmp_path):
    site = ROOT / "site"
    for name in ("index.html", "app.js", "calendar.js", "styles.css"):
        (tmp_path / name).write_bytes((site / name).read_bytes())
    (tmp_path / "data.js").write_text("window.CINEMA_DATA = {};\n")
    versions = stamp_assets.stamp_folder(tmp_path)
    html = (tmp_path / "index.html").read_text()
    assert set(versions) == {"styles.css", "data.js", "calendar.js", "app.js"}
    for name, v in versions.items():
        assert f'"{name}?v={v}"' in html and len(v) == 10
    assert 'href="manifest.webmanifest"' in html and 'href="favicon.png"' in html   # not versioned
    assert stamp_assets.stamp_folder(tmp_path) == versions                          # idempotent
    assert html == (tmp_path / "index.html").read_text()


def test_version_follows_content():
    html = '<script src="app.js?v=old"></script><script src="data.js"></script>'
    out = stamp_assets.stamp(html, {"app.js": "abc", "data.js": "def"})
    assert out == '<script src="app.js?v=abc"></script><script src="data.js?v=def"></script>'


def test_publish_and_ci_stamp_the_staged_copy():
    assert "scripts/stamp_assets.py" in (ROOT / "scripts" / "publish.sh").read_text()
    assert "scripts/stamp_assets.py _site" in (ROOT / ".github" / "workflows" / "refresh.yml").read_text()


def test_phone_page_scripts_are_versioned_too(tmp_path):
    """m/venues/index.html loads ../_shared/core.js and ../../data.js: a new phone page with a cached old core.js
    would call functions that aren't there."""
    import shutil
    shutil.copytree(ROOT / "site" / "m", tmp_path / "m")
    for name in ("index.html", "app.js", "calendar.js", "styles.css", "plan.js", "planner.js", "planner.css"):
        (tmp_path / name).write_bytes((ROOT / "site" / name).read_bytes())
    (tmp_path / "data.js").write_text("window.CINEMA_DATA = {};\n")
    stamp_assets.stamp_folder(tmp_path)
    phone = (tmp_path / "m" / "venues" / "index.html").read_text()
    core = stamp_assets.version((tmp_path / "m" / "_shared" / "core.js").read_bytes())
    data = stamp_assets.version((tmp_path / "data.js").read_bytes())
    assert f'src="../_shared/core.js?v={core}"' in phone and f'src="../../data.js?v={data}"' in phone
    assert 'href="venues.css?v=' in phone and 'href="../../manifest.webmanifest"' in phone      # not versioned
    stamp_assets.stamp_folder(tmp_path)
    assert (tmp_path / "m" / "venues" / "index.html").read_text() == phone                       # idempotent
