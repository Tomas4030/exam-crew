'use client';

import { useEffect, useMemo, useState } from 'react';
import type { Dispatch, SetStateAction } from 'react';
import Link from 'next/link';

interface TokenUsage {
  calls?: number;
  models?: string[];
  promptTokens?: number;
  completionTokens?: number;
  reasoningTokens?: number;
  totalTokens?: number;
}

interface Exam {
  id: string;
  filename: string;
  status: string;
  createdAt: string;
  updatedAt: string;
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  tokenUsage?: TokenUsage;
  sourceUrl?: string;
  batchIndex?: number;
}

const statusColors: Record<string, string> = {
  queued: 'border-slate-700 bg-slate-800 text-slate-300',
  pending: 'border-yellow-400/30 bg-yellow-500/10 text-yellow-200',
  processing: 'border-blue-400/30 bg-blue-500/10 text-blue-200',
  completed: 'border-emerald-400/30 bg-emerald-500/10 text-emerald-200',
  completed_with_warnings: 'border-amber-400/30 bg-amber-500/10 text-amber-200',
  needs_review: 'border-amber-400/30 bg-amber-500/10 text-amber-200',
  partial_failed: 'border-orange-400/30 bg-orange-500/10 text-orange-200',
  error: 'border-red-400/30 bg-red-500/10 text-red-200',
};

const terminalStatuses = new Set(['completed', 'completed_with_warnings', 'needs_review', 'partial_failed', 'error']);
const exportableStatuses = new Set(['completed', 'completed_with_warnings']);

