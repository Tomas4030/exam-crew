from PIL import Image
from pathlib import Path

MAX_DIMENSION = 1024


def resize_image_for_vision(image_path: str, output_path: str = None) -> str:
    path = Path(image_path)
    img = Image.open(path)
    w, h = img.size
    if max(w, h) > MAX_DIMENSION:
        ratio = MAX_DIMENSION / max(w, h)
        img = img.resize((int(w * ratio), int(h * ratio)), Image.LANCZOS)
    out = output_path or str(path)
    img.save(out)
    return out
