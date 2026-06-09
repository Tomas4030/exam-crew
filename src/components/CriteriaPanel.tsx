'use client';

import { useCallback, useEffect, useRef, useState } from 'react';

interface AnswerKeyEntry {
  groupId: string;
  number: string;
  correctAnswer: string;
}
interface AnswerKey {
  version: string;
  default?: boolean;
  items: AnswerKeyEntry[];
}
export interface CriteriaItem {
  criteriaId?: string;
  groupId: string;
  number: string;
  points: number | null;
  type: string;
  correctAnswer: Record<string, string> | null;
  rawText: string;
  contentTopics: string[];
  sourcePage?: number | null;
  sourcePages?: number[];
  confidence?: number;
  status?: string;
  match?: string | null;
  questionId?: string | null;
  needsHumanReview?: boolean;
}
interface AuditIssue {
  code: string;
  severity: string;
  message: string;
}
export interface CriteriaDoc {
  examId: string;
  status: string;
  metadata: {
    subject?: string;
    year?: string;
    phase?: string;
    examCode?: string;
    sourcePdf?: string | null;
    pages?: number;
    extractionMode?: string;
    matchedQuestions?: number;
    unmatchedQuestions?: string[];
    crossCheck?: Record<string, unknown>;
  };
  answerKeys: AnswerKey[];
  items: CriteriaItem[];
  audit: { verdict: string; blocker: number; high: number; issues: AuditIssue[] };
}

const GROUP_LABEL: Record<string, string> = {
  grupo_i: 'Grupo I',
  grupo_ii: 'Grupo II',
  grupo_iii: 'Grupo III',
};

const TYPE_LABEL: Record<string, string> = {
  multiple_choice: 'Escolha múltipla',
  multi_select: 'Escolha múltipla (várias)',
  multi_blank_choice: 'Preenchimento',
  open_answer: 'Resposta aberta',
  essay: 'Composição',
};

const severityStyles: Record<string, string> = {
  blocker: 'bg-red-100 text-red-700',
  high: 'bg-orange-100 text-orange-700',
  medium: 'bg-amber-100 text-amber-700',
  low: 'bg-slate-100 text-slate-600',
};

