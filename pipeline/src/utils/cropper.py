"""Cropper v4: dual crop with auto_candidate_score for visual crops."""
import re
from pathlib import Path

import fitz  # PyMuPDF
from PIL import Image


# DPI used for page rendering (must match pdf_extractor.py)
RENDER_DPI = 200
SCALE = RENDER_DPI / 72  # PDF points to pixels

# Context crop regions (existing behavior)
FIGURE_ABOVE_LABEL_PX = 380
FIGURE_BELOW_LABEL_PX = 40
FIGURE_MARGIN_X_PX = 30
TABLE_PADDING_TOP_PCT = 5
TABLE_PADDING_BOTTOM_PCT = 35
TABLE_PADDING_X_PCT = 3
FALLBACK_PADDING_PCT = 8

# Visual crop settings
VISUAL_PAD_PX = 10


def _region_to_rect(region: dict | None) -> fitz.Rect | None:
    if not region:
        return None
    bbox = region.get("bbox") or []
    if len(bbox) != 4:
        return None
    try:
        return fitz.Rect(float(bbox[0]), float(bbox[1]), float(bbox[2]), float(bbox[3]))
    except Exception:
        return None


# ── Label Finding ────────────────────────────────────────────────

def _find_label_position(pdf_path: str, page_num: int, label: str) -> fitz.Rect | None:
    """Search for a standalone figure/table label on a PDF page."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    blocks = page.get_text("dict")["blocks"]
    doc.close()

    label_lower = label.lower().strip()

    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_text = "".join(span["text"] for span in line.get("spans", []))
            line_stripped = line_text.strip().lower()
            if line_stripped == label_lower or line_stripped == label_lower + ".":
                return fitz.Rect(line["bbox"])
            block_text = ""
            for bl in block.get("lines", []):
                block_text += "".join(s["text"] for s in bl.get("spans", []))
            block_text = block_text.strip().lower()
            if block_text == label_lower or block_text == label_lower + ".":
                return fitz.Rect(block["bbox"])

    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    rects = page.search_for(label)
    doc.close()

    if len(rects) == 1:
        return rects[0]
    elif len(rects) > 1:
        if "tabela" in label.lower() or "table" in label.lower():
            return sorted(rects, key=lambda r: r.y0)[0]
        else:
            return sorted(rects, key=lambda r: r.x0, reverse=True)[0]
    return None


def _find_label_regex(pdf_path: str, page_num: int, pattern: str) -> fitz.Rect | None:
    """Search for label using regex on text blocks."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    blocks = page.get_text("dict")["blocks"]
    doc.close()

    regex = re.compile(pattern, re.IGNORECASE)
    for block in blocks:
        if block.get("type") != 0:
            continue
        for line in block.get("lines", []):
            line_text = "".join(span["text"] for span in line.get("spans", []))
            if regex.search(line_text):
                return fitz.Rect(block["bbox"])
    return None


# ── Context Crop (existing logic) ────────────────────────────────

def _crop_context(img: Image.Image, label_rect: fitz.Rect, is_table: bool) -> Image.Image:
    """Context crop: captures the question area around the label."""
    img_w, img_h = img.size
    label_y_top = label_rect.y0 * SCALE
    label_y_bottom = label_rect.y1 * SCALE

    if is_table:
        top = max(0, int(label_y_top - img_h * TABLE_PADDING_TOP_PCT / 100))
        bottom = min(img_h, int(label_y_top + img_h * TABLE_PADDING_BOTTOM_PCT / 100))
        left = max(0, int(img_w * TABLE_PADDING_X_PCT / 100))
        right = min(img_w, int(img_w * (100 - TABLE_PADDING_X_PCT) / 100))
    else:
        top = max(0, int(label_y_top - FIGURE_ABOVE_LABEL_PX))
        bottom = min(img_h, int(label_y_bottom + FIGURE_BELOW_LABEL_PX))
        label_cx = ((label_rect.x0 + label_rect.x1) / 2) * SCALE
        crop_width = min(int(img_w * 0.75), 900)
        left = max(0, int(label_cx - crop_width / 2))
        right = min(img_w, int(label_cx + crop_width / 2))
        if right - left < 200:
            left = max(0, FIGURE_MARGIN_X_PX)
            right = min(img_w, img_w - FIGURE_MARGIN_X_PX)

    return img.crop((left, top, right, bottom))


def _crop_context_bbox(img: Image.Image, bbox: dict, is_table: bool) -> Image.Image:
    """Context crop fallback using LLM bbox estimate with generous padding."""
    w, h = img.size
    pad = TABLE_PADDING_TOP_PCT if is_table else FALLBACK_PADDING_PCT

    x_pct = max(0, bbox.get("x_pct", 0) - pad)
    y_pct = max(0, bbox.get("y_pct", 0) - pad)
    w_pct = min(100 - x_pct, bbox.get("w_pct", 0) + pad * 2)
    h_pct = min(100 - y_pct, bbox.get("h_pct", 0) + (pad + TABLE_PADDING_BOTTOM_PCT if is_table else pad * 2))

    x = int(w * x_pct / 100)
    y = int(h * y_pct / 100)
    crop_w = int(w * w_pct / 100)
    crop_h = int(h * h_pct / 100)

    return img.crop((x, y, min(w, x + crop_w), min(h, y + crop_h)))


