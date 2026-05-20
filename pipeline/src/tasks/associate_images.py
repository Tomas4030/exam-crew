from crewai import Task


def create_association_task(agent) -> Task:
    return Task(
        description="Para cada imagem extraída, determina a que pergunta pertence. Usa a posição (bbox) e o conteúdo visual para fazer a associação. Usa a ferramenta vision_analysis quando necessário.",
        expected_output="JSON array com associações: {image_id, path, question_number, description}",
        agent=agent,
    )
