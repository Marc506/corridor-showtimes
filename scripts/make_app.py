"""Build ~/Applications/Corridor Showtimes.app (double-click -> scripts/open_site.sh).

    /opt/anaconda3/bin/python3 scripts/make_app.py      # needs Pillow for the icon
"""
import shutil
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
APP = Path.home() / "Applications" / "Corridor Showtimes.app"


def draw_icon(size: int = 1024) -> Image.Image:
    s = size / 1024
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    pad = int(90 * s)
    d.rounded_rectangle([pad, pad, size - pad, size - pad], radius=int(190 * s), fill=(28, 28, 30))
    # film strip across the middle
    top, bot = int(330 * s), int(694 * s)
    d.rectangle([pad, top, size - pad, bot], fill=(230, 57, 70))
    hole_w, hole_h, gap = int(46 * s), int(34 * s), int(92 * s)
    for x in range(pad + int(40 * s), size - pad - hole_w, gap):
        d.rounded_rectangle([x, top + int(22 * s), x + hole_w, top + int(22 * s) + hole_h], radius=int(6 * s), fill=(28, 28, 30))
        d.rounded_rectangle([x, bot - int(22 * s) - hole_h, x + hole_w, bot - int(22 * s)], radius=int(6 * s), fill=(28, 28, 30))
    # three "timeline" blocks inside the strip
    y0, y1 = int(430 * s), int(594 * s)
    for (x0, x1), col in zip([(200, 420), (450, 610), (640, 830)], [(251, 250, 247), (244, 162, 97), (58, 134, 255)]):
        d.rounded_rectangle([int(x0 * s), y0, int(x1 * s), y1], radius=int(18 * s), fill=col)
    # little clock-hand ticks above/below: hour marks
    for i, x in enumerate(range(int(200 * s), int(840 * s), int(80 * s))):
        h = int((40 if i % 2 == 0 else 22) * s)
        d.rectangle([x, int(250 * s) - h, x + int(8 * s), int(250 * s)], fill=(154, 150, 141))
    return img


def build_icns(dest: Path) -> None:
    base = draw_icon()
    with tempfile.TemporaryDirectory() as tmp:
        iconset = Path(tmp) / "icon.iconset"
        iconset.mkdir()
        for px in (16, 32, 128, 256, 512):
            base.resize((px, px), Image.LANCZOS).save(iconset / f"icon_{px}x{px}.png")
            base.resize((px * 2, px * 2), Image.LANCZOS).save(iconset / f"icon_{px}x{px}@2x.png")
        subprocess.run(["iconutil", "-c", "icns", str(iconset), "-o", str(dest)], check=True)


def main() -> None:
    script = f'do shell script "/bin/zsh " & quoted form of "{ROOT}/scripts/open_site.sh"'
    if APP.exists():
        shutil.rmtree(APP)
    APP.parent.mkdir(parents=True, exist_ok=True)
    subprocess.run(["osacompile", "-o", str(APP), "-e", script], check=True)
    build_icns(APP / "Contents" / "Resources" / "applet.icns")
    # the icon changed the bundle after osacompile signed it: re-sign (ad hoc) so macOS will open it
    subprocess.run(["codesign", "--force", "--deep", "--sign", "-", str(APP)], check=True)
    subprocess.run(["touch", str(APP)], check=True)          # refresh Finder's icon cache
    print(f"built {APP}")


if __name__ == "__main__":
    main()
