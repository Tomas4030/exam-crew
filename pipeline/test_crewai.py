"""Testa CrewAI com um agente simples via OpenRouter."""
import os
from pathlib import Path
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")
os.environ["OPENAI_API_BASE"] = "https://openrouter.ai/api/v1"
os.environ["OPENAI_API_KEY"] = os.environ.get("OPENROUTER_API_KEY", "")

from crewai import Agent, Task, Crew


def test_crewai():
    agent = Agent(
        role="Assistente de Teste",
        goal="Responder a perguntas simples",
        backstory="Sou um agente de teste.",
        llm="google/gemini-2.0-flash-exp:free",
        verbose=True,
    )
    task = Task(
        description="Diz 'CrewAI funciona!' e nada mais.",
        expected_output="A frase 'CrewAI funciona!'",
        agent=agent,
    )
    crew = Crew(agents=[agent], tasks=[task], verbose=True)
    result = crew.kickoff()
    print(f"Result: {result}")
    print("✓ CrewAI + OpenRouter OK")


if __name__ == "__main__":
    test_crewai()
