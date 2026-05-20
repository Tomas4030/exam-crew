from crewai import Agent
from ..config import MODELS


def create_structurer_agent() -> Agent:
    return Agent(
        role="Estruturador de JSON Final",
        goal="Estruturar todos os dados extraídos num JSON válido e completo seguindo o schema definido",
        backstory="Sou meticuloso na organização de dados. Garanto que o output final está correto, completo e válido contra o schema Pydantic.",
        llm=MODELS["structuring"],
        verbose=True,
    )