def _crop_visual_bbox(img: Image.Image, bbox: dict, is_table: bool = False) -> Image.Image | None:
    """Tight visual crop from bbox_estimate / metadata.

    This is intentionally much tighter than _crop_context_bbox.  It is used as
    a fallback when the vector/label crop pulls in running question text.  The
    bbox coming from vision is often approximate, so we keep a small safety pad
    instead of the large context pad.
    """
    if not bbox:
        return None

    w, h = img.size
    try:
        x_pct = float(bbox.get("x_pct", bbox.get("x", 0)))
        y_pct = float(bbox.get("y_pct", bbox.get("y", 0)))
        w_pct = float(bbox.get("w_pct", bbox.get("width", 0)))
        h_pct = float(bbox.get("h_pct", bbox.get("height", 0)))
    except (TypeError, ValueError):
        return None

    if w_pct <= 0 or h_pct <= 0:
        return None

    # Small padding: enough to avoid cutting strokes/axis arrows, not enough to
    # include the surrounding question text.
    pad_x = 2.0 if not is_table else 1.0
    pad_top = 1.5 if not is_table else 1.0
    pad_bottom = 2.5 if not is_table else 1.0

    x0 = max(0.0, x_pct - pad_x)
    y0 = max(0.0, y_pct - pad_top)
    x1 = min(100.0, x_pct + w_pct + pad_x)
    y1 = min(100.0, y_pct + h_pct + pad_bottom)

    left = int(w * x0 / 100)
    top = int(h * y0 / 100)
    right = int(w * x1 / 100)
    bottom = int(h * y1 / 100)

    if right - left < 50 or bottom - top < 50:
        return None
    return img.crop((left, top, right, bottom))


def _auto_visual_is_polluted(diag: dict) -> bool:
    """True when auto_candidate_score likely included running question text.

    Do not send these directly to context.  For quiz assets, a metadata/bbox
    visual crop is usually better than a context crop with question text.
    """
    if not diag:
        return False
    return bool(
        diag.get("textRatio", 0) > 0.08
        or diag.get("score", 1.0) < 0.62
        or (diag.get("textTouchesEdge") and diag.get("textRatio", 0) > 0.03)
    )


def _bbox_is_consistent_with_label(
    bbox: dict | None,
    label_rect: fitz.Rect | None,
    page_rect: fitz.Rect,
) -> bool:
    """Reject LLM/metadata bboxes that are obviously far from the figure label.

    This is a general guard, not an exam-specific rule.  Vision bboxes are useful
    when they agree with the PDF geometry, but they can be badly wrong.  Example:
    a bbox for "Figura 4" can accidentally point to the lower half of the page
    near "Figura 5".  If a real label was found in the PDF, never let a far-away
    bbox override the label/cluster crop.
    """
    if not bbox or not label_rect:
        return True
    try:
        y_pct = float(bbox.get("y_pct", bbox.get("y", 0)))
        h_pct = float(bbox.get("h_pct", bbox.get("height", 0)))
        x_pct = float(bbox.get("x_pct", bbox.get("x", 0)))
        w_pct = float(bbox.get("w_pct", bbox.get("width", 0)))
    except (TypeError, ValueError):
        return False

    if w_pct <= 0 or h_pct <= 0:
        return False

    bbox_cx = page_rect.width * (x_pct + w_pct / 2) / 100
    bbox_cy = page_rect.height * (y_pct + h_pct / 2) / 100
    label_cx = (label_rect.x0 + label_rect.x1) / 2
    label_cy = (label_rect.y0 + label_rect.y1) / 2

    # Vertical agreement is the most important signal because figure captions
    # are normally immediately below/near the visual object.
    if abs(bbox_cy - label_cy) > max(185, page_rect.height * 0.30):
        return False

    # Horizontally, allow generous tolerance for wide graphs and captions.
    if abs(bbox_cx - label_cx) > max(260, page_rect.width * 0.55):
        return False

    return True


