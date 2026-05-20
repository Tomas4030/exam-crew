def match_images_by_position(images: list[dict], questions: list[dict]) -> list[dict]:
    """Associa imagens a perguntas por proximidade posicional (y-coordinate na mesma página)."""
    for img in images:
        img_page = img.get("page", 0)
        img_y = img.get("y", 0)
        best_q = None
        best_dist = float("inf")
        for q in questions:
            if q.get("page") == img_page:
                dist = abs(q.get("y", 0) - img_y)
                if dist < best_dist:
                    best_dist = dist
                    best_q = q
        if best_q:
            best_q.setdefault("images", []).append(img)
    return questions