export default function ExamList() {
  const [exams, setExams] = useState<Exam[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    const fetchExams = () => fetch('/api/exams').then(r => r.json()).then(setExams).catch(() => {});
    fetchExams();
    const interval = setInterval(fetchExams, 5000);
    return () => clearInterval(interval);
  }, []);

  useEffect(() => {
    setSelectedIds(previous => {
      const valid = new Set(exams.map(exam => exam.id));
      const next = new Set([...previous].filter(id => valid.has(id)));
      return next.size === previous.size ? previous : next;
    });
  }, [exams]);

  const exportableExams = useMemo(() => exams.filter(isExportable), [exams]);

  if (exams.length === 0) {
    return (
      <div className="rounded-md border border-dashed border-slate-800 bg-slate-900 p-8 text-center text-slate-400">
        Nenhum exame encontrado.
      </div>
    );
  }

  const completedDurations = exams
    .map(getDurationMs)
    .filter((value): value is number => typeof value === 'number' && value > 0);
  const tokenTotals = exams
    .map(exam => exam.tokenUsage?.totalTokens || 0)
    .filter(total => total > 0);
  const grouped = groupByDay(exams);

  const selectedCount = selectedIds.size;
  const selectedExportableCount = exportableExams.filter(exam => selectedIds.has(exam.id)).length;
  const allSelected = exams.length > 0 && selectedCount === exams.length;

  const toggleAll = () => {
    setSelectedIds(allSelected ? new Set() : new Set(exams.map(exam => exam.id)));
  };

  const downloadSelected = async () => {
    if (!selectedExportableCount || downloading) return;
    setDownloading(true);
    try {
      const response = await fetch('/api/exams/export-selected', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [...selectedIds] }),
      });
      if (!response.ok) throw new Error(await response.text());

      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement('a');
      anchor.href = url;
      anchor.download = filenameFromDisposition(response.headers.get('content-disposition')) || `SelectedExams_${selectedExportableCount}.zip`;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      URL.revokeObjectURL(url);
    } finally {
      setDownloading(false);
    }
  };

  const deleteSelected = async () => {
    if (!selectedCount || deleting) return;
    const confirmed = window.confirm(`Apagar ${selectedCount} exame${selectedCount === 1 ? '' : 's'} selecionado${selectedCount === 1 ? '' : 's'}?`);
    if (!confirmed) return;

    setDeleting(true);
    try {
      const response = await fetch('/api/exams/delete-selected', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ids: [...selectedIds] }),
      });
      if (!response.ok) throw new Error(await response.text());
      setExams(previous => previous.filter(exam => !selectedIds.has(exam.id)));
      setSelectedIds(new Set());
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6">
      <section className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Metric label="Total" value={String(exams.length)} detail="exames na lista" />
        <Metric label="Concluidos" value={String(exams.filter(exam => exam.status === 'completed').length)} detail="sem revisao" />
        <Metric label="Tempo medio" value={completedDurations.length ? formatDuration(avg(completedDurations)) : 'Sem dados'} detail={`${completedDurations.length} com duracao`} />
        <Metric label="Tokens medios" value={tokenTotals.length ? formatNumber(Math.round(avg(tokenTotals))) : 'Sem dados'} detail={`${tokenTotals.length} com usage real`} />
      </section>

      <section className="flex flex-col gap-3 rounded-md border border-slate-800 bg-slate-900 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
        <div className="flex flex-wrap items-center gap-3">
          <label className="inline-flex items-center gap-2 text-sm font-medium text-slate-200">
            <input
              type="checkbox"
              checked={allSelected}
              onChange={toggleAll}
              className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-blue-500 focus:ring-blue-500"
            />
            Selecionar todos
          </label>
          <span className="text-xs text-slate-500">
            {selectedCount} selecionado{selectedCount === 1 ? '' : 's'} - {selectedExportableCount} exportavel{selectedExportableCount === 1 ? '' : 'eis'}
          </span>
        </div>
        <div className="flex flex-col gap-2 sm:flex-row">
          <button
            type="button"
            disabled={!selectedExportableCount || downloading}
            onClick={downloadSelected}
            className="inline-flex items-center justify-center rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white transition-colors hover:bg-blue-500 disabled:cursor-not-allowed disabled:bg-slate-800 disabled:text-slate-500"
          >
            {downloading ? 'A preparar...' : 'Download selecionados'}
          </button>
          <button
            type="button"
            disabled={!selectedCount || deleting}
            onClick={deleteSelected}
            className="inline-flex items-center justify-center rounded-md border border-red-400/30 bg-red-500/10 px-4 py-2 text-sm font-medium text-red-100 transition-colors hover:bg-red-500/20 disabled:cursor-not-allowed disabled:border-slate-800 disabled:bg-slate-800 disabled:text-slate-500"
          >
            {deleting ? 'A apagar...' : 'Apagar selecionados'}
          </button>
        </div>
      </section>

      <section className="space-y-5">
        {grouped.map(group => {
          const groupExportable = group.exams.filter(isExportable);
          const groupSelected = group.exams.filter(exam => selectedIds.has(exam.id)).length;
          const groupSelectedExportable = groupExportable.filter(exam => selectedIds.has(exam.id)).length;
          const groupAllSelected = group.exams.length > 0 && groupSelected === group.exams.length;

          return (
            <div key={group.key} className="overflow-hidden rounded-md border border-slate-800 bg-slate-900 shadow-[0_18px_60px_rgba(0,0,0,0.28)]">
              <div className="flex flex-col gap-3 border-b border-slate-800 bg-slate-900/80 px-4 py-3 sm:flex-row sm:items-center sm:justify-between">
                <div>
                  <h2 className="font-semibold text-white">{group.label}</h2>
                  <p className="text-xs text-slate-400">
                    {group.exams.length} exame{group.exams.length === 1 ? '' : 's'} - media {group.averageDuration ? formatDuration(group.averageDuration) : 'sem duracao'}
                  </p>
                </div>
                <div className="flex flex-wrap items-center gap-3 text-xs text-slate-400">
                  <label className="inline-flex items-center gap-2 text-slate-300">
                    <input
                      type="checkbox"
                      checked={groupAllSelected}
                      onChange={() => toggleGroup(group.exams, groupAllSelected, setSelectedIds)}
                      className="h-4 w-4 rounded border-slate-600 bg-slate-950 text-blue-500 focus:ring-blue-500"
                    />
                    Dia
                  </label>
                  <span>{groupSelected}/{group.exams.length} selecionados</span>
                  <span>{groupSelectedExportable}/{groupExportable.length} exportaveis</span>
                  <span>Tokens: {group.totalTokens ? formatNumber(group.totalTokens) : 'sem dados'}</span>
                </div>
              </div>
              <ul className="divide-y divide-slate-800">
                {group.exams.map(exam => {
                  const checked = selectedIds.has(exam.id);

                  return (
                    <li key={exam.id} className="grid grid-cols-[auto_minmax(0,1fr)] items-start gap-3 px-4 py-4 transition-colors hover:bg-slate-800/55">
                      <input
                        type="checkbox"
                        checked={checked}
                        onChange={() => toggleExam(exam.id, setSelectedIds)}
                        className="mt-1 h-4 w-4 rounded border-slate-600 bg-slate-950 text-blue-500 focus:ring-blue-500"
                        aria-label={`Selecionar ${displayName(exam)}`}
                      />
                      <Link href={`/exams/${exam.id}`} className="min-w-0">
                        <div className="grid gap-3 lg:grid-cols-[minmax(0,1fr)_auto] lg:items-start">
                          <div className="min-w-0">
                            <div className="flex flex-wrap items-center gap-2">
                              <span className="truncate font-medium text-slate-100">{displayName(exam)}</span>
                              <span className={`rounded-full border px-2 py-0.5 text-xs font-medium ${statusColors[exam.status] || 'border-slate-700 bg-slate-800 text-slate-300'}`}>
                                {exam.status}
                              </span>
                            </div>
                            <p className="mt-1 truncate text-xs text-slate-500">{exam.sourceUrl || exam.id}</p>
                          </div>

                          <div className="grid grid-cols-2 gap-3 text-xs text-slate-300 sm:grid-cols-4 lg:min-w-[520px]">
                            <Info label="Criado" value={formatTime(exam.createdAt)} />
                            <Info label="Inicio" value={formatTime(exam.startedAt)} />
                            <Info label="Fim" value={formatTime(exam.completedAt || (terminalStatuses.has(exam.status) ? exam.updatedAt : undefined))} />
                            <Info label="Duracao" value={formatDuration(getDurationMs(exam))} />
                            <Info label="Calls" value={exam.tokenUsage?.calls ? String(exam.tokenUsage.calls) : '-'} />
                            <Info label="Tokens" value={exam.tokenUsage?.totalTokens ? formatNumber(exam.tokenUsage.totalTokens) : '-'} />
                            <Info label="Prompt" value={exam.tokenUsage?.promptTokens ? formatNumber(exam.tokenUsage.promptTokens) : '-'} />
                            <Info label="Resposta" value={exam.tokenUsage?.completionTokens ? formatNumber(exam.tokenUsage.completionTokens) : '-'} />
                          </div>
                        </div>
                      </Link>
                    </li>
                  );
                })}
              </ul>
            </div>
          );
        })}
      </section>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail: string }) {
  return (
    <div className="rounded-md border border-slate-800 bg-slate-900 p-4">
      <div className="text-xs font-medium uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-2 text-2xl font-bold text-white">{value}</div>
      <div className="mt-1 text-xs text-slate-400">{detail}</div>
    </div>
  );
}

