from crewai import Agent
from ..config import MODELS


def create_question_splitter_agent() -> Agent:
    return Agent(
        role="Especialista em Análise de Exames Portugueses",
        goal="Identificar e separar cada pergunta do exame, incluindo opções de resposta",
        backstory="Sou especialista em análise de exames do sistema educativo português. Consigo identificar padrões de numeração e estrutura de perguntas.",
        llm=MODELS["text_extraction"],
        verbose=True,
    )
