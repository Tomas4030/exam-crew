"use client";

import { useState, useEffect } from "react";
import { useParams } from "next/navigation";
import Link from "next/link";
import MathJaxProvider from "@/components/MathJaxProvider";
import MathText from "@/components/MathText";

interface Option {
  letter: string;
  text: string;
  latex?: string;
  imageUrl?: string;
  imageAssetId?: string;
}
interface CropInfo {
  status: string;
  url?: string;
  quality?: string;
  relativePath?: string;
}
interface Asset {
  id: string;
  type: string;
  page: number;
  description?: string;
  crops?: {
    context?: CropInfo;
    visual?: CropInfo;
    full?: CropInfo;
    best?: CropInfo;
  };
  crop?: CropInfo;
}
interface Source {
  sourceId: string;
  groupId?: string;
  label?: string;
  kind?: string;
  pageStart?: number;
  crops?: {
    best?: CropInfo;
    full?: CropInfo;
    visual?: CropInfo;
    context?: CropInfo;
    document?: CropInfo;
  };
  assetRefs?: string[];
}
interface Blank {
  number: string;
  options: { letter: string; text: string; latex?: string }[];
}
interface Question {
  questionId: string;
  number: string;
  type: string;
  statement: string;
  statementLatex?: string;
  statementPlain?: string;
  statementFormatted?: string;
  statementLatexFormatted?: string;
  statementPlainFormatted?: string;
  rawText?: string;
  mathSpans?: { plain: string; latex: string; confidence?: number }[];
  textQuality?: { status?: string };
  options?: Option[];
  blanks?: Blank[] | null;
  group?: string;
  groupId?: string;
  displayNumber?: string;
  imageRefs?: string[];
  tableRefs?: string[];
  assetRefs?: string[];
  sourceRefs?: { sourceId: string; childId?: string; mode: string }[];
  media?: { type: string; url: string; sourceId?: string; label?: string }[];
  points?: number;
  sourcePage?: number;
  parentQuestion?: string | null;
  isGroup?: boolean;
  hasOptionImages?: boolean;
  matchColumns?: {
    left: { key: string; text: string }[];
    right: { key: string; text: string }[];
  };
}
interface ExamData {
  exam_id: string;
  metadata: {
    title?: string;
    subject?: string;
    year?: string;
    phase?: string;
    stats?: { answerableItems?: number };
  };
  questions: Question[];
  assets: Asset[];
  sources?: Source[];
  sourceGroups?: {
    id: string;
    children: string[];
    crops?: { context?: CropInfo };
  }[];
}

function orderQuestionKey(q: Question): string {
  const page = String(q.sourcePage ?? 999).padStart(4, "0");
  const num = String(q.number || "")
    .split(".")
    .map((part) => String(parseInt(part, 10) || 999).padStart(4, "0"))
    .join(".");
  return `${page}.${num}`;
}

function isTableAsset(asset?: Asset): boolean {
  if (!asset) return false;
  const id = String(asset.id || "").toLowerCase();
  const type = String(asset.type || "").toLowerCase();
  return id.includes("tabela") || type.includes("table");
}

function normalizeChemistryText(text: string): string {
  let t = text;

  // OCR / PDF extraction cleanup for common FQ notation.
  t = t.replace(/H\s*2\b/g, "H₂");
  t = t.replace(/I\s*2\b/g, "I₂");
  t = t.replace(/\bt0\b/g, "t₀");
  t = t.replace(/\bt1\b/g, "t₁");
  t = t.replace(/\bt2\b/g, "t₂");
  t = t.replace(/\bt3\b/g, "t₃");
  t = t.replace(/\bQc\b/g, "Qᶜ");
  t = t.replace(/\bKc\b/g, "Kᶜ");

  // Broken vertical fraction sometimes extracted as: "quociente H @ entre ...".
  t = t.replace(
    /quociente\s+H\s*@\s*entre/gi,
    "quociente \\(\\frac{[HI]^2}{[H_2][I_2]}\\) entre",
  );
  t = t.replace(
    /ao\s+quociente\s+H\s*@\s*entre/gi,
    "ao quociente \\(\\frac{[HI]^2}{[H_2][I_2]}\\) entre",
  );

  // Remove isolated extraction garbage while preserving normal Portuguese text.
  t = t.replace(/^\s*@\s*$/gm, "");
  t = t.replace(/\n{3,}/g, "\n\n");

  return t.trim();
}

