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
