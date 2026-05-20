from crewai import Task


def create_structure_task(agent) -> Task:
    return Task(
        description="Combina os resultados anteriores (perguntas separadas + associações de imagens) num JSON final. O JSON deve seguir o schema ExamOutput com: exam_id, metadata (title, subject, year, total_pages, total_questions), questions (number, text, type, options, images, page). Valida que está completo e correto.",
        expected_output="JSON válido seguindo o schema ExamOutput com todas as perguntas e imagens associadas.",
        agent=agent,
    )