def _visual_crop_cluster_near_label(
    pdf_path: str,
    page_num: int,
    label_rect: fitz.Rect,
    img: Image.Image,
) -> tuple[Image.Image | None, dict]:
    """Crop the vector/drawing cluster immediately associated with a figure label.

    This is preferred over bbox_estimate for PDFs like Exames Nacionais, where
    many diagrams are vectors rather than embedded images.  It avoids the main
    failure mode of bbox/metadata crops: a wrong bbox can jump to a different
    figure or to surrounding running text.
    """
    try:
        doc = fitz.open(pdf_path)
        page = doc[page_num - 1]
        page_rect = page.rect
        label_cx = (label_rect.x0 + label_rect.x1) / 2

        try:
            clusters = list(page.cluster_drawings())
        except Exception:
            clusters = []

        if not clusters:
            drawings = []
            for d in page.get_drawings():
                r = fitz.Rect(d.get("rect"))
                if r.width >= 3 or r.height >= 3:
                    drawings.append(r)
            if drawings:
                u = fitz.Rect(drawings[0])
                for r in drawings[1:]:
                    u |= r
                clusters = [u]

        candidates: list[tuple[float, fitz.Rect]] = []
        for r in clusters:
            r = fitz.Rect(r)
            if r.is_empty or r.width < 12 or r.height < 12:
                continue
            if _is_separator_line(r, page_rect.width):
                continue

            # Caption normally sits below the diagram.  Keep a wide vertical
            # range to support tall diagrams, but do not grab earlier page items.
            if r.y0 > label_rect.y1 + 35:
                continue
            if r.y1 < label_rect.y0 - max(360, page_rect.height * 0.45):
                continue
            if r.y1 < label_rect.y0 - 2 or r.y0 <= label_rect.y1 + 20:
                pass
            else:
                continue

            expanded_x0 = r.x0 - 90
            expanded_x1 = r.x1 + 90
            horizontal_ok = expanded_x0 <= label_cx <= expanded_x1
            if not horizontal_ok:
                label_band = fitz.Rect(label_rect.x0 - 120, r.y0, label_rect.x1 + 120, r.y1)
                if (label_band & r).is_empty:
                    continue

            dist = abs(label_rect.y0 - r.y1)
            h_bonus = 1.0 if horizontal_ok else 0.65
            area_bonus = min(1.0, (r.width * r.height) / (page_rect.width * page_rect.height * 0.10))
            score = h_bonus * 3.0 + area_bonus - dist / 220.0
            candidates.append((score, r))

        if not candidates:
            doc.close()
            return None, {}

        candidates.sort(key=lambda item: item[0], reverse=True)
        cluster = fitz.Rect(candidates[0][1])

        # Expand to include short diagram labels, axis labels, chart titles, and
        # the figure caption, while excluding running question text.
        crop_rect = fitz.Rect(cluster)
        crop_rect |= label_rect

        for block in page.get_text("dict")["blocks"]:
            if block.get("type") != 0:
                continue
            block_text = ""
            for line in block.get("lines", []):
                block_text += "".join(s.get("text", "") for s in line.get("spans", []))
            block_text = block_text.strip()
            if not block_text:
                continue
            br = fitz.Rect(block["bbox"])

            # Always keep the caption itself.
            if not (br & label_rect).is_empty:
                crop_rect |= br
                continue

            short_label = _is_diagram_label(block_text) or len(block_text) <= 18
            near_cluster = not (br & fitz.Rect(cluster.x0 - 24, cluster.y0 - 24, cluster.x1 + 24, cluster.y1 + 24)).is_empty
            centered_title = (
                br.y1 <= cluster.y0 + 28
                and br.y0 >= cluster.y0 - 34
                and br.x0 >= cluster.x0 - 30
                and br.x1 <= cluster.x1 + 30
            )

            if short_label and near_cluster:
                crop_rect |= br
            elif centered_title:
                crop_rect |= br

        # Safety padding.
        pad_x = 14
        pad_top = 12
        pad_bottom = 10
        crop_rect = fitz.Rect(
            max(0, crop_rect.x0 - pad_x),
            max(0, crop_rect.y0 - pad_top),
            min(page_rect.width, crop_rect.x1 + pad_x),
            min(page_rect.height, crop_rect.y1 + pad_bottom),
        )
        doc.close()

        img_w, img_h = img.size
        left = max(0, int(crop_rect.x0 * SCALE))
        top = max(0, int(crop_rect.y0 * SCALE))
        right = min(img_w, int(crop_rect.x1 * SCALE))
        bottom = min(img_h, int(crop_rect.y1 * SCALE))
        if right - left < 60 or bottom - top < 60:
            return None, {}
        return img.crop((left, top, right, bottom)), {
            "score": 0.88,
            "textRatio": 0.0,
            "edgeTouch": False,
            "textTouchesEdge": False,
            "drawingCoverage": 1.0,
            "candidate": "cluster_drawings_near_label",
            "clusterRect": [round(cluster.x0, 2), round(cluster.y0, 2), round(cluster.x1, 2), round(cluster.y1, 2)],
        }
    except Exception:
        try:
            doc.close()
        except Exception:
            pass
        return None, {}


# ── Visual Crop: Auto Candidate Score ────────────────────────────

def _is_separator_line(r: fitz.Rect, page_width: float) -> bool:
    """Detect separator lines spanning most of the page."""
    if r.height < 2 and r.width > page_width * 0.6:
        return True
    if r.width < 2 and r.height > page_width * 0.5:
        return True
    return False


def _detect_ink_bbox(img: Image.Image, threshold: int = 240) -> tuple[int, int, int, int] | None:
    """Detect bounding box of non-white pixels (ink/drawings) in a crop.
    
    Returns (x, y, w, h) of the content box, or None if image is blank.
    """
    gray = img.convert("L")
    # Find bounding box of pixels darker than threshold
    bbox = gray.point(lambda p: 255 if p < threshold else 0).getbbox()
    if not bbox:
        return None
    x0, y0, x1, y1 = bbox
    return (x0, y0, x1 - x0, y1 - y0)


def _is_diagram_label(text: str) -> bool:
    """Check if text is a short diagram/axis label (not running text)."""
    t = text.strip()
    if len(t) <= 8:
        return True
    if re.match(r'^(Re\(z\)|Im\(z\)|Figura\s*\d+|Gráfico\s*\d+)$', t, re.IGNORECASE):
        return True
    return False


