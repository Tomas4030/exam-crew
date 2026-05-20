from crewai import Task


def create_split_task(agent) -> Task:
    return Task(
        description="Analisa o texto extraído do PDF e separa cada pergunta. Identifica: número da pergunta, texto, tipo (multiple_choice/true_false/open/matching), opções de resposta (letra e texto), e página.",
        expected_output="JSON array com objetos: {number, text, type, options: [{letter, text}], page}",
        agent=agent,
    )
