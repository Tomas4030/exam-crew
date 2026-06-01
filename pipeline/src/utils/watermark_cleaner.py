"""Image watermark cleaner for rendered PDF pages."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageFilter, ImageOps


def clean_rendered_page_watermark(image_path: str | Path, watermark_detected: bool = False) -> bool:
    """Remove light-grey diagonal watermarks from rendered pages.

    Conservative: only runs when preflight detected a watermark.
    Preserves dark text, tables and figures.
    Returns True if the image was modified.
    """
    if not watermark_detected:
        return False

    path = Path(image_path)
    try:
        img = Image.open(path).convert("RGB")
    except Exception:
        return False

    gray = ImageOps.grayscale(img)

    # Mask: mid-grey pixels typical of diagonal watermarks (not dark text, not white bg)
    mask = gray.point(lambda p: 255 if 110 <= p <= 225 else 0)
    mask = mask.filter(ImageFilter.GaussianBlur(radius=1.2))

    white = Image.new("RGB", img.size, "white")
    cleaned = Image.composite(white, img, mask)

    # Restore very dark pixels (real text/lines)
    dark_mask = gray.point(lambda p: 255 if p < 95 else 0)
    cleaned = Image.composite(img, cleaned, dark_mask)

    cleaned.save(path)
    return True