def _score_candidate(crop_rect: fitz.Rect, drawing_rects: list[fitz.Rect],
                     text_blocks: list[dict], page_rect: fitz.Rect) -> dict:
    """Score a crop candidate. Higher = better for quiz display."""
    crop_area = crop_rect.width * crop_rect.height
    if crop_area <= 0:
        return {"score": 0, "textRatio": 1.0, "edgeTouch": True, "textTouchesEdge": True, "drawingCoverage": 0}

    # Count drawings inside crop and check edge touch
    drawings_inside = 0
    edge_touch = False
    edge_margin = 4  # pts

    for dr in drawing_rects:
        inter = dr & crop_rect
        if inter.is_empty:
            continue
        drawings_inside += 1
        if (dr.x0 <= crop_rect.x0 + edge_margin or
            dr.x1 >= crop_rect.x1 - edge_margin or
            dr.y0 <= crop_rect.y0 + edge_margin or
            dr.y1 >= crop_rect.y1 - edge_margin):
            edge_touch = True

    total_drawings = len(drawing_rects)
    drawing_capture = drawings_inside / total_drawings if total_drawings > 0 else 0

    # Running text analysis
    running_text_area = 0
    text_touches_edge = False
    edge_text_margin = 6  # pts

    for tb in text_blocks:
        tb_rect = fitz.Rect(tb["bbox"])
        inter = tb_rect & crop_rect
        if inter.is_empty:
            continue
        tb_text = tb.get("text", "")
        if _is_diagram_label(tb_text) or len(tb_text) <= 15:
            continue
        running_text_area += inter.width * inter.height
        # Check if running text touches crop edge (visually jarring)
        if (tb_rect.x0 <= crop_rect.x0 + edge_text_margin or
            tb_rect.x1 >= crop_rect.x1 - edge_text_margin):
            text_touches_edge = True

    text_ratio = running_text_area / crop_area

    # Size ratio
    page_area = page_rect.width * page_rect.height
    size_ratio = crop_area / page_area

    # Granular score
    score = (
        0.30 * drawing_capture
        + 0.30 * max(0, 1.0 - text_ratio * 15)
        + 0.15 * (0.0 if edge_touch else 1.0)
        + 0.15 * (0.0 if text_touches_edge else 1.0)
        + 0.10 * max(0, 1.0 - max(0, size_ratio - 0.12) * 3)
    )

    return {
        "score": round(score, 3),
        "textRatio": round(text_ratio, 3),
        "edgeTouch": edge_touch,
        "textTouchesEdge": text_touches_edge,
        "drawingCoverage": round(drawing_capture, 3),
    }


