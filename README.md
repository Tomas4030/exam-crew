# ExamCrew — Documentação do Projeto

## O que é o ExamCrew?

O ExamCrew é um sistema que transforma PDFs de Exames Nacionais portugueses em informação organizada e estruturada. Imagina que tens um exame em PDF — com perguntas, imagens, gráficos e tabelas tudo misturado — e queres separar cada pergunta, associar cada imagem à pergunta certa, e ter tudo num formato que um computador consiga ler facilmente. É exatamente isso que o ExamCrew faz.

O resultado final é um ficheiro JSON (um formato de texto organizado que os computadores entendem bem) com todas as perguntas separadas, as imagens recortadas e associadas, as cotações de cada pergunta, e muito mais.

---

## Para que serve?

O objetivo é criar material de estudo interativo. Depois de o ExamCrew processar um exame, o JSON resultante pode ser usado por qualquer aplicação de quizzes para apresentar as perguntas aos alunos de forma interativa — com imagens, opções de resposta, e pontuações.

---

## Como está organizado o projeto?

O projeto tem duas grandes partes que trabalham em conjunto:

### 1. A Interface Web (Frontend)

É a parte visível — o que o utilizador vê no browser. Permite:
- **Fazer upload** de um PDF de exame
- **Ver o estado** do processamento (a processar, concluído, erro)
- **Consultar os resultados** quando o processamento termina
- **Descarregar** o resultado em formato ZIP

### 2. O Motor de Processamento (Pipeline)

É a parte "invisível" que faz o trabalho pesado. Quando um PDF é enviado, este motor:
- Lê o PDF página a página
- Usa inteligência artificial para entender o conteúdo
- Separa cada pergunta
- Identifica e recorta imagens
- Organiza tudo num ficheiro JSON estruturado

---

## Tecnologias Utilizadas

### Na Interface Web

| Tecnologia | O que faz | Explicação simples |
|---|---|---|
| **Next.js** | Framework web | É como o "esqueleto" do site. Gere as páginas, os formulários e a comunicação com o motor de processamento. |
| **React** | Biblioteca de interface | Permite criar os botões, listas e painéis que vês no browser. |
| **Tailwind CSS** | Estilos visuais | Define as cores, tamanhos e espaçamentos — tudo o que torna o site bonito. |
| **TypeScript** | Linguagem de programação | Uma versão melhorada de JavaScript que ajuda a evitar erros no código. |

### No Motor de Processamento

| Tecnologia | O que faz | Explicação simples |
|---|---|---|
| **Python** | Linguagem principal | A linguagem em que o motor está escrito. É muito usada em projetos de IA. |
| **PyMuPDF** | Leitor de PDFs | Abre o PDF e extrai o texto e as imagens de cada página, como se estivesse a "desmontar" o documento. |
| **OpenRouter + Qwen3-VL** | Modelo de IA com visão | Um modelo de inteligência artificial que consegue "ver" imagens e entender o que está escrito nelas. É o cérebro do sistema. |
| **Pillow** | Manipulação de imagens | Permite redimensionar, recortar e guardar imagens. |
| **Pydantic** | Validação de dados | Garante que o resultado final tem o formato correto — como um inspetor de qualidade. |

### Comunicação entre as duas partes

Quando fazes upload de um PDF no site, o Next.js guarda o ficheiro e lança o motor Python como um processo separado (como se abrisse um programa no computador). O motor trabalha em segundo plano e, quando termina, guarda o resultado num ficheiro. O site verifica periodicamente se o resultado já está pronto.

---

## O Workflow Completo — Passo a Passo

Vamos seguir o caminho de um PDF desde o momento em que é enviado até ao resultado final.

### Passo 1: Upload do PDF

O utilizador arrasta um ficheiro PDF para a zona de upload no site (ou clica para selecionar). O site envia o ficheiro para o servidor, que:
1. Guarda o PDF na pasta `data/uploads/`
2. Cria um registo do "trabalho" (job) com um identificador único
3. Inicia o motor de processamento em segundo plano
4. Responde imediatamente ao utilizador: "O teu exame está a ser processado"

O utilizador não precisa de esperar — pode fechar a página e voltar mais tarde.

### Passo 2: Extração do PDF

O motor abre o PDF com o PyMuPDF e faz duas coisas para cada página:

- **Renderiza a página como imagem** — Converte cada página numa imagem PNG de alta qualidade (200 DPI), como se tirasse uma "fotografia" da página. Isto é necessário porque o modelo de IA precisa de "ver" a página.

- **Extrai imagens embutidas** — Retira as imagens que estão dentro do PDF (gráficos, figuras geométricas, etc.) e guarda-as separadamente. Para cada imagem, regista a sua posição na página (onde está, que tamanho tem).