function Info({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-slate-500">{label}</div>
      <div className="mt-0.5 font-medium text-slate-200">{value}</div>
    </div>
  );
}

function isExportable(exam: Exam) {
  return exportableStatuses.has(exam.status);
}

function toggleExam(id: string, setSelectedIds: Dispatch<SetStateAction<Set<string>>>) {
  setSelectedIds(previous => {
    const next = new Set(previous);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
}

function toggleGroup(
  exams: Exam[],
  allSelected: boolean,
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>,
) {
  setSelectedIds(previous => {
    const next = new Set(previous);
    for (const exam of exams) {
      if (allSelected) next.delete(exam.id);
      else next.add(exam.id);
    }
    return next;
  });
}

function groupByDay(exams: Exam[]) {
  const groups = new Map<string, Exam[]>();
  const sorted = [...exams].sort((a, b) => new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime());

  for (const exam of sorted) {
    const key = dayKey(exam.createdAt);
    groups.set(key, [...(groups.get(key) || []), exam]);
  }

  return Array.from(groups.entries()).map(([key, groupExams]) => {
    const durations = groupExams
      .map(getDurationMs)
      .filter((value): value is number => typeof value === 'number' && value > 0);
    const totalTokens = groupExams.reduce((sum, exam) => sum + (exam.tokenUsage?.totalTokens || 0), 0);

    return {
      key,
      label: formatDay(groupExams[0]?.createdAt),
      exams: groupExams,
      averageDuration: durations.length ? avg(durations) : 0,
      totalTokens,
    };
  });
}

function displayName(exam: Exam) {
  const source = exam.sourceUrl || exam.filename || exam.id;
  const match = source.match(/\/(20\d{2})-(\dfase)\/([^/?#]+)/i);
  if (match) return `${match[1]} ${match[2].replace('fase', '.a fase')} - ${decodeURIComponent(match[3])}`;
  return exam.batchIndex ? `#${exam.batchIndex} - ${exam.filename}` : exam.filename;
}

function dayKey(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? 'unknown' : date.toISOString().slice(0, 10);
}

function formatDay(value?: string) {
  if (!value) return 'Sem data';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'Sem data';
  return new Intl.DateTimeFormat('pt-PT', { day: 'numeric', month: 'long', year: 'numeric' }).format(date);
}

function formatTime(value?: string) {
  if (!value) return '-';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return '-';
  return new Intl.DateTimeFormat('pt-PT', { hour: '2-digit', minute: '2-digit', second: '2-digit' }).format(date);
}

function getDurationMs(exam: Exam) {
  if (typeof exam.durationMs === 'number') return exam.durationMs;
  if (!exam.startedAt) return undefined;
  const end = exam.completedAt || (terminalStatuses.has(exam.status) ? exam.updatedAt : undefined);
  if (!end) return undefined;
  const duration = new Date(end).getTime() - new Date(exam.startedAt).getTime();
  return Number.isFinite(duration) && duration >= 0 ? duration : undefined;
}

function formatDuration(ms?: number) {
  if (!ms) return '-';
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes >= 60) {
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    return `${hours}h ${rest}m`;
  }
  return `${minutes}m ${seconds}s`;
}

function avg(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat('pt-PT').format(value);
}

function filenameFromDisposition(disposition: string | null) {
  if (!disposition) return '';
  const match = disposition.match(/filename="([^"]+)"/);
  return match?.[1] || '';
}
