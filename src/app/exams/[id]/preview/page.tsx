'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import MathJaxProvider from '@/components/MathJaxProvider';
import MathText from '@/components/MathText';

interface Option { letter: string; text: string; latex?: string; }
interface CropInfo { status: string; url?: string; quality?: string; diagnostics?: { edgeTouch?: boolean; textTouchesEdge?: boolean; contentAreaRatio?: number }; }
interface Asset {
  id: string; type: string; page: number; description?: string;
  crops?: { context?: CropInfo; visual?: CropInfo; full?: CropInfo; best?: CropInfo };
  crop?: CropInfo;
}
interface Source { sourceId: string; groupId?: string; label?: string; kind?: string; pageStart?: number; crops?: { full?: CropInfo }; assetRefs?: string[]; }
interface Blank { number: string; options: { letter: string; text: string; latex?: string }[]; }
interface Question {
  questionId: string; number: string; type: string; statement: string; statementLatex?: string;
  statementPlain?: string;
  mathSpans?: { plain: string; latex: string; confidence?: number }[];
  textQuality?: { status?: string };
  options?: Option[]; blanks?: Blank[] | null; group?: string; groupId?: string; displayNumber?: string;
  imageRefs?: string[]; tableRefs?: string[]; assetRefs?: string[]; sourceRefs?: { sourceId: string; childId?: string; mode: string }[];
  media?: { type: string; url: string; sourceId?: string; label?: string }[];
  points?: number; sourcePage?: number; parentQuestion?: string | null; isGroup?: boolean;
}
interface ExamData {
  exam_id: string; metadata: { title?: string; subject?: string; year?: string; phase?: string; stats?: { answerableItems?: number } };
  questions: Question[]; assets: Asset[]; sources?: Source[]; sourceGroups?: { id: string; children: string[]; crops?: { context?: CropInfo } }[];
}