Resultado: Uma pasta com imagens de cada página + imagens individuais extraídas + o texto de cada página.

### Passo 3: Deteção da Disciplina

O motor lê o texto da primeira página (a capa do exame) e tenta perceber de que disciplina se trata. Procura palavras-chave como "Matemática A", "Física e Química", "Português", etc.

Isto é importante porque cada disciplina tem características diferentes:
- Matemática tem formulários (páginas com fórmulas que não são perguntas)
- Português tem textos de apoio (excertos literários)
- Biologia tem esquemas e classificações

### Passo 4: Filtragem de Páginas de Formulário

Se o exame for de Matemática ou Física, o motor identifica e **remove** as páginas que são apenas formulários (listas de fórmulas). Estas páginas não contêm perguntas, por isso não faz sentido processá-las com a IA — poupamos tempo e dinheiro.

Como deteta? Procura palavras como "formulário", "fórmulas", "tabela trigonométrica", e verifica se a página tem muitos símbolos matemáticos mas nenhum número de pergunta.

### Passo 5: Análise Visual com IA (o passo mais importante)

Aqui entra o modelo de inteligência artificial — o **Qwen3-VL** (um modelo com capacidade de "visão"). O processo tem duas fases:

#### Fase A: Pré-scan (reconhecimento rápido)

Para cada página, o motor envia a imagem da página ao modelo e pergunta:
- "Que tipo de página é esta?" (perguntas, cotações, instruções, capa?)
- "Que números de perguntas existem aqui?" (1, 2.1, 2.2, 3...)
- "Há figuras ou tabelas?" (Figura 1, Tabela...)

Isto é como um "olhar rápido" para saber o que esperar.

#### Fase B: Extração individual de cada pergunta

Para cada pergunta identificada no pré-scan, o motor envia novamente a imagem da página ao modelo, mas agora com um pedido específico:
- "Extrai APENAS a pergunta número X"
- "Diz-me o texto exato, o tipo de pergunta, as opções de resposta..."

Isto evita que o modelo se confunda ao tentar extrair tudo de uma vez. Uma pergunta de cada vez = mais precisão.

#### Fase C: Extração de figuras

Para cada figura identificada (Figura 1, Figura 2...), o motor pede ao modelo:
- "Descreve esta figura"
- "Estima onde está na página" (posição aproximada)
- "A que pergunta pertence?"

### Passo 6: Extração das Cotações

O motor procura a tabela de cotações (normalmente na última página do exame). Envia a imagem dessa página ao modelo e pede:
- "Extrai a tabela de cotações: para cada pergunta, quantos pontos vale?"

Se a IA não conseguir, tenta extrair do texto puro usando padrões (por exemplo: "1 ......... 12 pontos").

### Passo 7: Assemblagem (juntar tudo)

Agora o motor combina toda a informação recolhida:
- Cria um objeto para cada pergunta com: número, texto, tipo, opções, página, pontos
- Associa cada figura à pergunta que a menciona (se a pergunta diz "observa a Figura 1", liga-as)
- Cria grupos para perguntas com sub-alíneas (ex: 7.1, 7.2 pertencem ao grupo 7)
- Calcula um nível de confiança para cada pergunta (quão certo está o sistema de que extraiu bem)

### Passo 8: Extração de Dados de Tabelas

Se alguma pergunta referencia uma tabela, o motor volta a enviar a imagem da página ao modelo para extrair os dados da tabela (colunas e linhas) de forma estruturada.

### Passo 9: Normalização (correções automáticas)

O motor aplica correções que não precisam de IA — são regras lógicas:
- Se uma pergunta menciona "Figura 1" no texto, garante que a Figura 1 está associada a essa pergunta
- Se o enunciado diz "sem recorrer à calculadora", marca a pergunta como "calculadora não permitida"
- Remove "perguntas falsas" que são na verdade proposições (I, II, III, IV) dentro de outra pergunta
- Corrige flags como "tem gráfico" ou "tem diagrama" com base nas figuras realmente associadas

### Passo 10: Recorte de Imagens (Cropping)

Para cada figura ou tabela, o motor recorta duas versões da imagem:

#### Recorte de Contexto
Uma imagem mais ampla que mostra a figura no contexto da página (com algum texto à volta). Útil para perceber onde a figura aparece.

#### Recorte Visual
Uma imagem precisa apenas da figura, sem texto à volta. O motor usa um sistema inteligente:
1. Encontra a etiqueta "Figura X" no PDF
2. Procura os desenhos/linhas acima dessa etiqueta
3. Gera vários candidatos de recorte (mais apertado, mais largo...)
4. Pontua cada candidato (tem texto a mais? corta alguma parte do desenho? tem margens suficientes?)
5. Escolhe o melhor

