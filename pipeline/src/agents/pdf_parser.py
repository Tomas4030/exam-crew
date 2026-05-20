from crewai import Agent
from ..config import MODELS
from ..tools.pdf_extractor import PDFExtractorTool


def create_pdf_parser_agent() -> Agent:
    return Agent(
        role="Especialista em Extração de PDFs",
        goal="Extrair todo o conteúdo textual e imagens de PDFs de exames com máxima precisão",
        backstory="Sou especialista em processamento de documentos PDF, capaz de extrair texto mantendo a estrutura e posição original.",
        tools=[PDFExtractorTool()],
        llm=MODELS["text_extraction"],
        verbose=True,
    )