def _visual_crop_figure(pdf_path: str, page_num: int, label_rect: fitz.Rect, img: Image.Image, question_region: fitz.Rect | None = None) -> tuple[Image.Image | None, dict]:
    """Auto candidate score: generate multiple crop candidates, score each, pick best.
    
    Returns (cropped_image, diagnostics_dict) or (None, {}).
    """
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    page_rect = page.rect

    label_y = label_rect.y0
    label_cx = (label_rect.x0 + label_rect.x1) / 2

    # Search window above label. Figures in national exams can be tall 3D
    # diagrams/graphs; 170pt was too small and cut upper content. Prefer the
    # linked question region when available, otherwise use a generous window.
    if question_region:
        window_top = max(0, min(question_region.y0, label_y - 300))
    else:
        window_top = max(0, label_y - 300)
    window_bottom = label_y - 2

    # Determine column bounds based on label position
    page_mid = page_rect.width / 2
    if label_cx > page_mid * 1.05:
        col_left, col_right = page_rect.width * 0.52, page_rect.width * 0.98
    elif label_cx < page_mid * 0.95:
        col_left, col_right = page_rect.width * 0.02, page_rect.width * 0.48
    else:
        col_left, col_right = page_rect.width * 0.03, page_rect.width * 0.97

    # Collect drawings in the search window (filtered by column)
    all_drawings = page.get_drawings()
    drawing_rects = []
    for d in all_drawings:
        r = fitz.Rect(d["rect"])
        if r.y1 < window_top or r.y0 > window_bottom:
            continue
        if r.width < 3 and r.height < 3:
            continue
        if _is_separator_line(r, page_rect.width):
            continue
        # Filter by column to avoid capturing drawings from adjacent figures
        if r.x1 < col_left or r.x0 > col_right:
            continue
        drawing_rects.append(r)

    # Collect text blocks with their text content
    blocks = page.get_text("dict")["blocks"]
    text_blocks = []
    for block in blocks:
        if block.get("type") != 0:
            continue
        block_text = ""
        for line in block.get("lines", []):
            block_text += "".join(s["text"] for s in line.get("spans", []))
        br = fitz.Rect(block["bbox"])
        if br.y1 < window_top - 20 or br.y0 > window_bottom + 5:
            continue
        text_blocks.append({"bbox": block["bbox"], "text": block_text.strip()})

    # Also collect image blocks as drawings
    for block in blocks:
        if block.get("type") == 1:
            r = fitz.Rect(block["bbox"])
            if r.y1 < window_top or r.y0 > window_bottom:
                continue
            drawing_rects.append(r)

    doc.close()

    if not drawing_rects:
        return None, {}

    # Compute base drawingBBox (union of all drawings in window)
    base_bbox = drawing_rects[0]
    for r in drawing_rects[1:]:
        base_bbox = base_bbox | r

    # Generate candidates with different padding levels (in PDF points)
    # 1pt ≈ 0.35mm, so 12pts ≈ 4mm, 20pts ≈ 7mm, 30pts ≈ 10mm
    paddings = [
        ("small", 18, 18, 16, 18),
        ("medium", 28, 28, 24, 28),
        ("large", 40, 40, 35, 40),
        ("xlarge", 55, 55, 48, 55),
    ]

    candidates = []
    for name, pt, pb, pl, pr in paddings:
        c = fitz.Rect(
            max(0, base_bbox.x0 - pl),
            max(0, base_bbox.y0 - pt),
            min(page_rect.width, base_bbox.x1 + pr),
            min(label_y - 1, base_bbox.y1 + pb),
        )
        if c.width > 20 and c.height > 20:
            candidates.append((name, c))

    # Also add column-clamped candidates for ALL padding levels
    for pad_name, pt, pb, pl, pr in paddings:
        c = fitz.Rect(
            max(col_left, base_bbox.x0 - pl),
            max(0, base_bbox.y0 - pt),
            min(col_right, base_bbox.x1 + pr),
            min(label_y - 1, base_bbox.y1 + pb),
        )
        if c.width > 20 and c.height > 20:
            candidates.append((f"col_{pad_name}", c))

    # Score all candidates
    scored = []
    # Preference order for tiebreaking (medium is the sweet spot)
    pref_order = {"col_medium": 10, "medium": 9, "col_small": 8, "small": 7,
                  "col_large": 6, "large": 5, "col_xlarge": 2, "xlarge": 1}
    
    for name, rect in candidates:
        if question_region:
            # Treat question_region as a soft bound. Region detection can be
            # imperfect; hard intersection can chop diagrams. Expand it first
            # and only use it when it still captures the drawing.
            soft_region = fitz.Rect(
                max(0, question_region.x0 - 35),
                max(0, question_region.y0 - 35),
                min(page_rect.width, question_region.x1 + 35),
                min(page_rect.height, question_region.y1 + 35),
            )
            clipped = rect & soft_region
            if not clipped.is_empty and clipped.width > 20 and clipped.height > 20:
                clipped_diag = _score_candidate(clipped, drawing_rects, text_blocks, page_rect)
                # Only accept the clipped version when it did not lose content.
                if clipped_diag.get("drawingCoverage", 0) >= 0.97:
                    rect = clipped
        diag = _score_candidate(rect, drawing_rects, text_blocks, page_rect)
        diag["candidate"] = name
        scored.append((rect, diag))

    if not scored:
        return None, {}

    # Sort by score descending; tiebreak: prefer medium-sized candidates
    scored.sort(key=lambda x: (x[1]["score"], pref_order.get(x[1]["candidate"], 0)), reverse=True)

    # Pick the best
    best_rect, best_diag = scored[0]

    # Metadata-based refinement: render initial crop, detect ink bbox,
    # expand proportionally until margins are comfortable
    img_w, img_h = img.size

    for _attempt in range(3):
        # Render current crop
        left = max(0, int(best_rect.x0 * SCALE))
        top = max(0, int(best_rect.y0 * SCALE))
        right = min(img_w, int(best_rect.x1 * SCALE))
        bottom = min(img_h, int(best_rect.y1 * SCALE))

        if (right - left) < 60 or (bottom - top) < 60:
            break

        crop_img = img.crop((left, top, right, bottom))
        content_box = _detect_ink_bbox(crop_img)
        if not content_box:
            break

        cx, cy, cw, ch = content_box
        margins = {
            "left": cx,
            "top": cy,
            "right": crop_img.width - (cx + cw),
            "bottom": crop_img.height - (cy + ch),
        }

        # Required margins: 8% of content size, clamped 20-80px
        min_mx = max(20, min(80, int(cw * 0.08)))
        min_my = max(20, min(80, int(ch * 0.08)))

        # Calculate needed expansion per side (in pixels)
        expand_left = max(0, min_mx - margins["left"])
        expand_right = max(0, min_mx - margins["right"])
        expand_top = max(0, min_my - margins["top"])
        expand_bottom = max(0, min_my - margins["bottom"])

        if expand_left + expand_right + expand_top + expand_bottom < 5:
            break  # margins already comfortable

        # Convert expansion from pixels to PDF points
        exp_pts_l = expand_left / SCALE
        exp_pts_r = expand_right / SCALE
        exp_pts_t = expand_top / SCALE
        exp_pts_b = expand_bottom / SCALE

        # Try expanding each side independently, revalidate text
        new_rect = fitz.Rect(best_rect)

        for side, exp in [("left", exp_pts_l), ("right", exp_pts_r),
                          ("top", exp_pts_t), ("bottom", exp_pts_b)]:
            if exp < 1:
                continue
            test = fitz.Rect(new_rect)
            if side == "left":
                test.x0 = max(0, test.x0 - exp)
            elif side == "right":
                test.x1 = min(page_rect.width, test.x1 + exp)
            elif side == "top":
                test.y0 = max(0, test.y0 - exp)
            elif side == "bottom":
                test.y1 = min(label_y - 1, test.y1 + exp)

            test_diag = _score_candidate(test, drawing_rects, text_blocks, page_rect)
            if test_diag["textRatio"] <= 0.06:
                new_rect = test

        if new_rect == best_rect:
            break

        best_rect = new_rect
        best_diag = _score_candidate(best_rect, drawing_rects, text_blocks, page_rect)
        best_diag["candidate"] = scored[0][1]["candidate"] + "+refine"

    # Final render
    left = max(0, int(best_rect.x0 * SCALE))
    top = max(0, int(best_rect.y0 * SCALE))
    right = min(img_w, int(best_rect.x1 * SCALE))
    bottom = min(img_h, int(best_rect.y1 * SCALE))

    if (right - left) < 60 or (bottom - top) < 60:
        return None, {}

    best_diag["questionBounded"] = bool(question_region)
    return img.crop((left, top, right, bottom)), best_diag


# ── Visual Crop: Tables ──────────────────────────────────────────

