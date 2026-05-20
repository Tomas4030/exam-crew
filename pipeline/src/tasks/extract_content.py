from crewai import Task


def create_extraction_task(pdf_path: str, output_dir: str, agent) -> Task:
    return Task(
        description=f"Extrai todo o conteúdo do PDF em '{pdf_path}'. Guarda imagens em '{output_dir}'. Usa a ferramenta pdf_extractor com pdf_path='{pdf_path}' e output_dir='{output_dir}'.",
        expected_output="JSON com pages (text_blocks com texto e posição), images (com path e bbox), total_pages e total_images.",
        agent=agent,
    )