export default function PreviewPage() {
  const { id } = useParams<{ id: string }>();
  const [data, setData] = useState<ExamData | null>(null);
  const [selected, setSelected] = useState(0);
  const [answers, setAnswers] = useState<Record<string, string>>({});

  useEffect(() => {
    fetch(`/api/exams/${id}/result`).then(r => r.json()).then(setData).catch(() => {});
  }, [id]);

  if (!data) return <div className="min-h-screen flex items-center justify-center text-gray-500">A carregar...</div>;

  // Show all questions (including group parents with shared context)
  const questions = data.questions.filter(q => q.statement || (q.options && q.options.length > 0));
  const current = questions[selected];
  if (!current) return <div className="p-8">Sem perguntas.</div>;

  // Get parent context for sub-questions
  const getParentContext = (q: Question): string | null => {
    if (!q.parentQuestion) return null;
    const parent = data.questions.find(p => p.questionId === q.parentQuestion);
    return parent?.statement || null;
  };

  // Get best URL for an asset — backend provides crops.best
  const getBestUrl = (asset?: Asset): string | null => {
    if (!asset) return null;
    if (asset.type === 'embedded_image' && asset.crop?.url) return asset.crop.url;
    const best = asset.crops?.best;
    if (best?.url) return best.url;
    if (asset.crops?.visual?.url) return asset.crops.visual.url;
    if (asset.crop?.url) return asset.crop.url;
    if (asset.crops?.context?.url) return asset.crops.context.url;
    return null;
  };

  // Get images for current question
  const getAllImages = (q: Question): string[] => {
    const urls: string[] = [];
    const add = (url?: string | null) => { if (url && !urls.includes(url)) urls.push(url); };

    // 1. media (cache from backend, but don't block sourceRefs)
    if (q.media?.length) {
      for (const m of q.media) add(m.url);
    }

    // 2. sourceRefs — expand each source independently
    if (q.sourceRefs?.length) {
      for (const ref of q.sourceRefs) {
        const before = urls.length;
        const src = data.sources?.find(s => s.sourceId === ref.sourceId);
        if (!src) continue;

        // Specific child image (e.g. "imagem B")
        if (ref.childId && src.assetRefs?.length) {
          const letter = ref.childId.split('_').pop() || 'a';
          const idx = letter.charCodeAt(0) - 'a'.charCodeAt(0);
          add(getBestUrl(data.assets.find(a => a.id === src.assetRefs![idx])));
        }
        // For image_set sources (e.g. 4 images A/B/C/D), show embedded assets
        else if (src.kind === 'image_set' && src.assetRefs?.length) {
          for (const aId of src.assetRefs) add(getBestUrl(data.assets.find(a => a.id === aId)));
        }
        // For other sources (table, graph, text), prefer the document crop
        else if (src.crops?.full?.url) {
          add(src.crops.full.url);
        }
        // Fallback: try assetRefs anyway
        else if (src.assetRefs?.length) {
          for (const aId of src.assetRefs) add(getBestUrl(data.assets.find(a => a.id === aId)));
        }

        // Per-source fallback: embedded images on source page
        if (urls.length === before && src.pageStart) {
          for (const a of data.assets.filter(a => a.page === src.pageStart && a.type === 'embedded_image')) {
            add(getBestUrl(a));
          }
        }

        // Per-source last resort: source full crop
        if (urls.length === before && src.crops?.full?.url) {
          add(src.crops.full.url);
        }
      }
    }

    // 3. Direct refs
    for (const refId of [...(q.imageRefs || []), ...(q.assetRefs || [])]) {
      add(getBestUrl(data.assets.find(a => a.id === refId)));
    }

    // 4. Text-based detection (for old outputs without sourceRefs)
    if (urls.length === 0 && q.groupId && data.sources) {
      const text = (q.statement || '').toLowerCase();
      const groupSources = data.sources.filter(s => s.groupId === q.groupId);
      const docNums = [...text.matchAll(/documentos?\s+((?:\d+[\s,e]*)+)/gi)]
        .flatMap(m => [...m[1].matchAll(/\d+/g)].map(n => n[0]));
      const allDocs = /cada um dos documentos|dos documentos apresentados|dos dois documentos|dos três documentos/i.test(text);

      const matched = allDocs ? groupSources : groupSources.filter(s =>
        docNums.some(n => s.sourceId.endsWith(`_${n}`))
      );
      for (const src of matched) {
        if (src.assetRefs?.length) {
          for (const aId of src.assetRefs) add(getBestUrl(data.assets.find(a => a.id === aId)));
        } else if (src.pageStart) {
          for (const a of data.assets.filter(a => a.page === src.pageStart && a.type === 'embedded_image')) add(getBestUrl(a));
        }
        if (urls.length === 0 && src.crops?.full?.url) add(src.crops.full.url);
      }
    }

    return urls;
  };

  const images = getAllImages(current);
  const childQuestions = data.questions.filter(q => q.parentQuestion === current.questionId);
  const isGroupParent = Boolean(current.isGroup || current.type === 'group' || childQuestions.length > 0);

  const getRenderableStatement = (q: Question): string => {
    const latex = q.statementLatex || '';
    const badLatex =
      latex.includes('�') ||
      latex.includes('\\begin{itemize}') ||
      latex.includes('\\begin{center}') ||
      latex.includes('\\_\\_') ||
      (q.textQuality?.status === 'corrupt');
    if (badLatex) {
      return q.statementPlain || q.statement;
    }
    return latex || q.statementPlain || q.statement;
  };
  const qJson = current;

  return (
    <MathJaxProvider>
    <div className="h-screen flex flex-col bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b px-4 py-3 flex items-center gap-4 shrink-0">
        <Link href={`/exams/${id}`} className="text-blue-600 hover:underline text-sm">&larr; Voltar</Link>
        <h1 className="font-semibold text-lg truncate">
          {data.metadata.title || `${data.metadata.subject || 'Exame'} ${data.metadata.year || ''}`}
        </h1>
        <span className="ml-auto text-sm text-gray-500">
          {selected + 1} / {questions.length}
        </span>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* Left sidebar — question nav */}
        <aside className="w-56 bg-white border-r overflow-y-auto shrink-0 p-3">
          <div className="grid grid-cols-4 gap-1.5">
            {questions.map((q, i) => (
              <button
                key={q.questionId}
                onClick={() => setSelected(i)}
                className={`w-full aspect-square rounded text-xs font-medium flex items-center justify-center transition-colors
                  ${i === selected ? 'bg-blue-600 text-white' : answers[q.questionId] ? 'bg-green-100 text-green-800 border border-green-300' : 'bg-gray-100 hover:bg-gray-200 text-gray-700'}`}
              >
                {q.displayNumber ? q.number : q.number}
              </button>
            ))}
          </div>
          {/* Group legend */}
          {questions.some(q => q.group) && (
            <div className="mt-4 text-xs text-gray-500 space-y-1">
              {[...new Set(questions.map(q => q.group).filter(Boolean))].map(g => (
                <div key={g} className="font-medium">{g}</div>
              ))}
            </div>
          )}
        </aside>

        {/* Center — question content */}
        <main className="flex-1 overflow-y-auto p-6">
          <div className="max-w-2xl mx-auto space-y-5">
            {/* Question header */}
            <div className="flex items-baseline gap-2">
              <span className="bg-blue-100 text-blue-800 text-sm font-bold px-2.5 py-0.5 rounded">
                {current.displayNumber || (current.group ? `${current.group} - ${current.number}` : `Q${current.number}`)}
              </span>
              {current.points && <span className="text-sm text-gray-500">{current.points} pts</span>}
              <span className="text-xs text-gray-400 ml-auto">{current.type}</span>
            </div>

            {/* Images */}
            {images.length > 0 && (
              <div className="space-y-3">
                {images.map((url, i) => (
                  <img key={i} src={url} alt={`Documento ${i + 1}`} className="max-w-full rounded border shadow-sm" />
                ))}
              </div>
            )}

            {/* Parent context for sub-questions */}
            {getParentContext(current) && (
              <div className="bg-gray-100 border-l-4 border-blue-300 p-4 rounded text-sm text-gray-700">
                <MathText text={getParentContext(current)!} />
              </div>
            )}

            {/* Statement */}
            <div className="text-gray-900 text-base leading-relaxed">
              <MathText text={(() => {
                const useRaw = current.type === 'multi_blank_choice' || current.tableRefs?.length;
                let text = useRaw ? current.statement : getRenderableStatement(current);
                // Remove inline table text when table is shown as image asset
                if (current.tableRefs?.length) {
                  const tableAsset = data.assets.find(a => current.tableRefs!.includes(a.id) && a.type === 'table');
                  if (tableAsset) {
                    // Remove block that looks like table data (rows of numbers/text separated by spaces)
                    text = text.replace(/(?:^|\n)(?:Ano|Year)\s+\d{4}[\s\S]*?(?:\d[\s\d]*\d)\s*(?:\n|$)/gi, '\n');
                  }
                }
                return text.replace(/\n{3,}/g, '\n\n').trim();
              })()} />
            </div>

            {/* Answer area */}
            {isGroupParent ? (
              <div className="space-y-2 rounded-lg border bg-white p-4">
                <div className="text-sm font-semibold text-gray-700">Subquestoes</div>
                {childQuestions.length === 0 ? (
                  <div className="text-sm text-gray-500">Este grupo nao tem subquestoes extraidas.</div>
                ) : (
                  childQuestions
                    .sort((a, b) => a.number.localeCompare(b.number, undefined, { numeric: true }))
                    .map(child => (
                      <button
                        key={child.questionId}
                        onClick={() => {
                          const idx = questions.findIndex(q => q.questionId === child.questionId);
                          if (idx >= 0) setSelected(idx);
                        }}
                        className="w-full rounded border border-gray-200 px-3 py-2 text-left text-sm hover:bg-gray-50"
                      >
                        <span className="font-medium text-gray-700">{child.displayNumber || child.number}</span>
                        <span className="ml-2 text-gray-500">{child.type}</span>
                      </button>
                    ))
                )}
              </div>
            ) : current.type === 'multi_blank_choice' && current.blanks?.length ? (
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-4 gap-3">
                {current.blanks.map(blank => (
                  <div key={blank.number} className="border rounded-lg bg-white overflow-hidden">
                    <div className="font-bold text-center border-b p-2 bg-gray-50">{blank.number}</div>
                    <div className="p-3 space-y-2">
                      {blank.options.map(opt => {
                        const key = `${current.questionId}_${blank.number}`;
                        return (
                          <label key={opt.letter} className={`flex items-start gap-2 p-2 rounded cursor-pointer ${answers[key] === opt.letter ? 'bg-blue-50 border border-blue-300' : 'hover:bg-gray-50'}`}>
                            <input type="radio" name={key} value={opt.letter} checked={answers[key] === opt.letter} onChange={() => setAnswers(prev => ({ ...prev, [key]: opt.letter }))} className="mt-1" />
                            <span className="text-sm"><strong>{opt.letter})</strong> <MathText text={opt.latex || opt.text} /></span>
                          </label>
                        );
                      })}
                    </div>
                  </div>
                ))}
              </div>
            ) : current.type === 'multiple_choice' && current.options && current.options.length > 0 ? (
              <div className="space-y-2">
                {current.options.map(opt => (
                  <label
                    key={opt.letter}
                    className={`flex items-start gap-3 p-3 rounded-lg border cursor-pointer transition-colors
                      ${answers[current.questionId] === opt.letter ? 'border-blue-500 bg-blue-50' : 'border-gray-200 hover:bg-gray-50'}`}
                  >
                    <input
                      type="radio"
                      name={current.questionId}
                      value={opt.letter}
                      checked={answers[current.questionId] === opt.letter}
                      onChange={() => setAnswers(prev => ({ ...prev, [current.questionId]: opt.letter }))}
                      className="mt-0.5"
                    />
                    <span className="font-medium text-sm text-gray-500 w-5">({opt.letter})</span>
                    <span className="text-gray-800"><MathText text={opt.latex || opt.text} /></span>
                  </label>
                ))}
              </div>
            ) : (
              <textarea
                placeholder="Escreve a tua resposta aqui..."
                value={answers[current.questionId] || ''}
                onChange={e => setAnswers(prev => ({ ...prev, [current.questionId]: e.target.value }))}
                className="w-full h-32 p-3 border border-gray-300 rounded-lg resize-y text-sm focus:ring-2 focus:ring-blue-500 focus:border-blue-500"
              />
            )}

            {/* Navigation */}
            <div className="flex gap-3 pt-4">
              <button
                onClick={() => setSelected(Math.max(0, selected - 1))}
                disabled={selected === 0}
                className="px-4 py-2 rounded bg-gray-200 hover:bg-gray-300 disabled:opacity-40 text-sm"
              >
                &larr; Anterior
              </button>
              <button
                onClick={() => setSelected(Math.min(questions.length - 1, selected + 1))}
                disabled={selected === questions.length - 1}
                className="px-4 py-2 rounded bg-blue-600 text-white hover:bg-blue-700 disabled:opacity-40 text-sm"
              >
                Seguinte &rarr;
              </button>
            </div>
          </div>
        </main>

        {/* Right panel — JSON */}
        <aside className="w-96 bg-gray-900 text-gray-100 overflow-y-auto shrink-0 p-4 border-l">
          <h3 className="text-xs font-semibold text-gray-400 uppercase mb-2">JSON da Pergunta</h3>
          <pre className="text-xs leading-relaxed whitespace-pre-wrap break-words font-mono">
            {JSON.stringify(qJson, null, 2)}
          </pre>
        </aside>
      </div>
    </div>
    </MathJaxProvider>
  );
}
