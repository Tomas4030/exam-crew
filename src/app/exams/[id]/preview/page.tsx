'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';

interface Option { letter: string; text: string; }
interface CropInfo { status: string; url?: string; }
interface Asset {
  id: string; type: string; page: number; description?: string;
  crops?: { context?: CropInfo; visual?: CropInfo; full?: CropInfo };
  crop?: CropInfo;
}
interface Source { sourceId: string; groupId?: string; label?: string; pageStart?: number; crops?: { full?: CropInfo }; assetRefs?: string[]; }
interface Question {
  questionId: string; number: string; type: string; statement: string;
  options?: Option[]; group?: string; groupId?: string; displayNumber?: string;
  imageRefs?: string[]; assetRefs?: string[]; sourceRefs?: { sourceId: string; childId?: string; mode: string }[];
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

  // Filter to answerable questions (skip groups that are just containers)
  const questions = data.questions.filter(q => !q.isGroup || (q.options && q.options.length > 0));
  const current = questions[selected];
  if (!current) return <div className="p-8">Sem perguntas.</div>;

  // Get best URL for an asset (embedded > visual > context)
  const getBestUrl = (asset?: Asset): string | null => {
    if (!asset) return null;
    // Embedded images are always clean (extracted directly from PDF)
    if (asset.type === 'embedded_image' && asset.crop?.url) return asset.crop.url;
    // Visual crop (clean isolated figure)
    if (asset.crops?.visual?.status === 'success' && asset.crops.visual.url) return asset.crops.visual.url;
    // Context crop only if successful
    if (asset.crops?.context?.status === 'success' && asset.crops.context.url) return asset.crops.context.url;
    // Generic crop fallback
    if (asset.crop?.status === 'success' && asset.crop.url) return asset.crop.url;
    return null;
  };

  // Get images for current question
  const getAllImages = (q: Question): string[] => {
    // Priority 1: question.media (resolved by backend)
    if (q.media && q.media.length > 0) {
      return q.media.map(m => m.url).filter(Boolean);
    }

    const urls: string[] = [];

    // Priority 2: sourceRefs → find assets (prefer embedded)
    if (q.sourceRefs && q.sourceRefs.length > 0) {
      for (const ref of q.sourceRefs) {
        const src = data.sources?.find(s => s.sourceId === ref.sourceId);
        if (!src) continue;

        // Specific child
        if (ref.childId && src.assetRefs?.length) {
          const letter = ref.childId.split('_').pop() || 'a';
          const idx = letter.charCodeAt(0) - 'a'.charCodeAt(0);
          const asset = data.assets.find(a => a.id === src.assetRefs![idx]);
          const url = getBestUrl(asset);
          if (url) { urls.push(url); continue; }
        }

        // Full source — show asset images
        if (src.assetRefs?.length) {
          for (const aId of src.assetRefs) {
            const asset = data.assets.find(a => a.id === aId);
            const url = getBestUrl(asset);
            if (url) urls.push(url);
          }
          if (urls.length > 0) continue;
        }

        // Last resort: source full crop
        if (src.crops?.full?.url) urls.push(src.crops.full.url);
      }
    }
    if (urls.length > 0) return [...new Set(urls)];

    // Priority 3: direct refs
    for (const refId of [...(q.imageRefs || []), ...(q.assetRefs || [])]) {
      const url = getBestUrl(data.assets.find(a => a.id === refId));
      if (url) urls.push(url);
    }
    if (urls.length > 0) return [...new Set(urls)];

    // Priority 4: group fallback
    if (q.groupId && data.sources) {
      for (const src of data.sources.filter(s => s.groupId === q.groupId && (s.pageStart || 0) < (q.sourcePage || 999))) {
        if (src.assetRefs?.length) {
          for (const aId of src.assetRefs) {
            const url = getBestUrl(data.assets.find(a => a.id === aId));
            if (url) urls.push(url);
          }
        }
      }
    }
    return [...new Set(urls)];
  };

  const images = getAllImages(current);
  const qJson = current;

  return (
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

            {/* Statement */}
            <p className="text-gray-900 text-base leading-relaxed whitespace-pre-wrap">{current.statement}</p>

            {/* Answer area */}
            {current.type === 'multiple_choice' && current.options && current.options.length > 0 ? (
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
                    <span className="text-gray-800">{opt.text}</span>
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
  );
}