Para tabelas, usa deteção automática de tabelas do PyMuPDF.

### Passo 11: Validação

O motor aplica mais de 12 regras de qualidade:
- Todos os IDs são únicos?
- As referências a figuras apontam para figuras que existem?
- Há perguntas em falta? (se temos Q1, Q2, Q4 mas não Q3, algo correu mal)
- As cotações estão atribuídas?
- Há figuras "fantasma" que nenhuma pergunta referencia? (possível alucinação da IA)

Com base nestas verificações, atribui um estado:
- **completed** — tudo OK
- **completed_with_warnings** — funciona mas tem avisos menores
- **needs_review** — precisa de revisão humana
- **partial_failed** — algumas páginas falharam

### Passo 12: Retry (segunda tentativa)

Se a validação detetou perguntas em falta, o motor tenta novamente:
1. Identifica que páginas devem conter as perguntas em falta
2. Envia essas páginas novamente ao modelo com um pedido mais específico
3. Se a IA falhar, tenta extrair do texto puro usando padrões de texto
4. Se encontrar as perguntas, adiciona-as ao resultado e re-valida tudo

### Passo 13: Guardar o Resultado

O resultado final é guardado como um ficheiro JSON em `data/output/{id_do_exame}.json`. As imagens recortadas ficam em `data/output/{id_do_exame}/assets/`.

O site deteta que o processamento terminou e mostra o resultado ao utilizador.

---

## Como funciona a leitura de imagens pelo modelo de IA?

O modelo Qwen3-VL é um modelo "multimodal" — significa que entende tanto texto como imagens. Quando o motor precisa que o modelo "veja" uma página:

1. **Converte a imagem para Base64** — É como traduzir a imagem para texto (uma sequência de letras e números que representa os pixels). Isto permite enviar a imagem pela internet.

2. **Envia ao OpenRouter** — O OpenRouter é um serviço que dá acesso a vários modelos de IA. O motor envia a imagem + uma instrução (prompt) como: "Olha para esta página e diz-me que perguntas vês."

3. **Recebe a resposta em JSON** — O modelo responde com texto estruturado que o motor consegue interpretar automaticamente.

4. **Pausa entre pedidos** — Para não sobrecarregar o serviço, o motor espera 2 segundos entre cada pedido.

---

## Como funciona a remoção/filtragem de imagens?

O sistema não "remove" imagens no sentido de as apagar. O que faz é **filtrar** — decidir quais são relevantes:

### Imagens demasiado pequenas
Quando extrai imagens do PDF, ignora qualquer imagem com menos de 50 pixels de largura ou altura. Estas são geralmente ícones decorativos ou artefactos do PDF que não têm valor para as perguntas.

### Páginas de formulário
Páginas inteiras são excluídas do processamento se forem identificadas como formulários. As imagens dessas páginas nunca chegam a ser analisadas pela IA.

### Figuras "fantasma" (alucinações)
Por vezes, a IA pode "inventar" uma figura que não existe realmente. O validador deteta isto: se uma figura não é referenciada por nenhuma pergunta e não tem ligação clara, é marcada como "risco de alucinação" e sinalizada para revisão humana.

### Imagens embutidas vs. figuras detetadas pela IA
O sistema distingue entre:
- **Imagens embutidas** — extraídas diretamente do PDF (são reais, nunca são alucinações)
- **Figuras detetadas pela IA** — identificadas pelo modelo ao "ver" a página (podem ser reais ou alucinações)

---

## Estrutura de Pastas

```
motor_ai_exames/
├── doc.md                          ← Este ficheiro
├── exam-extraction-system.md       ← Documentação técnica detalhada
└── exam-crew/                      ← O projeto principal
    ├── src/                        ← Código da interface web
    │   ├── app/                    ← Páginas e rotas da API
    │   ├── components/             ← Componentes visuais (botões, listas...)
    │   └── lib/                    ← Lógica partilhada (storage, tipos...)
    ├── pipeline/                   ← Motor de processamento Python
    │   └── src/
    │       ├── crew.py             ← Orquestrador principal
    │       ├── config.py           ← Configurações (chaves API, modelo...)
    │       ├── main.py             ← Ponto de entrada
    │       ├── tools/              ← Ferramentas (extrator PDF, visão IA)
    │       ├── schemas/            ← Definição do formato do resultado
    │       └── utils/              ← Utilitários (validador, normalizador, cropper...)
    └── data/                       ← Dados gerados
        ├── uploads/                ← PDFs enviados
        ├── extracted/              ← Páginas renderizadas + imagens extraídas
        └── output/                 ← Resultados finais (JSON + imagens recortadas)
```

