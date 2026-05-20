"""Testa PDFExtractorTool com um PDF."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from src.tools.pdf_extractor import PDFExtractorTool


def test_extraction(pdf_path: str):
    tool = PDFExtractorTool()
    output_dir = str(Path(__file__).parent.parent / "data" / "extracted" / "test")
    result = tool._run(pdf_path=pdf_path, output_dir=output_dir)
    data = json.loads(result)
    print(f"Pages: {data['total_pages']}")
    print(f"Images: {data['total_images']}")
    print(f"Text blocks (page 0): {len(data['pages'][0]['text_blocks']) if data['pages'] else 0}")
    print("✓ PDF extraction OK")
    return data


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python test_extraction.py <pdf_path>")
        sys.exit(1)
    test_extraction(sys.argv[1])
