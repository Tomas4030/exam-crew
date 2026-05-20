import sys
from pathlib import Path

# Import config first — loads .env and sets up API
from .config import OPENROUTER_API_KEY
from .crew import ExamProcessingCrew
from .utils.progress import report_progress


def main():
    if len(sys.argv) < 3:
        print("Usage: python -m src.main <pdf_path> <exam_id>")
        sys.exit(1)

    if not OPENROUTER_API_KEY:
        print("Error: OPENROUTER_API_KEY not set in .env")
        sys.exit(1)

    pdf_path = sys.argv[1]
    exam_id = sys.argv[2]

    if not Path(pdf_path).exists():
        print(f"Error: PDF not found: {pdf_path}")
        sys.exit(1)

    try:
        crew = ExamProcessingCrew(pdf_path, exam_id)
        crew.run()
    except Exception as e:
        report_progress("error", str(e))
        sys.exit(1)


if __name__ == "__main__":
    main()