export default function CriteriaPanel({
  examId,
  autoRun = false,
}: {
  examId: string;
  autoRun?: boolean;
}) {
  const [doc, setDoc] = useState<CriteriaDoc | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [error, setError] = useState('');
  const [pdfFile, setPdfFile] = useState<File | null>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const autoRanRef = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const r = await fetch(`/api/exams/${examId}/criteria`);
      if (r.ok) setDoc(await r.json());
      else setDoc(null);
    } catch {
      setDoc(null);
    } finally {
      setLoading(false);
    }
  }, [examId]);

  useEffect(() => {
    load();
  }, [load]);

  // Auto-run: when autoRun=true, fire criteria silently once after the initial
  // load if no doc exists. Errors are swallowed (non-Portuguese exams simply stay
  // in the "not built" state without alarming the user).
  useEffect(() => {
    if (!autoRun || loading || doc || running || autoRanRef.current) return;
    autoRanRef.current = true;
    setRunning(true);
    fetch(`/api/exams/${examId}/criteria`, { method: 'POST' })
      .then((r) => (r.ok ? r.json() : null))
      .then((data) => { if (data) setDoc(data); })
      .catch(() => {})
      .finally(() => setRunning(false));
  }, [autoRun, loading, doc, running, examId]);

  const run = async () => {
    setRunning(true);
    setError('');
    try {
      let r: Response;
      if (pdfFile) {
        const fd = new FormData();
        fd.append('pdf', pdfFile);
        r = await fetch(`/api/exams/${examId}/criteria`, { method: 'POST', body: fd });
      } else {
        r = await fetch(`/api/exams/${examId}/criteria`, { method: 'POST' });
      }
      const data = await r.json();
      if (!r.ok) {
        setError(data.error || 'Falha ao processar critérios.');
      } else {
        setDoc(data);
        setPdfFile(null);
        if (fileInputRef.current) fileInputRef.current.value = '';
      }
    } catch (e) {
      setError(String(e));
    } finally {
      setRunning(false);
    }
  };

  // Merge answer keys (v1/v2) into a per-item view.
  const mergedKey = (() => {
    if (!doc) return [];
    const map = new Map<string, { group: string; number: string; v1?: string; v2?: string }>();
    for (const ak of doc.answerKeys) {
      for (const it of ak.items) {
        const key = `${it.groupId}|${it.number}`;
        const row = map.get(key) || { group: it.groupId, number: it.number };
        if (ak.version === '1') row.v1 = it.correctAnswer;
        else if (ak.version === '2') row.v2 = it.correctAnswer;
        map.set(key, row);
      }
    }
    return Array.from(map.values());
  })();

  return (
    <section className="mt-8 rounded-lg border border-[#dce5f2] bg-white p-5 shadow-sm">
      <div className="flex flex-wrap items-start justify-between gap-4">
        <div className="flex items-center gap-2">
          <h2 className="text-lg font-bold text-[#07122f]">Critérios oficiais de classificação</h2>
          {running && !pdfFile && (
            <span className="flex items-center gap-1.5 text-xs text-[#7a87a3]">
              <svg className="h-3.5 w-3.5 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
              </svg>
              A obter critérios…
            </span>
          )}
        </div>

        {/* Upload + action */}
        <div className="flex flex-wrap items-center gap-2">
          <label className="flex cursor-pointer items-center gap-1.5 rounded-md border border-[#dce5f2] bg-[#f7faff] px-3 py-2 text-sm text-[#3d4965] hover:bg-[#eef4ff] transition">
            <svg xmlns="http://www.w3.org/2000/svg" className="h-4 w-4 text-[#7a87a3]" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M4 16v2a2 2 0 002 2h12a2 2 0 002-2v-2M16 12l-4-4m0 0l-4 4m4-4v12" />
            </svg>
            {pdfFile ? (
              <span className="max-w-[180px] truncate font-medium text-[#07122f]">{pdfFile.name}</span>
            ) : (
              <span>PDF de critérios</span>
            )}
            <input
              ref={fileInputRef}
              type="file"
              accept=".pdf,application/pdf"
              className="sr-only"
              onChange={(e) => setPdfFile(e.target.files?.[0] ?? null)}
            />
          </label>

          <button
            type="button"
            onClick={run}
            disabled={running}
            className="inline-flex items-center gap-2 rounded-md bg-[#0b66f6] px-4 py-2 text-sm font-semibold text-white transition hover:bg-[#0052df] disabled:cursor-not-allowed disabled:bg-[#b8c5d8]"
          >
            {running ? (
              <>
                <svg className="h-4 w-4 animate-spin" xmlns="http://www.w3.org/2000/svg" fill="none" viewBox="0 0 24 24">
                  <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4" />
                  <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8v8H4z" />
                </svg>
                A processar…
              </>
            ) : doc ? (
              'Reprocessar'
            ) : (
              'Adicionar critérios oficiais'
            )}
          </button>
        </div>
      </div>

      {/* Hint when no file selected and no doc */}
      {!doc && !loading && !pdfFile && (
        <p className="mt-2 text-xs text-[#7a87a3]">
          Seleciona um PDF de critérios para upload manual, ou clica em
          <strong> Adicionar critérios oficiais</strong> para descarregar automaticamente.
        </p>
      )}

      {error && (
        <div className="mt-3 rounded-md bg-red-50 px-3 py-2 text-sm text-red-700">{error}</div>
      )}

      {loading && <p className="mt-3 text-sm text-[#7a87a3]">A carregar…</p>}

      {!loading && !doc && !error && (
        <p className="mt-3 text-sm text-[#53617f]">
          Ainda não foram processados os critérios oficiais deste exame.
        </p>
      )}

      {!loading && doc && (
        <div className="mt-4 space-y-5">
          {/* Summary */}
          <div className="flex flex-wrap items-center gap-2 text-sm">
            <span
              className={`rounded-md px-2.5 py-1 text-xs font-semibold ${
                doc.audit.verdict === 'PASS' ? 'bg-emerald-50 text-emerald-700' : 'bg-amber-50 text-amber-700'
              }`}
            >
              {doc.audit.verdict === 'PASS' ? 'Critérios OK' : 'Critérios c/ avisos'}
            </span>
            <span className="text-[#53617f]">
              {doc.metadata.matchedQuestions ?? 0} itens associados
            </span>
            {doc.metadata.sourcePdf && (
              <a
                href={doc.metadata.sourcePdf}
                target="_blank"
                rel="noopener noreferrer"
                className="text-[#0b66f6] hover:underline"
              >
                PDF de critérios ↗
              </a>
            )}
          </div>

          {/* Answer key */}
          {mergedKey.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-bold text-[#07122f]">Chave de resposta</h3>
              <div className="overflow-x-auto">
                <table className="min-w-[360px] border-collapse text-sm">
                  <thead>
                    <tr className="border-b border-[#dce5f2] text-left text-xs uppercase text-[#667392]">
                      <th className="py-1.5 pr-4">Item</th>
                      <th className="py-1.5 pr-4">Versão 1</th>
                      <th className="py-1.5">Versão 2</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[#eef2f8]">
                    {mergedKey.map((row) => (
                      <tr key={`${row.group}-${row.number}`}>
                        <td className="py-1.5 pr-4 font-medium text-[#28477d]">
                          {GROUP_LABEL[row.group] || row.group} · {row.number}
                        </td>
                        <td className="py-1.5 pr-4 text-[#07122f]">{row.v1 || '—'}</td>
                        <td className="py-1.5 text-[#53617f]">{row.v2 || '—'}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Items */}
          <div>
            <h3 className="mb-2 text-sm font-bold text-[#07122f]">Itens ({doc.items.length})</h3>
            <div className="space-y-1.5">
              {doc.items.map((it) => (
                <details
                  key={it.criteriaId || `${it.groupId}-${it.number}`}
                  className="rounded-md border border-[#eef2f8] bg-[#fbfdff] px-3 py-2"
                >
                  <summary className="flex cursor-pointer flex-wrap items-center gap-2 text-sm">
                    <span className="font-medium text-[#28477d]">
                      {GROUP_LABEL[it.groupId] || it.groupId} · {it.number}
                    </span>
                    <span className="text-xs text-[#7a87a3]">{TYPE_LABEL[it.type] || it.type}</span>
                    {it.points != null && (
                      <span className="rounded bg-slate-100 px-1.5 py-0.5 text-xs text-slate-600">
                        {it.points} pts
                      </span>
                    )}
                    {it.match ? (
                      <span className="rounded bg-emerald-50 px-1.5 py-0.5 text-xs text-emerald-700">
                        associado
                      </span>
                    ) : (
                      <span className="rounded bg-amber-50 px-1.5 py-0.5 text-xs text-amber-700">
                        sem associação
                      </span>
                    )}
                    {it.correctAnswer && (
                      <span className="text-xs text-[#53617f]">
                        chave: {Object.entries(it.correctAnswer).map(([k, v]) => `${k}=${v}`).join(' · ')}
                      </span>
                    )}
                    {it.confidence != null && (
                      <span className="ml-auto text-xs text-[#b8c5d8]">
                        conf. {Math.round(it.confidence * 100)}%
                      </span>
                    )}
                  </summary>
                  {it.contentTopics.length > 0 && (
                    <ul className="mt-2 list-disc space-y-0.5 pl-5 text-xs text-[#3d4965]">
                      {it.contentTopics.map((t, i) => (
                        <li key={i}>{t}</li>
                      ))}
                    </ul>
                  )}
                  {it.rawText && (
                    <pre className="mt-2 max-h-48 overflow-auto whitespace-pre-wrap rounded bg-white p-2 text-[11px] leading-snug text-[#53617f]">
                      {it.rawText}
                    </pre>
                  )}
                  {it.needsHumanReview && (
                    <p className="mt-2 text-xs text-amber-700">⚠ Associação incerta — requer revisão manual</p>
                  )}
                </details>
              ))}
            </div>
          </div>

          {/* Audit issues */}
          {doc.audit.issues.length > 0 && (
            <div>
              <h3 className="mb-2 text-sm font-bold text-[#07122f]">Avisos da auditoria</h3>
              <div className="space-y-1">
                {doc.audit.issues.map((i, idx) => (
                  <div key={idx} className="flex items-start gap-2 text-xs">
                    <span className={`mt-0.5 shrink-0 rounded px-1.5 py-0.5 font-semibold uppercase ${severityStyles[i.severity] || severityStyles.low}`}>
                      {i.severity}
                    </span>
                    <span className="text-[#3d4965]">{i.message}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      )}
    </section>
  );
}
