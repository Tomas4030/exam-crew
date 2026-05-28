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
interface Source { sourceId: string; groupId?: string; label?: string; kind?: string; pageStart?: number; crops?: { best?: CropInfo; full?: CropInfo; visual?: CropInfo; context?: CropInfo; document?: CropInfo }; assetRefs?: string[]; }
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

  // Get best URL for an asset
  const getBestUrl = (asset?: Asset): string | null => {
    if (!asset) return null;
    return (
      asset.crops?.best?.url ||
      asset.crops?.visual?.url ||
      asset.crop?.url ||
      asset.crops?.context?.url ||
      asset.crops?.full?.url ||
      null
    );
  };

  // Get images for current question
  const getAllImages = (q: Question): string[] => {
    const urls: string[] = [];
    const add = (url?: string | null) => { if (url && !urls.includes(url)) urls.push(url); };
    const addAsset = (id?: string) => { if (id) add(getBestUrl(data.assets.find(a => a.id === id))); };

    // 1. Direct refs (most specific — always wins)
    for (const refId of [...(q.imageRefs || []), ...(q.assetRefs || []), ...(q.tableRefs || [])]) {
      addAsset(refId);
    }

    // 2. Source refs: assetRefs first, source crop only as fallback
    if (q.sourceRefs?.length) {
      for (const ref of q.sourceRefs) {
        const src = data.sources?.find(s => s.sourceId === ref.sourceId);
        if (!src) continue;
        const srcAssets = src.assetRefs || [];

        // Specific child (e.g. "imagem B")
        if (ref.childId && srcAssets.length) {
          const letter = ref.childId.split('_').pop()?.toLowerCase() || 'a';
          const idx = letter.charCodeAt(0) - 'a'.charCodeAt(0);
          if (idx >= 0 && idx < srcAssets.length) addAsset(srcAssets[idx]);
          continue;
        }

        // Source has asset images — use them (not the full page crop)
        if (srcAssets.length) {
          for (const aId of srcAssets) addAsset(aId);
          continue;
        }

        // No assets — use source document crop as fallback
        add(
          (src.crops as any)?.best?.url ||
          src.crops?.full?.url ||
          null
        );
      }
    }

    // 3. Text-based detection (old outputs without sourceRefs)
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
          for (const aId of src.assetRefs) addAsset(aId);
        } else if (src.crops?.full?.url) {
          add(src.crops.full.url);
        }
      }
    }

    // 4. Media as last fallback
    if (urls.length === 0 && q.media?.length) {
      for (const m of q.media) add(m.url);
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
        {/* Left sidebar — question nav grouped */}
        <aside className="w-56 bg-white border-r overflow-y-auto shrink-0 p-3">
          {(() => {
            const groups = [...new Set(questions.map(q => q.group || 'Perguntas'))];
            return groups.map(group => {
              const groupQs = questions.filter(q => (q.group || 'Perguntas') === group);
              return (
                <div key={group} className="mb-4">
                  <div className="text-xs font-bold text-gray-900 uppercase tracking-wide mb-1.5 px-1">{group}</div>
                  <div className="grid grid-cols-4 gap-1.5">
                    {groupQs.map(q => {
                      const i = questions.indexOf(q);
                      return (
                        <button
                          key={q.questionId}
                          onClick={() => setSelected(i)}
                          className={`w-full aspect-square rounded text-xs font-bold flex items-center justify-center border transition-colors
                            ${i === selected ? 'bg-blue-600 text-white border-blue-600' : answers[q.questionId] ? 'bg-blue-50 text-blue-800 border-blue-300' : 'bg-white text-gray-900 border-gray-300 hover:border-blue-400'}`}
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
                  <img key={i} src={url} alt={`Documento ${i + 1}`} className="mx-auto max-h-[560px] max-w-full rounded border bg-white object-contain shadow-sm" />
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
              <div className="rounded-lg border bg-white p-4 space-y-3">
                <div className="text-sm font-semibold text-gray-700">Respostas</div>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                  {current.blanks.map(blank => {
                    const key = `${current.questionId}_${blank.number}`;
                    return (
                      <label key={blank.number} className="flex items-center gap-3 rounded border px-3 py-2">
                        <span className="w-8 font-bold text-blue-700">{blank.number}</span>
                        <select
                          value={answers[key] || ''}
                          onChange={e => setAnswers(prev => ({ ...prev, [key]: e.target.value }))}
                          className="flex-1 rounded border border-gray-300 bg-white px-2 py-1.5 text-sm text-gray-900"
                        >
                          <option value="">Selecionar...</option>
                          {blank.options.map(opt => (
                            <option key={opt.letter} value={opt.letter}>{opt.letter}) {opt.text}</option>
                          ))}
                        </select>
                      </label>
                    );
                  })}
                </div>
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
                className="px-4 py-2 rounded bg-white border border-gray-300 hover:bg-gray-50 disabled:opacity-40 text-sm text-gray-900 font-medium"
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