def _visual_crop_table(pdf_path: str, page_num: int, label_rect: fitz.Rect | None, img: Image.Image, bbox: dict | None) -> Image.Image | None:
    """Detect table region using find_tables() from PyMuPDF."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]

    try:
        tables = page.find_tables()
    except Exception:
        doc.close()
        return None

    if not tables or len(tables.tables) == 0:
        doc.close()
        return None

    ref_y = None
    if label_rect:
        ref_y = label_rect.y1
    elif bbox:
        ref_y = page.rect.height * bbox.get("y_pct", 50) / 100

    best_table = None
    best_dist = float("inf")

    for table in tables.tables:
        table_rect = fitz.Rect(table.bbox)
        dist = abs(table_rect.y0 - ref_y) if ref_y is not None else table_rect.y0
        if dist < best_dist:
            best_dist = dist
            best_table = table_rect

    doc.close()

    if not best_table:
        return None

    img_w, img_h = img.size
    left = max(0, int(best_table.x0 * SCALE) - VISUAL_PAD_PX)
    top = max(0, int(best_table.y0 * SCALE) - VISUAL_PAD_PX)
    right = min(img_w, int(best_table.x1 * SCALE) + VISUAL_PAD_PX)
    bottom = min(img_h, int(best_table.y1 * SCALE) + VISUAL_PAD_PX)

    if (right - left) < 40 or (bottom - top) < 40:
        return None

    return img.crop((left, top, right, bottom))


# ── Main Entry Point ─────────────────────────────────────────────

def crop_assets(output: dict, extraction: dict, output_dir: Path) -> dict:
    """Crop all assets producing both context and visual crops."""
    context_dir = output_dir / "assets" / "context"
    visual_dir = output_dir / "assets" / "visual"
    context_dir.mkdir(parents=True, exist_ok=True)
    visual_dir.mkdir(parents=True, exist_ok=True)
    legacy_dir = output_dir / "assets"

    page_images: dict[int, str] = {}
    for p in extraction.get("pages", []):
        page_images[p["page"]] = p["page_image_path"]

    pdf_path = output.get("_pdf_path") or extraction.get("_pdf_path")
    exam_id = output.get("exam_id", "")
    by_qid = {q.get("questionId"): q for q in output.get("questions", [])}
    by_page_number = {(q.get("sourcePage"), str(q.get("number"))): q for q in output.get("questions", [])}

    for asset in output.get("assets", []):
        page_num = asset.get("page")
        if not page_num or page_num not in page_images:
            asset["crops"] = {
                "context": {"status": "failed", "reason": "page_image_missing"},
                "visual": {"status": "failed", "reason": "page_image_missing"},
            }
            asset["crop"] = {"status": "failed", "reason": "page_image_missing"}
            continue

        if asset.get("type") == "embedded_image" and asset.get("url"):
            src_path = Path(asset["url"])
            fname = src_path.name
            # Copy to output assets dir so the API can serve it
            dst_path = legacy_dir / fname
            if src_path.exists() and not dst_path.exists():
                import shutil
                shutil.copy2(str(src_path), str(dst_path))
            crop_info = {
                "status": "success",
                "method": "embedded",
                "relativePath": f"assets/{fname}",
                "url": f"/api/exams/{exam_id}/assets/{fname}",
            }
            asset["crops"] = {"context": crop_info, "visual": crop_info}
            asset["crop"] = crop_info
            continue

        label = asset.get("label", "")
        aid = asset.get("id", "")
        is_table = "tabela" in (label or aid).lower() or "table" in (label or aid).lower() or asset.get("assetType") == "table"

        if not label:
            fig_match = re.match(r'figura_(\d+)', aid)
            tab_match = re.match(r'tabela', aid)
            if fig_match:
                label = f"Figura {fig_match.group(1)}"
            elif tab_match:
                label = "Tabela"

        try:
            img = Image.open(page_images[page_num])

            question_region = None
            near = str(asset.get("nearQuestion") or "").strip()
            if near:
                q_match = by_page_number.get((page_num, near))
                if q_match:
                    question_region = _region_to_rect(q_match.get("region"))
            if question_region is None:
                linked = asset.get("linkedQuestions") or []
                for qid in linked:
                    q_match = by_qid.get(qid)
                    if q_match and q_match.get("sourcePage") == page_num:
                        question_region = _region_to_rect(q_match.get("region"))
                        if question_region:
                            break

            label_rect = None
            if pdf_path and label:
                label_rect = _find_label_position(pdf_path, page_num, label)
                if not label_rect:
                    fig_match = re.match(r'[Ff]igura\s*(\d+)', label)
                    if fig_match:
                        label_rect = _find_label_regex(pdf_path, page_num, rf'[Ff]ig(?:ura)?\.?\s*{fig_match.group(1)}')
                    if not label_rect and is_table:
                        label_rect = _find_label_regex(pdf_path, page_num, r'[Tt]abela|TABELA')

            bbox = asset.get("bbox") or asset.get("bbox_estimate")
            crop_filename = f"{aid}.png"

            # Context Crop
            context_crop_info = _do_context_crop(
                img, label_rect, bbox, is_table, crop_filename, context_dir, legacy_dir, exam_id
            )

            # Visual Crop
            visual_crop_info = _do_visual_crop(
                pdf_path, page_num, label_rect, bbox, is_table, img, crop_filename, visual_dir, exam_id, question_region
            )

            asset["crops"] = {"context": context_crop_info, "visual": visual_crop_info}
            asset["crops"]["best"] = _choose_best_crop(visual_crop_info, context_crop_info)
            asset["crop"] = asset["crops"]["best"]

        except Exception as e:
            err = {"status": "failed", "reason": str(e)}
            asset["crops"] = {"context": err, "visual": err, "best": err}
            asset["crop"] = err

    # ── Source document crops (for History and similar) ────────────
    sources_dir = output_dir / "assets" / "sources"
    sources_dir.mkdir(parents=True, exist_ok=True)

    for source in output.get("sources", []):
        page_num = source.get("pageStart")
        if not page_num or page_num not in page_images:
            continue
        try:
            img = Image.open(page_images[page_num])
            source_id = source.get("sourceId", f"source_p{page_num}")
            full_filename = f"{source_id}_full.png"
            full_path = sources_dir / full_filename

            # Try precise crop by document label position in PDF
            doc_num_match = re.search(r'_(\d+)$', source_id)
            cropped = None
            method = "full_page_content"

            if pdf_path and doc_num_match:
                doc_num = int(doc_num_match.group(1))
                cropped = _crop_by_document_label(pdf_path, page_num, doc_num, img)
                if cropped:
                    method = "document_label_range"

            # Fallback: full page content area
            if not cropped:
                w, h = img.size
                margin_x = int(w * 0.03)
                margin_top = int(h * 0.05)
                margin_bottom = int(h * 0.05)
                cropped = img.crop((margin_x, margin_top, w - margin_x, h - margin_bottom))

            cropped.save(str(full_path))

            crop_info = {
                "status": "success",
                "method": method,
                "relativePath": f"assets/sources/{full_filename}",
                "url": f"/api/exams/{exam_id}/assets/sources/{full_filename}",
                "width": cropped.width,
                "height": cropped.height,
            }
            source.setdefault("crops", {})["full"] = crop_info
            source.setdefault("crops", {})["best"] = crop_info
        except Exception:
            pass

    return output


def _crop_by_document_label(pdf_path: str, page_num: int, doc_num: int, img: Image.Image):
    """Crop from 'Documento N' label to next document/question boundary."""
    doc = fitz.open(pdf_path)
    page = doc[page_num - 1]
    page_rect = page.rect

    # Find the label "Documento N" using block-level search for precision
    current_y = None
    blocks = page.get_text("dict")["blocks"]
    for block in blocks:
        if block.get("type") != 0:
            continue
        block_text = ""
        for line in block.get("lines", []):
            block_text += "".join(span["text"] for span in line.get("spans", []))
        if re.search(rf'\bDocumento\s+{doc_num}\b', block_text, re.IGNORECASE):
            current_y = block["bbox"][1]  # y0
            break

    # Fallback to search_for
    if current_y is None:
        found = page.search_for(f"Documento {doc_num}")
        if not found:
            doc.close()
            return None
        current_y = sorted(found, key=lambda r: r.y0)[0].y0

    # Find boundaries below current label
    boundaries = []

    # Next document label
    for next_num in range(doc_num + 1, doc_num + 6):
        for block in blocks:
            if block.get("type") != 0:
                continue
            block_text = ""
            for line in block.get("lines", []):
                block_text += "".join(span["text"] for span in line.get("spans", []))
            if re.search(rf'\bDocumento\s+{next_num}\b', block_text, re.IGNORECASE):
                by = block["bbox"][1]
                if by > current_y + 10:
                    boundaries.append(by)
                    break
        if boundaries:
            break

    # Question start pattern: "1. ", "2. " etc at start of block
    for block in blocks:
        if block.get("type") != 0:
            continue
        by = block["bbox"][1]
        if by <= current_y + 40:
            continue
        for line in block.get("lines", []):
            line_text = "".join(span["text"] for span in line.get("spans", []))
            if re.match(r'^\s*\d+\.\s+\S', line_text):
                boundaries.append(line["bbox"][1])
                break
        if len(boundaries) > 1:
            break

    # Page footer "Prova 623..."
    for block in blocks:
        if block.get("type") != 0:
            continue
        block_text = ""
        for line in block.get("lines", []):
            block_text += "".join(span["text"] for span in line.get("spans", []))
        if re.match(r'Prova\s+\d+', block_text.strip()) and block["bbox"][1] > current_y + 40:
            boundaries.append(block["bbox"][1])
            break

    y0 = max(0, current_y - 6)
    y1 = min(boundaries) - 8 if boundaries else page_rect.height * 0.94
    x0 = page_rect.width * 0.035
    x1 = page_rect.width * 0.965

    doc.close()

    left = int(x0 * SCALE)
    top = int(y0 * SCALE)
    right = int(x1 * SCALE)
    bottom = int(y1 * SCALE)

    if right - left < 100 or bottom - top < 80:
        return None

    return img.crop((left, top, right, bottom))


def _choose_best_crop(visual: dict, context: dict) -> dict:
    """Choose the best crop between visual and context.

    Policy: for quiz display, visual is always preferred over context because
    context includes surrounding question text. Only fall back to context when
    visual completely failed (no image produced).
    """
    v_ok = visual.get("status") == "success"
    c_ok = context.get("status") in ("success", "needs_review")

    # For quiz, prefer visual. Context has question text.
    if v_ok and visual.get("width", 0) >= 80 and visual.get("height", 0) >= 80:
        return visual

    if c_ok:
        return context

    return visual if visual.get("url") else context
    if v_ok:
        return visual
    return visual if visual.get("url") else context


def _do_context_crop(img, label_rect, bbox, is_table, filename, context_dir, legacy_dir, exam_id) -> dict:
    """Produce the context crop (question + figure area)."""
    if label_rect:
        cropped = _crop_context(img, label_rect, is_table)
        method = "label_position"
        status = "success"
    elif bbox:
        cropped = _crop_context_bbox(img, bbox, is_table)
        method = "bbox_fallback"
        status = "needs_review"
    else:
        return {"status": "failed", "reason": "no_bbox_and_label_not_found"}

    if cropped.width < 20 or cropped.height < 20:
        return {"status": "failed", "reason": "crop_too_small"}

    crop_path = context_dir / filename
    cropped.save(str(crop_path))
    legacy_path = legacy_dir / filename
    cropped.save(str(legacy_path))

    return {
        "status": status,
        "method": method,
        "relativePath": f"assets/context/{filename}",
        "url": f"/api/exams/{exam_id}/assets/context/{filename}",
        "width": cropped.width,
        "height": cropped.height,
    }


def _do_visual_crop(pdf_path, page_num, label_rect, bbox, is_table, img, filename, visual_dir, exam_id, question_region=None) -> dict:
    """Produce the visual crop using auto_candidate_score."""
    if not pdf_path:
        return {"status": "failed", "reason": "no_pdf_path"}

    cropped = None
    method = ""
    diagnostics = {}

    if is_table:
        cropped = _visual_crop_table(pdf_path, page_num, label_rect, img, bbox)
        method = "find_tables"
    elif label_rect:
        # Prefer the real PDF vector cluster near the caption.  This is more
        # stable across exams than a vision bbox because many official exam
        # figures are vector drawings, not embedded images.
        cropped, diagnostics = _visual_crop_cluster_near_label(pdf_path, page_num, label_rect, img)
        method = "cluster_drawings_near_label" if cropped is not None else ""

        if cropped is None:
            cropped, diagnostics = _visual_crop_figure(pdf_path, page_num, label_rect, img, question_region)
            method = "auto_candidate_score"

        # If the vector/label candidate is polluted with running text, try the
        # metadata / bbox_estimate candidate before falling back to context.
        if bbox and _auto_visual_is_polluted(diagnostics):
            try:
                doc = fitz.open(pdf_path)
                page_rect = doc[page_num - 1].rect
                doc.close()
            except Exception:
                page_rect = fitz.Rect(0, 0, img.width / SCALE, img.height / SCALE)

            # Only trust the bbox when it agrees with the found caption.
            if _bbox_is_consistent_with_label(bbox, label_rect, page_rect):
                bbox_crop = _crop_visual_bbox(img, bbox, is_table=False)
                if bbox_crop is not None:
                    cropped = bbox_crop
                    method = "bbox_estimate_visual"
                    diagnostics = {
                        "candidate": "bbox_estimate_visual",
                        "fallbackReason": "auto_candidate_polluted_with_text",
                        "previousAutoDiagnostics": diagnostics,
                    }
            else:
                diagnostics = dict(diagnostics or {})
                diagnostics["bboxRejected"] = "inconsistent_with_label_position"

    elif bbox:
        cropped = _crop_visual_bbox(img, bbox, is_table=is_table)
        method = "bbox_estimate_visual"
        diagnostics = {"candidate": "bbox_estimate_visual", "fallbackReason": "label_not_found"}

    if cropped is None:
        return {"status": "failed", "reason": "no_visual_elements_detected"}

    if cropped.width < 30 or cropped.height < 30:
        return {"status": "failed", "reason": "visual_crop_too_small"}

    crop_path = visual_dir / filename
    cropped.save(str(crop_path))

    # Tables from find_tables() are inherently precise
    if method == "find_tables":
        return {
            "status": "success",
            "method": method,
            "quality": "accepted",
            "score": 0.95,
            "relativePath": f"assets/visual/{filename}",
            "url": f"/api/exams/{exam_id}/assets/visual/{filename}",
            "width": cropped.width,
            "height": cropped.height,
        }

    # Compute content metrics from final crop
    content_box = _detect_ink_bbox(cropped)
    content_area_ratio = 0.0
    margins = {}
    if content_box:
        cx, cy, cw, ch = content_box
        margins = {
            "top": cy,
            "right": cropped.width - (cx + cw),
            "bottom": cropped.height - (cy + ch),
            "left": cx,
        }
        content_area_ratio = (cw * ch) / (cropped.width * cropped.height)
        diagnostics["contentBox"] = {"x": cx, "y": cy, "w": cw, "h": ch}
        diagnostics["margins"] = margins
        diagnostics["contentAreaRatio"] = round(content_area_ratio, 3)

    # Quality gate
    score = diagnostics.get("score", 0.5)
    text_ratio = diagnostics.get("textRatio", 0)
    edge_touch = diagnostics.get("edgeTouch", False)
    text_touches_edge = diagnostics.get("textTouchesEdge", False)
    drawing_cov = diagnostics.get("drawingCoverage", 0)

    # Minimum margin check (at least 6% of content dimension on each side)
    min_margin_ok = True
    if content_box:
        min_mx = max(12, int(content_box[2] * 0.06))
        min_my = max(12, int(content_box[3] * 0.06))
        if (margins.get("left", 0) < min_mx or margins.get("right", 0) < min_mx or
            margins.get("top", 0) < min_my or margins.get("bottom", 0) < min_my):
            min_margin_ok = False

    quality = "accepted"
    if not min_margin_ok:
        quality = "needs_review"
    if content_area_ratio > 0.82:
        quality = "needs_review"
    if text_ratio > 0.05:
        quality = "needs_review"
    if text_touches_edge and text_ratio > 0.03:
        quality = "needs_review"
    if score < 0.60:
        quality = "needs_review"

    result = {
        "status": "success",
        "method": method,
        "quality": quality,
        "score": score,
        "relativePath": f"assets/visual/{filename}",
        "url": f"/api/exams/{exam_id}/assets/visual/{filename}",
        "width": cropped.width,
        "height": cropped.height,
    }
    if diagnostics:
        result["diagnostics"] = diagnostics

    return result
