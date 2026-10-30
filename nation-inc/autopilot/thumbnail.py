"""1280x720 thumbnail: stock background, dark gradient, big Anton text with gold accent."""
import subprocess
from pathlib import Path

from PIL import Image, ImageDraw, ImageEnhance, ImageFilter, ImageFont

from .config import FONTS

GOLD = (212, 175, 55)
TW, TH = 1280, 720


def frame_from_video(video: str, out: Path, at: float = 2.0) -> Path:
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-ss", str(at), "-i", video, "-frames:v", "1", str(out)], check=True)
    return out


def _cover(img: Image.Image) -> Image.Image:
    s = max(TW / img.width, TH / img.height) * 1.04
    img = img.resize((int(img.width * s), int(img.height * s)), Image.LANCZOS)
    left, top = (img.width - TW) // 2, (img.height - TH) // 2
    return img.crop((left, top, left + TW, top + TH))


def _wrap(draw, words, font, max_w):
    lines, line = [], ""
    for w in words:
        t = f"{line} {w}".strip()
        if draw.textlength(t, font=font) > max_w and line:
            lines.append(line)
            line = w
        else:
            line = t
    if line:
        lines.append(line)
    return lines


def _add_mascot(bg):
    """Puts the channel mascot (Baron) big on the right side, with a white sticker outline."""
    try:
        from .character import thumbnail_image
        path = thumbnail_image()
        if not path:
            return
        m = Image.open(path).convert("RGBA")
        h = int(TH * 0.98)
        w = int(m.width * h / m.height)
        if w > 600:
            w, h = 600, int(m.height * 600 / m.width)
        m = m.resize((w, h), Image.LANCZOS)
        pad = 14
        canvas = Image.new("RGBA", (w + pad * 2, h + pad * 2), (0, 0, 0, 0))
        canvas.paste(m, (pad, pad), m)
        alpha = canvas.getchannel("A").point(lambda v: 255 if v > 40 else 0).filter(ImageFilter.MaxFilter(17))
        outline = Image.new("RGBA", canvas.size, (255, 255, 255, 255))
        outline.putalpha(alpha)
        glow = Image.new("RGBA", canvas.size, (212, 175, 55, 0))
        glow.putalpha(alpha.filter(ImageFilter.GaussianBlur(18)).point(lambda v: int(v * 0.8)))
        x = TW - canvas.width + 10
        y = TH - canvas.height + pad + 4
        bg.paste(glow, (x, y), glow)
        bg.paste(outline, (x, y), outline)
        bg.paste(canvas, (x, y), canvas)
    except Exception as e:
        print(f"[thumbnail] mascot not added: {e}", flush=True)


def make_thumbnail(bg_path: str | None, text: str, channel: str, out: Path) -> Path:
    if bg_path and Path(bg_path).exists():
        bg = _cover(Image.open(bg_path).convert("RGB"))
        bg = ImageEnhance.Contrast(bg).enhance(1.15)
        bg = ImageEnhance.Color(bg).enhance(1.2)
    else:
        bg = Image.new("RGB", (TW, TH), (14, 13, 11))
    shade = Image.new("L", (TW, 1))
    for x in range(TW):
        shade.putpixel((x, 0), int(235 * max(0.0, 1 - x / (TW * 0.78)) ** 1.1))
    black = Image.new("RGB", (TW, TH), (0, 0, 0))
    bg = Image.composite(black, bg, shade.resize((TW, TH)))

    _add_mascot(bg)
    d = ImageDraw.Draw(bg)
    words = (text or "").upper().split()[:5] or ["CASE", "STUDY"]
    size = 150
    while size > 60:
        font = ImageFont.truetype(str(FONTS / "Anton-Regular.ttf"), size)
        lines = _wrap(d, words, font, 760)
        if len(lines) <= 3 and all(d.textlength(l, font=font) <= 780 for l in lines):
            break
        size -= 6
    lh = int(size * 1.08)
    y = (TH - lh * len(lines)) // 2 - 10
    bottom = y
    for i, ln in enumerate(lines):
        color = GOLD if i == len(lines) - 1 else (255, 255, 255)
        d.text((64, y + i * lh), ln, font=font, fill=color, stroke_width=8, stroke_fill=(0, 0, 0))
        bottom = d.textbbox((64, y + i * lh), ln, font=font, stroke_width=8)[3]
    bar_y = min(bottom + 18, TH - 90)
    d.rectangle([64, bar_y, 244, bar_y + 12], fill=GOLD)
    if channel:
        f2 = ImageFont.truetype(str(FONTS / "Poppins-Bold.ttf"), 30)
        d.text((64, TH - 62), channel, font=f2, fill=(235, 235, 235))
    bg.save(out, "JPEG", quality=90, optimize=True)
    return out