---

## Diagrama do Fluxo

```
┌─────────────┐
│  Utilizador │
│  faz upload │
│  de um PDF  │
└──────┬──────┘
       │
       ▼
┌─────────────────┐
│   Interface Web  │  (Next.js)
│   Guarda o PDF   │
│   Cria um "job"  │
└──────┬──────────┘
       │ lança em segundo plano
       ▼
┌─────────────────────────────────────────────────────┐
│              Motor de Processamento (Python)          │
│                                                       │
│  1. Extrai texto + imagens do PDF (PyMuPDF)          │
│  2. Deteta a disciplina                               │
│  3. Filtra páginas de formulário                      │
│  4. Envia páginas ao modelo de IA (Qwen3-VL)        │
│     → Pré-scan: identifica perguntas                 │
│     → Extração: uma pergunta de cada vez             │
│     → Figuras: descrição e posição                   │
│  5. Extrai cotações                                   │
│  6. Junta tudo (assemblagem)                          │
│  7. Extrai dados de tabelas                           │
│  8. Normaliza (correções automáticas)                 │
│  9. Recorta imagens (context + visual)               │
│  10. Valida (12+ regras de qualidade)                │
│  11. Retry se houver perguntas em falta              │
│  12. Guarda JSON final                                │
└──────────────────────┬──────────────────────────────┘
                       │
                       ▼
┌─────────────────────────────┐
│  Resultado: JSON estruturado │
│  + imagens recortadas        │
│  em data/output/             │
└──────────────┬──────────────┘
               │
               ▼
┌─────────────────┐
│  Interface Web   │
│  mostra resultado│
│  ao utilizador   │
└─────────────────┘
```

---

## O que contém o resultado final?

O ficheiro JSON de saída contém:

- **Metadados** — Disciplina, ano, fase, número total de páginas e perguntas
- **Perguntas** — Cada uma com:
  - Número e tipo (escolha múltipla, resposta aberta, cálculo...)
  - Texto exato do enunciado
  - Opções de resposta (se aplicável)
  - Página de origem
  - Pontuação (cotação)
  - Referências a figuras/tabelas
  - Nível de confiança da extração
  - Flags: tem fórmulas? precisa de calculadora? tem gráfico?
- **Assets (recursos visuais)** — Figuras, tabelas, gráficos, cada um com:
  - Tipo e descrição
  - Posição na página
  - Imagens recortadas (contexto + visual)
  - Ligação às perguntas que os referenciam
- **Avisos** — Problemas detetados (perguntas em falta, referências partidas, etc.)
- **Estado do processamento** — Se correu tudo bem ou se precisa de revisão

---

## Disciplinas Suportadas

| Disciplina | Características especiais |
|---|---|
| Matemática A | Tem formulário, muitas fórmulas, perguntas de cálculo e demonstração |
| Física e Química | Tem formulário, fórmulas, perguntas de cálculo |
| Português | Tem excertos literários, perguntas de interpretação e composição |
| História A | Tem documentos históricos, análise de fontes |
| Biologia e Geologia | Tem esquemas biológicos, classificação, ordenação |

---

## Glossário

| Termo | Significado |
|---|---|
| **JSON** | Um formato de texto organizado em pares "chave: valor". Os computadores usam-no para trocar informação. |
| **API** | Uma "porta de entrada" que permite a programas comunicarem entre si. O site usa APIs para falar com o motor. |
| **Pipeline** | Uma sequência de passos que são executados um após o outro, como uma linha de montagem. |
| **Modelo de IA** | Um programa treinado com milhões de exemplos que consegue "entender" texto e imagens. |
| **OpenRouter** | Um serviço online que dá acesso a vários modelos de IA através de uma única ligação. |
| **Prompt** | A instrução/pergunta que enviamos ao modelo de IA. Quanto melhor o prompt, melhor a resposta. |
| **Crop/Recorte** | Cortar uma parte específica de uma imagem maior. |
| **Bbox (Bounding Box)** | Um retângulo que define a posição e tamanho de algo numa página (x, y, largura, altura). |
| **Base64** | Uma forma de representar dados binários (como imagens) usando apenas letras e números. |
| **DPI** | "Dots Per Inch" — quanto maior, mais detalhada é a imagem. 200 DPI é boa qualidade para leitura. |
| **Alucinação** | Quando a IA "inventa" informação que não existe realmente no documento. |
| **Token** | A unidade de texto que a IA processa. Uma palavra tem geralmente 1-3 tokens. |
