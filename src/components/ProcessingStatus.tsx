'use client';

import { useState, useEffect } from 'react';

interface Progress {
  step: string;
  label: string;
  pct: number;
  message: string;
}

interface StatusData {
  id: string;
  status: string;
  error?: string;
  progress?: Progress | null;
}

const STEPS = [
  { id: 'extract', label: 'Extrair PDF' },
  { id: 'vision', label: 'Analisar páginas' },
  { id: 'scoring', label: 'Extrair cotações' },
  { id: 'assemble', label: 'Montar estrutura' },
  { id: 'crop', label: 'Cortar imagens' },
  { id: 'math_normalize', label: 'Normalizar fórmulas' },
  { id: 'validate', label: 'Validar' },
  { id: 'done', label: 'Concluído' },
];

export default function ProcessingStatus({ examId }: { examId: string }) {
  const [data, setData] = useState<StatusData | null>(null);

  useEffect(() => {
    let interval: ReturnType<typeof setInterval>;
    const fetchStatus = () =>
      fetch(`/api/exams/${examId}/status`).then(r => r.json()).then(d => {
        setData(d);
        if (['completed', 'error', 'completed_with_warnings', 'needs_review'].includes(d.status)) {
          clearInterval(interval);
        }
      }).catch(() => {});
    fetchStatus();
    interval = setInterval(fetchStatus, 2000);
    return () => clearInterval(interval);
  }, [examId]);

  if (!data) return <div className="p-4 text-gray-500">A carregar...</div>;

  if (data.status === 'completed' || data.status === 'completed_with_warnings' || data.status === 'needs_review') {
    return (
      <div className="p-4 border border-green-200 bg-green-50 rounded-lg">
        <div className="flex items-center gap-2">
          <svg className="w-5 h-5 text-green-600" fill="currentColor" viewBox="0 0 20 20">
            <path fillRule="evenodd" d="M10 18a8 8 0 100-16 8 8 0 000 16zm3.707-9.293a1 1 0 00-1.414-1.414L9 10.586 7.707 9.293a1 1 0 00-1.414 1.414l2 2a1 1 0 001.414 0l4-4z" clipRule="evenodd" />
          </svg>
          <span className="font-semibold text-green-800">Processamento concluído</span>
        </div>
      </div>
    );
  }

  if (data.status === 'error') {
    return (
      <div className="p-4 border border-red-200 bg-red-50 rounded-lg">
        <p className="font-semibold text-red-800">Erro no processamento</p>
        {data.error && <p className="mt-1 text-sm text-red-600">{data.error}</p>}
      </div>
    );
  }

  const progress = data.progress;
  const currentStepIdx = progress ? STEPS.findIndex(s => s.id === progress.step) : -1;

  return (
    <div className="p-5 border border-blue-100 bg-white rounded-lg space-y-4">
      {/* Progress bar */}
      <div>
        <div className="flex justify-between text-sm mb-1">
          <span className="font-medium text-gray-900">{progress?.label || 'A processar...'}</span>
          <span className="text-gray-500">{progress?.pct || 0}%</span>
        </div>
        <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
          <div
            className="h-full bg-blue-600 rounded-full transition-all duration-700 ease-out"
            style={{ width: `${progress?.pct || 0}%` }}
          />
        </div>
        {progress?.message && (
          <p className="mt-1.5 text-xs text-gray-500">{progress.message}</p>
        )}
      </div>

      {/* Steps */}
      <div className="grid grid-cols-2 sm:grid-cols-4 gap-2">
        {STEPS.map((step, i) => {
          const isDone = i < currentStepIdx || (i === currentStepIdx && progress?.step === 'done');
          const isCurrent = i === currentStepIdx && progress?.step !== 'done';
          return (
            <div key={step.id} className={`flex items-center gap-1.5 text-xs rounded px-2 py-1.5 ${
              isDone ? 'text-green-700 bg-green-50' :
              isCurrent ? 'text-blue-700 bg-blue-50 font-medium' :
              'text-gray-400'
            }`}>
              {isDone ? (
                <svg className="w-3.5 h-3.5 shrink-0" fill="currentColor" viewBox="0 0 20 20">
                  <path fillRule="evenodd" d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z" clipRule="evenodd" />
                </svg>
              ) : isCurrent ? (
                <svg className="w-3.5 h-3.5 shrink-0 animate-spin" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z" />
                </svg>
              ) : (
                <div className="w-3.5 h-3.5 shrink-0 rounded-full border border-gray-300" />
              )}
              <span className="truncate">{step.label}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
}