function removeMatchingRawBlock(text: string): string {
  const idx = text.search(/\bCOLUNA\s+I\b/i);
  if (idx >= 0) return text.slice(0, idx).trim();
  return text.trim();
}

function removeMultiBlankAnswerBank(text: string): string {
  let t = text;

  // Remove the raw answer bank from recovered PDF text. The selects render these data.
  const bankStartPatterns = [
    /\n\s*a\)\s*\n\s*b\)\s*\n\s*c\)\s*\n\s*d\)?/i,
    /\n\s*a\)\s*\n\s*b\)\s*\n\s*c\)/i,
    /\n\s*1\.\s*(adi[cç][aã]o|remo[cç][aã]o|superior|igual|inferior)\b/i,
  ];

  for (const pat of bankStartPatterns) {
    const m = pat.exec(t);
    if (m && m.index > 80) {
      t = t.slice(0, m.index).trim();
      break;
    }
  }

  return t.trim();
}

function makeInlineBlanksPretty(text: string): string {
  let t = text;

  // Remove accidental duplicated blank markers from previous preview cleanup.
  t = t.replace(
    /_{2,}\s+_{2,}\s+([a-d]\))\s+_{2,}\s+_{2,}/gi,
    "_____ $1 _____",
  );

  // Keep the markers visible, but make them look like the blanks in the original exam.
  const blank = "_____";
  t = t.replace(
    /\bpela\s+(?:_{2,}\s*)?a\)(?:\s*_{2,})?\s+no\s+instante/gi,
    `pela ${blank} a) ${blank} no instante`,
  );
  t = t.replace(
    /\bé\s+(?:_{2,}\s*)?b\)(?:\s*_{2,})?\s+à\s+velocidade/gi,
    `é ${blank} b) ${blank} à velocidade`,
  );
  t = t.replace(
    /\bé\s+(?:_{2,}\s*)?c\)(?:\s*_{2,})?\s+à\s+constante/gi,
    `é ${blank} c) ${blank} à constante`,
  );
  t = t.replace(
    /\bé\s+(?:_{2,}\s*)?d\)(?:\s*_{2,})?\s+ao\s+quociente/gi,
    `é ${blank} d) ${blank} ao quociente`,
  );

  // Safety for markers that survived without blanks. Avoid touching answer-bank lines,
  // because those are removed before this function runs.
  t = t.replace(
    /([^_\n])\s+([a-d]\))\s+([^_\n])/gi,
    (_m, before, marker, after) => {
      return `${before} ${blank} ${marker} ${blank} ${after}`;
    },
  );

  return t.replace(/\n{3,}/g, "\n\n").trim();
}

function formatMultiBlankStatement(text: string): string {
  let t = text;

  // In the preview the figure itself is already rendered above the question.
  // For items like 9.3, start at the actual instruction instead of repeating
  // the figure description and caption extracted from the PDF.
  const instruction = t.search(/Complete\s+o\s+texto\s+seguinte/i);
  if (instruction > 0) t = t.slice(instruction).trim();

  t = removeMultiBlankAnswerBank(t);
  t = normalizeChemistryText(t);
  t = makeInlineBlanksPretty(t);

  const rawLines = t
    .split(/\r?\n/)
    .map((line) => line.replace(/\s+/g, " ").trim())
    .filter(Boolean)
    .filter((line) => !/^Figura\s+\d+$/i.test(line));

  const paragraphs: string[] = [];
  let current = "";

  const flush = () => {
    if (current.trim()) paragraphs.push(current.trim());
    current = "";
  };

  for (const line of rawLines) {
    const startsMainInstruction = /^(Complete|Escreva|Atendendo)\b/i.test(line);
    const startsBullet = /^[-–‒]\s*/.test(line);

    if (startsMainInstruction) {
      flush();
      current = line;
      flush();
      continue;
    }

    if (startsBullet) {
      flush();
      current = line.replace(/^[-–‒]\s*/, "– ");
      continue;
    }

    if (current) {
      current += " " + line;
    } else {
      current = line;
    }
  }
  flush();

  // Put a blank line before the block that starts with “Atendendo…”, matching
  // the visual rhythm of the original exam page.
  return paragraphs
    .join("\n")
    .replace(/\n(Atendendo\s+ao\s+gr[aá]fico)/i, "\n\n$1")
    .replace(/\n{3,}/g, "\n\n")
    .trim();
}

