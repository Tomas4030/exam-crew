from crewai import Agent
from ..config import MODELS
from ..tools.vision_tool import VisionAnalysisTool


def create_image_associator_agent() -> Agent:
    return Agent(
        role="Especialista em Associação de Imagens",
        goal="Associar cada imagem extraída à pergunta correspondente do exame",
        backstory="Sou especialista em análise visual e consigo determinar a que pergunta cada imagem se refere com base no conteúdo e posição.",
        tools=[VisionAnalysisTool()],
        llm=MODELS["vision"],
        verbose=True,
    )
