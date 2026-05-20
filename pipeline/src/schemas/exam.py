"""Universal exam schema — works for any subject/discipline."""
from enum import Enum
from typing import Optional, Any
from pydantic import BaseModel, Field


# ── Question Types (generic, works for all subjects) ──────────────
class QuestionType(str, Enum):
    MULTIPLE_CHOICE = "multiple_choice"
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


class Option(BaseModel):
    letter: str
    text: str


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
    options: list[Option] = []
    # Asset references
    imageRefs: list[str] = []
    tableRefs: list[str] = []
    assetRefs: list[str] = Field(default_factory=list, description="All asset IDs this question depends on")
    # Structure
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
    assets: list[Asset] = []
    questions: list[Question] = []
    warnings: list[Warning] = []