function cleanOptionText(text?: string): string {
  const t = (text || "").trim();
  if (!t) return "";
  // Descriptions generated by the model for image options should not be shown.
  if (
    /^\(?[A-D]\)?\s*\[?\s*(gr[aá]fico|grafico|diagrama|curva|esbo[cç]o)/i.test(
      t,
    )
  )
    return "";
  if (/^(gr[aá]fico|grafico|diagrama|curva|esbo[cç]o)\s+com\s+/i.test(t))
    return "";
  return t;
}

export default function PreviewPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ExamData | null>(null);
  const [selected, setSelected] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch(`/api/exams/${id}/result`)
      .then((r) => r.json())
      .then(setData)
      .catch(() => {});
  }, [id]);

  if (!data) {
    return (
      <div className="min-h-screen flex items-center justify-center text-slate-600">
        A carregar...
      </div>
    );
  }

  const isAnswerable = (q: Question) => !q.isGroup && q.type !== "group";

  const questions = data.questions
    .filter(
      (q) =>
        isAnswerable(q) &&
        (q.statement ||
          (q.options && q.options.length > 0) ||
          q.blanks?.length ||
          q.matchColumns),
    )
    .sort((a, b) =>
      orderQuestionKey(a).localeCompare(orderQuestionKey(b), undefined, {
        numeric: true,
      }),
    );

  const current = questions[selected];
  if (!current) return <div className="p-8">Sem perguntas.</div>;

  const getAncestors = (q: Question): Question[] => {
    const ancestors: Question[] = [];
    let parentId = q.parentQuestion;
    while (parentId) {
      const parent = data.questions.find((p) => p.questionId === parentId);
      if (!parent) break;
      ancestors.unshift(parent);
      parentId = parent.parentQuestion;
    }
    return ancestors;
  };

  const getVisualUrl = (asset?: Asset): string | null => {
    if (!asset || isTableAsset(asset)) return null;
    const urls = [
      asset.crops?.visual?.url,
      asset.crop?.url,
      asset.crops?.best?.url,
    ];
    for (const url of urls) {
      if (url && url.includes("/assets/visual/")) return url;
    }
    return null;
  };

  const questionMentionsFigure = (q: Question, asset: Asset): boolean => {
    const idMatch = String(asset.id || "").match(/figura_(\d+)/i);
    if (!idMatch) return true;
    const figNum = idMatch[1];
    const text = `${q.statement || ""}\n${q.statementPlain || ""}\n${q.rawText || ""}`;
    return new RegExp(`Figura\\s+${figNum}\\b`, "i").test(text);
  };

  const getAllImages = (q: Question): string[] => {
    const urls: string[] = [];
    const currentPage = q.sourcePage ?? 0;
    const add = (url?: string | null) => {
      if (url && url.includes("/assets/") && !urls.includes(url))
        urls.push(url);
    };

    const collectFromQuestion = (target: Question, inherited: boolean) => {
      const refs = [...(target.imageRefs || []), ...(target.assetRefs || [])];
      for (const refId of refs) {
        const asset = data.assets.find((a) => a.id === refId);
        if (!asset || isTableAsset(asset)) continue;

        // Important: avoid Q9.1/Q9.2 inheriting Figura 6 from page 13.
        // For inherited context, only show the figure if it is on the current question page.
        if (
          inherited &&
          currentPage &&
          asset.page &&
          asset.page !== currentPage
        )
          continue;

        // For direct refs, be strict too: figures from other pages are often dirty associations.
        if (
          !inherited &&
          currentPage &&
          asset.page &&
          asset.page !== currentPage
        )
          continue;

        // If the asset is a figura_N, the target text should actually mention that figure.
        if (
          !questionMentionsFigure(target, asset) &&
          !questionMentionsFigure(q, asset)
        )
          continue;

        add(getVisualUrl(asset));
      }

      if (!inherited && target.media?.length) {
        for (const m of target.media) {
          if (m.url.includes("/assets/")) add(m.url);
        }
      }

      if (!inherited && target.sourceRefs?.length) {
        for (const ref of target.sourceRefs) {
          const src = data.sources?.find((s) => s.sourceId === ref.sourceId);
          if (!src) continue;

          // Specific child: show the internal asset image
          if (ref.childId && src.assetRefs?.length) {
            const letter = String(ref.childId).split("_").pop()?.toLowerCase() || "";
            const idx = letter.charCodeAt(0) - "a".charCodeAt(0);
            if (idx >= 0 && idx < src.assetRefs.length) {
              const asset = data.assets.find((a) => a.id === src.assetRefs![idx]);
              const url = asset?.crops?.best?.url || asset?.crop?.url || asset?.crops?.visual?.url;
              if (url && url.includes("/assets/")) { add(url); continue; }
            }
          }

          // Full source document
          const sourceUrl =
            (src.crops as Record<string, any>)?.best?.url ||
            (src.crops as Record<string, any>)?.full?.url ||
            (src.crops as Record<string, any>)?.document?.url ||
            (src.crops as Record<string, any>)?.visual?.url;
          if (sourceUrl && sourceUrl.includes("/assets/")) add(sourceUrl);
        }
      }
    };

    for (const ancestor of getAncestors(q)) collectFromQuestion(ancestor, true);
    collectFromQuestion(q, false);
    return urls;
  };

  const parseMatchingColumns = (q: Question) => {
    if (q.matchColumns?.left?.length && q.matchColumns?.right?.length)
      return q.matchColumns;

    const text = `${q.statement || ""}\n${q.statementPlain || ""}\n${q.rawText || ""}`;
    if (!/COLUNA\s+I/i.test(text) || !/COLUNA\s+II/i.test(text)) return null;

    const leftMatches = [...text.matchAll(/\(([a-e])\)\s*([^\n(]+)/gi)];
    const rightMatches = [...text.matchAll(/\((\d+)\)\s*([^\n(]+)/g)];

    const uniq = (items: { key: string; text: string }[]) => {
      const seen = new Set<string>();
      return items.filter((item) => {
        if (!item.key || seen.has(item.key)) return false;
        seen.add(item.key);
        return true;
      });
    };

    const left = uniq(
      leftMatches.map((m) => ({
        key: m[1],
        text: normalizeChemistryText(m[2].replace(/\u0007/g, "").trim()),
      })),
    );
    const right = uniq(
      rightMatches.map((m) => ({
        key: m[1],
        text: normalizeChemistryText(m[2].replace(/\u0007/g, "").trim()),
      })),
    );

    return left.length && right.length ? { left, right } : null;
  };

  const currentMatching = parseMatchingColumns(current);

  function decodeEscapedPreviewText(text: string): string {
    if (!text) return "";
    return text
      .replace(/\\n/g, "\n")
      .replace(/\\t/g, "\t")
      .replace(/\\u2022/g, "•")
      .replace(/\\u00a0/g, " ")
      .replace(/\u0007/g, "")
      .replace(/\[\d+;\d+u/g, "")
      .replace(/\n{3,}/g, "\n\n")
      .trim();
  }

  const getRenderableStatement = (q: Question): string => {
    const latex = q.statementLatexFormatted || q.statementLatex || "";
    const badLatex =
      latex.includes("�") ||
      latex.includes("\\begin{itemize}") ||
      latex.includes("\\n") ||
      latex.includes("\\u2022") ||
      latex.includes("\\u00") ||
      q.textQuality?.status === "corrupt";
    if (badLatex)
      return (
        q.statementPlainFormatted ||
        q.statementFormatted ||
        q.statementPlain ||
        q.statement
      );
    return (
      latex ||
      q.statementPlainFormatted ||
      q.statementFormatted ||
      q.statementPlain ||
      q.statement
    );
  };

  const getPreviewStatement = (q: Question): string => {
    let text = decodeEscapedPreviewText(getRenderableStatement(q));

    const matching = parseMatchingColumns(q);
    if (matching) {
      text = removeMatchingRawBlock(text);
    }

    if (q.type === "multi_blank_choice" && q.blanks?.length) {
      return formatMultiBlankStatement(text);
    }

    text = normalizeChemistryText(text);
    return text.replace(/\n{3,}/g, "\n\n").trim();
  };

  const cleanParentContext = (a: Question): string => {
    let text =
      (a as any).rawText &&
      (a as any).rawText.length < (a.statement || "").length
        ? (a as any).rawText
        : getRenderableStatement(a);

    text = normalizeChemistryText(text || "");

    // Group parents often swallow child questions. Cut at first child marker or known child text.
    const children = data.questions
      .filter((q) => q.parentQuestion === a.questionId)
      .sort((x, y) =>
        String(x.number).localeCompare(String(y.number), undefined, {
          numeric: true,
        }),
      );

    const cuts: number[] = [];
    for (const child of children) {
      const num = String(child.number || "").replace(/\./g, "\\.");
      const m = new RegExp(`\\n\\s*${num}\\.?\\s+`).exec(text);
      if (m && m.index > 20) cuts.push(m.index);

      const childStart = (child.statement || "")
        .split(/\s+/)
        .slice(0, 8)
        .join(" ");
      if (childStart.length > 24) {
        const idx = text.toLowerCase().indexOf(childStart.toLowerCase());
        if (idx > 20) cuts.push(idx);
      }
    }

    // Specific safety for Q9 parent in FQ: stop before the association / multiblank blocks.
    const noisyStarts = [
      /\n\s*Associe\s+cada\s+uma\s+das\s+mol[eé]culas/i,
      /\n\s*A\s+Figura\s+6\s+apresenta\s+o\s+esbo[cç]o/i,
      /\n\s*Complete\s+o\s+texto\s+seguinte/i,
      /\n\s*COLUNA\s+I/i,
    ];
    for (const pat of noisyStarts) {
      const m = pat.exec(text);
      if (m && m.index > 20) cuts.push(m.index);
    }

    if (cuts.length) text = text.slice(0, Math.min(...cuts)).trim();
    return text.replace(/\n{3,}/g, "\n\n").trim();
  };

  const ancestorContext = getAncestors(current)
    .map(cleanParentContext)
    .filter(Boolean)
    .join("\n\n");

  const images = getAllImages(current);
  const previewStatement = getPreviewStatement(current);

  return (
    <MathJaxProvider>
      <div className="h-screen flex flex-col bg-slate-50">
        <header className="bg-white border-b px-4 py-3 flex items-center gap-4 shrink-0">
          <Link
            href={`/exams/${id}`}
            className="text-blue-600 hover:underline text-sm"
          >
            &larr; Voltar
          </Link>
          <h1 className="font-semibold text-lg truncate text-slate-900">
            {data.metadata.title ||
              `${data.metadata.subject || "Exame"} ${data.metadata.year || ""}`}
          </h1>
          <span className="ml-auto text-sm text-slate-500">
            {selected + 1} / {questions.length}
          </span>
        </header>

        <div className="flex flex-1 overflow-hidden">
          <aside className="w-56 bg-white border-r overflow-y-auto shrink-0 p-3">
            {(() => {
              const groups = [
                ...new Set(questions.map((q) => q.group || "Perguntas")),
              ];
              return groups.map((group) => {
                const groupQs = questions.filter(
                  (q) => (q.group || "Perguntas") === group,
                );
                return (
                  <div key={group} className="mb-4">
                    <div className="text-xs font-bold text-slate-900 uppercase tracking-wide mb-1.5 px-1">
                      {group}
                    </div>
                    <div className="grid grid-cols-4 gap-1.5">
                      {groupQs.map((q) => {
                        const i = questions.indexOf(q);
                        return (
                          <button
                            key={q.questionId}
                            onClick={() => setSelected(i)}
                            className={`w-full aspect-square rounded text-xs font-bold flex items-center justify-center border transition-colors
                              ${i === selected ? "bg-blue-600 text-white border-blue-600" : answers[q.questionId] ? "bg-blue-50 text-blue-800 border-blue-300" : "bg-white text-slate-900 border-slate-300 hover:border-blue-400"}`}
                          >
                            {q.number}
                          </button>
                        );
                      })}
                    </div>
                  </div>
                );
              });
            })()}
          </aside>

          <main className="flex-1 overflow-y-auto p-6">
            <div className="max-w-2xl mx-auto space-y-5">
              <div className="flex items-baseline gap-2">
                <span className="bg-blue-100 text-blue-800 text-sm font-bold px-2.5 py-0.5 rounded">
                  {current.displayNumber || current.number}
                </span>
                {current.points && (
                  <span className="text-sm text-slate-500">
                    {current.points} pts
                  </span>
                )}
                <span className="text-xs text-slate-500 ml-auto">
                  {current.type}
                </span>
              </div>

              {images.length > 0 && (
                <div className="space-y-3">
                  {images.map((url, i) => (
                    <img
                      key={i}
                      src={url}
                      alt={`Figura ${i + 1}`}
                      className="mx-auto max-h-[560px] max-w-full rounded border bg-white object-contain shadow-sm"
                    />
                  ))}
                </div>
              )}

              {ancestorContext && (
                <div className="bg-blue-50 border-l-4 border-blue-300 p-4 rounded text-sm text-slate-800 whitespace-pre-wrap">
                  <MathText text={ancestorContext} />
                </div>
              )}

              {previewStatement && (
                <div className="text-slate-950 text-base leading-relaxed whitespace-pre-wrap">
                  <MathText text={previewStatement} />
                </div>
              )}

              {currentMatching ? (
                <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-4 shadow-sm">
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    <div>
                      <div className="text-sm font-semibold text-slate-900 mb-2">
                        Coluna I
                      </div>
                      <div className="space-y-2">
                        {currentMatching.left.map((item) => {
                          const key = `${current.questionId}_${item.key}`;
                          return (
                            <label
                              key={item.key}
                              className="flex items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2 text-slate-900"
                            >
                              <span className="w-8 font-bold text-blue-700">
                                ({item.key})
                              </span>
                              <span className="flex-1 text-slate-900">
                                <MathText text={item.text} />
                              </span>
                              <select
                                value={answers[key] || ""}
                                onChange={(e) =>
                                  setAnswers((prev) => ({
                                    ...prev,
                                    [key]: e.target.value,
                                  }))
                                }
                                className="rounded border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900"
                              >
                                <option value="">...</option>
                                {currentMatching.right.map((opt) => (
                                  <option key={opt.key} value={opt.key}>
                                    ({opt.key})
                                  </option>
                                ))}
                              </select>
                            </label>
                          );
                        })}
                      </div>
                    </div>
                    <div>
                      <div className="text-sm font-semibold text-slate-900 mb-2">
                        Coluna II
                      </div>
                      <div className="space-y-2">
                        {currentMatching.right.map((item) => (
                          <div
                            key={item.key}
                            className="rounded-md border border-slate-200 bg-white px-3 py-2 text-sm text-slate-900"
                          >
                            <span className="font-bold text-slate-900">
                              ({item.key})
                            </span>{" "}
                            <MathText text={item.text} />
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              ) : current.type === "multi_blank_choice" &&
                current.blanks?.length ? (
                <div className="rounded-lg border border-slate-200 bg-white p-4 space-y-3 shadow-sm">
                  <div className="text-sm font-semibold text-slate-900">
                    Respostas
                  </div>
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    {current.blanks.map((blank) => {
                      const key = `${current.questionId}_${blank.number}`;
                      return (
                        <label
                          key={blank.number}
                          className="flex items-center gap-3 rounded-md border border-slate-200 bg-white px-3 py-2"
                        >
                          <span className="w-8 font-bold text-blue-700">
                            {blank.number}
                          </span>
                          <select
                            value={answers[key] || ""}
                            onChange={(e) =>
                              setAnswers((prev) => ({
                                ...prev,
                                [key]: e.target.value,
                              }))
                            }
                            className="flex-1 rounded border border-slate-300 bg-white px-2 py-1.5 text-sm text-slate-900"
                          >
                            <option value="">Selecionar...</option>
                            {blank.options.map((opt) => (
                              <option key={opt.letter} value={opt.letter}>
                                {opt.letter}) {normalizeChemistryText(opt.text)}
                              </option>
                            ))}
                          </select>
                        </label>
                      );
                    })}
                  </div>
                </div>
              ) : current.type === "multiple_choice" &&
                current.options &&
                current.options.length > 0 ? (
                <div className="space-y-2">
                  {current.options.map((opt) => {
                    const optionText = cleanOptionText(opt.latex || opt.text);
                    return (
                      <label
                        key={opt.letter}
                        className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors
                          ${answers[current.questionId] === opt.letter ? "border-blue-500 bg-blue-50" : "border-slate-200 bg-white hover:bg-slate-50"}`}
                      >
                        <input
                          type="radio"
                          name={current.questionId}
                          value={opt.letter}
                          checked={answers[current.questionId] === opt.letter}
                          onChange={() =>
                            setAnswers((prev) => ({
                              ...prev,
                              [current.questionId]: opt.letter,
                            }))
                          }
                          className="mt-0.5"
                        />
                        <span className="font-medium text-sm text-slate-700 w-5">
                          ({opt.letter})
                        </span>
                        <span className="flex-1 text-slate-900">
                          {opt.imageUrl ? (
                            <span className="block">
                              <img
                                src={opt.imageUrl}
                                alt={`Opção ${opt.letter}`}
                                className="max-h-72 max-w-full rounded border border-slate-300 bg-white object-contain"
                              />
                            </span>
                          ) : (
                            <MathText text={optionText} />
                          )}
                        </span>
                      </label>
                    );
                  })}
                </div>
              ) : (
                <textarea
                  placeholder="Escreve a tua resposta aqui..."
                  value={answers[current.questionId] || ""}
                  onChange={(e) =>
                    setAnswers((prev) => ({
                      ...prev,
                      [current.questionId]: e.target.value,
                    }))
                  }
                  className="w-full h-32 p-3 border border-slate-300 rounded-lg resize-y text-sm text-slate-900 focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
                />
              )}

              <div className="flex gap-3 pt-4">
                <button
                  onClick={() => setSelected(Math.max(0, selected - 1))}
                  disabled={selected === 0}
                  className="px-4 py-2 rounded bg-white border border-slate-300 hover:bg-slate-50 disabled:opacity-40 text-sm text-slate-900 font-medium"
                >
                  &larr; Anterior
                </button>
                <button
                  onClick={() =>
                    setSelected(Math.min(questions.length - 1, selected + 1))
                  }
                  disabled={selected === questions.length - 1}
                  className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 text-sm"
                >
                  Seguinte &rarr;
                </button>
              </div>
            </div>
          </main>

          <aside className="w-96 bg-slate-900 text-slate-100 overflow-y-auto shrink-0 p-4 border-l">
            <h3 className="text-xs font-semibold text-slate-400 uppercase mb-2">
              JSON da Pergunta
            </h3>
            <pre className="text-xs leading-relaxed whitespace-pre-wrap break-words font-mono">
              {JSON.stringify(current, null, 2)}
            </pre>
          </aside>
        </div>
      </div>
    </MathJaxProvider>
  );
}
