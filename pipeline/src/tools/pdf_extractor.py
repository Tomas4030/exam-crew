"""PDF Extractor v3: text + layout blocks + tables + rendered pages + embedded images."""
import json
from pathlib import Path
from typing import Type

import fitz  # PyMuPDF
from crewai.tools import BaseTool
from pydantic import BaseModel, Field

from ..config import MIN_IMAGE_SIZE_PX


class PDFExtractorInput(BaseModel):
    pdf_path: str = Field(description="Path to the PDF file")
    output_dir: str = Field(description="Directory to save page renders and extracted images")


class PDFExtractorTool(BaseTool):
    name: str = "pdf_extractor"
    description: str = "Extracts text, layout blocks, tables, renders pages as PNG, and extracts embedded images"
    args_schema: Type[BaseModel] = PDFExtractorInput

    def _run(self, pdf_path: str, output_dir: str) -> str:
        doc = fitz.open(pdf_path)
        out = Path(output_dir)
        pages_dir = out / "pages"
        assets_dir = out / "assets"
        pages_dir.mkdir(parents=True, exist_ok=True)
        assets_dir.mkdir(parents=True, exist_ok=True)

        result = {
            "total_pages": len(doc),
            "pages": [],
            "assets": [],
        }

        for page_num in range(len(doc)):
            page = doc[page_num]

            # Extract text
            text = page.get_text("text")

            # Extract layout blocks with bboxes
            text_dict = page.get_text("dict")
            blocks = []
            for block in text_dict.get("blocks", []):
                if block.get("type") == 0:  # text block
                    block_text = ""
                    for line in block.get("lines", []):
                        block_text += "".join(span["text"] for span in line.get("spans", []))
                    if block_text.strip():
                        blocks.append({
                            "type": "text",
                            "bbox": list(block["bbox"]),
                            "text": block_text.strip(),
                        })

            # Detect tables
            tables = []
            try:
                found_tables = page.find_tables()
                for i, table in enumerate(found_tables.tables):
                    rows = table.extract()
                    if rows and len(rows) > 1:
                        tables.append({
                            "index": i,
                            "bbox": list(table.bbox),
                            "rows": rows,
                            "header": rows[0] if rows else [],
                        })
            except Exception:
                pass

            # Render full page as PNG (200 DPI)
            mat = fitz.Matrix(200/72, 200/72)
            pix = page.get_pixmap(matrix=mat)
            page_path = pages_dir / f"page_{page_num + 1}.png"
            pix.save(str(page_path))

            # Extract embedded images
            page_images = page.get_images(full=True)
            image_count = 0

            for img_idx, img in enumerate(page_images):
                xref = img[0]
                try:
                    pix_img = fitz.Pixmap(doc, xref)
                    if pix_img.width < MIN_IMAGE_SIZE_PX or pix_img.height < MIN_IMAGE_SIZE_PX:
                        continue
                    if pix_img.n - pix_img.alpha > 3:
                        pix_img = fitz.Pixmap(fitz.csRGB, pix_img)

                    img_rects = page.get_image_rects(xref)
                    if not img_rects:
                        continue

                    rect = img_rects[0]
                    asset_id = f"page{page_num + 1}_img{img_idx}"
                    asset_path = assets_dir / f"{asset_id}.png"
                    pix_img.save(str(asset_path))
                    image_count += 1

                    result["assets"].append({
                        "id": asset_id,
                        "path": str(asset_path),
                        "page": page_num + 1,
                        "bbox": {
                            "x": round(rect.x0),
                            "y": round(rect.y0),
                            "width": round(rect.width),
                            "height": round(rect.height),
                        },
                        "img_width": pix_img.width,
                        "img_height": pix_img.height,
                    })
                except Exception:
                    continue

            result["pages"].append({
                "page": page_num + 1,
                "text": text,
                "blocks": blocks,
                "tables": tables,
                "page_image_path": str(page_path),
                "has_images": image_count > 0,
                "image_count": image_count,
            })

        doc.close()
        return json.dumps(result, ensure_ascii=False)
