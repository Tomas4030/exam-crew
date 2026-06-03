"""Universal exam schema — works for any subject/discipline."""
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


# ── Question Types (generic, works for all subjects) ──────────────
class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
    MULTI_SELECT = "multi_select"
    OPEN_ANSWER = "open_answer"
    SHORT_ANSWER = "short_answer"
    ESSAY = "essay"
    TRUE_FALSE = "true_false"
    MATCHING = "matching"
    FILL_BLANK = "fill_blank"
    MULTI_BLANK_CHOICE = "multi_blank_choice"
    CALCULATION = "calculation"
    PROOF = "proof"
    CLASSIFICATION = "classification"
    ORDERING = "ordering"
    TABLE_ANALYSIS = "table_analysis"
    DOCUMENT_ANALYSIS = "document_analysis"
    IMAGE_ANALYSIS = "image_analysis"
    GROUP = "group"


# ── Asset Types (generic) ─────────────────────────────────────────
class AssetType(str, Enum):
    IMAGE = "image"
    DIAGRAM = "diagram"
    CHART = "chart"
    TABLE = "table"
    MAP = "map"
    TEXT_SOURCE = "text_source"
    DOCUMENT_EXCERPT = "document_excerpt"
    FORMULA_BLOCK = "formula_block"
    GRAPH = "graph"
    AUDIO = "audio"
    VIDEO = "video"
    CODE_BLOCK = "code_block"
    CHEMICAL_STRUCTURE = "chemical_structure"
    BIOLOGICAL_SCHEME = "biological_scheme"
    HISTORICAL_SOURCE = "historical_source"
    GEOMETRY_DIAGRAM = "geometry_diagram"


# ── Sub-models ────────────────────────────────────────────────────
class BBox(BaseModel):
    x: int
    y: int
    width: int
    height: int


class CropInfo(BaseModel):
    status: str = "pending"  # success | needs_review | failed
    method: Optional[str] = None
    relativePath: Optional[str] = None
    url: Optional[str] = None
    width: Optional[int] = None
    height: Optional[int] = None
    reason: Optional[str] = None


class AssetCrops(BaseModel):
    context: CropInfo = CropInfo()
    visual: CropInfo = CropInfo()


class SourceRef(BaseModel):
    """Reference from a question to a source group or specific child."""
    sourceId: str
    childId: Optional[str] = None
    mode: str = "full_group"  # full_group | specific_child


class Source(BaseModel):
    """A semantic document/source within a group (e.g. 'Documento 1' of Grupo II).

    Separate from physical assets: a Source is the logical entity,
    assets are the physical crops/images that represent it.
    """
    sourceId: str  # e.g. "grupo_ii_documento_1"
    groupId: str  # e.g. "grupo_ii"
    label: str  # e.g. "Documento 1"
    kind: str = "image"  # image_set | text_source | caricature | table | graph | map | mixed
    pageStart: int = 0
    pageEnd: Optional[int] = None
    description: str = ""
    children: list[str] = Field(default_factory=list)  # child sourceIds for composite docs
    assetRefs: list[str] = Field(default_factory=list)  # physical asset IDs


class Asset(BaseModel):
    id: str
    type: AssetType
    page: int
    description: str = ""
    bbox: Optional[BBox] = None
    url: Optional[str] = None
    linkedQuestions: list[str] = Field(default_factory=list)
    hallucination_risk: bool = False
    crops: Optional[AssetCrops] = None
    # Source grouping fields
    parentAssetId: Optional[str] = None  # If this is a child of a source_group


class SourceGroup(BaseModel):
    """A document/source group that contains multiple related assets."""
    id: str
    type: str = "source_group"
    sourceType: str = "image_set"  # image_set | text_document | map_set | mixed
    page: int
    label: str = ""
    description: str = ""
    children: list[str] = Field(default_factory=list)
    crops: Optional[AssetCrops] = None


class MathSpan(BaseModel):
    plain: str
    latex: str
    confidence: float = 0.9


class TextQuality(BaseModel):
    status: str = "pending"  # ok | needs_review | failed
    source: str = "pdf_text_raw"  # vision_latex_normalized | pdf_text_raw | manual_fallback
    hasCorruptChars: bool = False
    hasLatex: bool = False
    mathHeavy: bool = False
    requiresMathReview: bool = False
    checks: dict[str, bool] = Field(default_factory=dict)


class Option(BaseModel):
    letter: str
    text: str
    latex: Optional[str] = None


class Warning(BaseModel):
    type: str
    message: str
    questionId: Optional[str] = None
    assetId: Optional[str] = None


class Section(BaseModel):
    sectionId: str
    title: str
    page: int
    assets: list[str] = Field(default_factory=list, description="Asset IDs shared by this section")
    questions: list[str] = Field(default_factory=list, description="Question IDs in this section")


class Question(BaseModel):
    questionId: str
    number: str
    type: QuestionType
    sourcePage: int
    statement: str
    statementPlain: Optional[str] = None
    statementLatex: Optional[str] = None
    sourceTextRaw: Optional[str] = None
    mathSpans: list[MathSpan] = Field(default_factory=list)
    textQuality: Optional[TextQuality] = None
    options: list[Option] = []
    maxSelections: Optional[int] = None
    # Asset references
    imageRefs: list[str] = []
    tableRefs: list[str] = []
    assetRefs: list[str] = Field(default_factory=list, description="All asset IDs this question depends on")
    sourceRefs: list[SourceRef] = Field(default_factory=list, description="References to source groups/documents")
    # Structure
    groupId: Optional[str] = None  # e.g. "grupo_ii" — scopes this question
    group: Optional[str] = None  # e.g. "Grupo I", "Grupo II"
    displayNumber: Optional[str] = None  # e.g. "Grupo II, item 1"
    section: Optional[str] = None  # e.g. "Parte A", "Parte B"
    parentQuestion: Optional[str] = None
    subQuestions: list[str] = []
    sectionId: Optional[str] = None
    isGroup: bool = False
    # Quality
    confidence: float = 0.5
    needsHumanReview: bool = True
    warnings: list[Warning] = []
    visualDependency: bool = False
    # Content flags
    mathHeavy: bool = False
    hasGraph: bool = False
    hasDiagram: bool = False
    hasTable: bool = False
    # Grading (to be filled later)
    points: Optional[float] = None
    answer: Optional[str] = None
    solution: Optional[str] = None
    gradingCriteria: Optional[str] = None
    # Discipline-specific data
    disciplineData: dict[str, Any] = Field(default_factory=dict)


class QuestionStats(BaseModel):
    mainQuestions: int = 0
    answerableItems: int = 0
    jsonNodes: int = 0
    groups: int = 0
    subQuestions: int = 0


class ExamMetadata(BaseModel):
    title: Optional[str] = None
    subject: Optional[str] = None
    year: Optional[str] = None
    phase: Optional[str] = None
    examCode: Optional[str] = None
    duration_minutes: Optional[int] = None
    total_pages: int = 0
    total_points: Optional[float] = None
    stats: QuestionStats = QuestionStats()


class ExamOutput(BaseModel):
    exam_id: str
    processingStatus: str = "needs_review"  # completed | completed_with_warnings | needs_review | partial_failed
    missingPages: list[int] = []
    needsHumanReview: bool = True
    metadata: ExamMetadata = ExamMetadata()
    sections: list[Section] = []
    sources: list[Source] = Field(default_factory=list)
    sourceGroups: list[SourceGroup] = Field(default_factory=list)
    assets: list[Asset] = []
    questions: list[Question] = []
    warnings: list[Warning] = []
