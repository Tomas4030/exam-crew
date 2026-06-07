"use client";

import { useEffect, useMemo, useState } from "react";
import type { Dispatch, SetStateAction } from "react";
import Link from "next/link";

interface TokenUsage {
  calls?: number;
  promptTokens?: number;
  completionTokens?: number;
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

const terminalStatuses = new Set(["completed", "completed_with_warnings", "needs_review", "partial_failed", "error"]);
const exportableStatuses = new Set(["completed", "completed_with_warnings", "needs_review", "partial_failed", "error"]);

const statusLabels: Record<string, string> = {
  queued: "A aguardar",
  pending: "A aguardar",
  processing: "Em processamento",
  completed: "Concluido",
  completed_with_warnings: "Com avisos",
  needs_review: "Revisao",
  partial_failed: "Parcial",
  error: "Erro",
};

const statusStyles: Record<string, string> = {
  queued: "bg-amber-50 text-amber-700",
  pending: "bg-amber-50 text-amber-700",
  processing: "bg-blue-50 text-[#0b66f6]",
  completed: "bg-emerald-50 text-emerald-700",
  completed_with_warnings: "bg-amber-50 text-amber-700",
  needs_review: "bg-amber-50 text-amber-700",
  partial_failed: "bg-orange-50 text-orange-700",
  error: "bg-red-50 text-red-700",
};

export default function ExamList() {
  const [exams, setExams] = useState<Exam[]>([]);
  const [selectedIds, setSelectedIds] = useState<Set<string>>(new Set());
  const [downloading, setDownloading] = useState(false);
  const [deleting, setDeleting] = useState(false);
  const [query, setQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("all");
  const [subjectFilter, setSubjectFilter] = useState("all");

  useEffect(() => {
    const fetchExams = () => fetch("/api/exams").then((response) => response.json()).then((nextExams: Exam[]) => {
      setExams(nextExams);
      setSelectedIds((previous) => {
        const valid = new Set(nextExams.map((exam) => exam.id));
        const next = new Set([...previous].filter((id) => valid.has(id)));
        return next.size === previous.size ? previous : next;
      });
    }).catch(() => {});
    fetchExams();
    const interval = setInterval(fetchExams, 5000);
    return () => clearInterval(interval);
  }, []);

  const filteredExams = useMemo(() => {
    const needle = query.trim().toLowerCase();
    return exams.filter((exam) => {
      const haystack = `${displayName(exam)} ${exam.sourceUrl || ""} ${exam.id}`.toLowerCase();
      const subject = inferSubject(exam);
      const statusOk = statusFilter === "all" || exam.status === statusFilter;
      const subjectOk = subjectFilter === "all" || subject === subjectFilter;
      return statusOk && subjectOk && (!needle || haystack.includes(needle));
    });
  }, [exams, query, statusFilter, subjectFilter]);

  const grouped = useMemo(() => groupByDay(filteredExams), [filteredExams]);
  const exportableExams = useMemo(() => exams.filter(isExportable), [exams]);
  const completedDurations = exams.map(getDurationMs).filter((value): value is number => typeof value === "number" && value > 0);
  const tokenTotals = exams.map((exam) => exam.tokenUsage?.totalTokens || 0).filter((total) => total > 0);
  const subjects = useMemo(() => Array.from(new Set(exams.map(inferSubject))).filter(Boolean).sort(), [exams]);

  const selectedCount = selectedIds.size;
  const selectedExportableCount = exportableExams.filter((exam) => selectedIds.has(exam.id)).length;
  const visibleAllSelected = filteredExams.length > 0 && filteredExams.every((exam) => selectedIds.has(exam.id));

  const toggleVisible = () => {
    setSelectedIds((previous) => {
      const next = new Set(previous);
      if (visibleAllSelected) filteredExams.forEach((exam) => next.delete(exam.id));
      else filteredExams.forEach((exam) => next.add(exam.id));
      return next;
    });
  };

  const downloadSelected = async () => {
    if (!selectedExportableCount || downloading) return;
    setDownloading(true);
    try {
      const response = await fetch("/api/exams/export-selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [...selectedIds] }),
      });
      if (!response.ok) throw new Error(await response.text());
      const blob = await response.blob();
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filenameFromDisposition(response.headers.get("content-disposition")) || `SelectedExams_${selectedExportableCount}.zip`;
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
    const confirmed = window.confirm(`Apagar ${selectedCount} exame${selectedCount === 1 ? "" : "s"} selecionado${selectedCount === 1 ? "" : "s"}?`);
    if (!confirmed) return;
    setDeleting(true);
    try {
      const response = await fetch("/api/exams/delete-selected", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ids: [...selectedIds] }),
      });
      if (!response.ok) throw new Error(await response.text());
      setExams((previous) => previous.filter((exam) => !selectedIds.has(exam.id)));
      setSelectedIds(new Set());
    } finally {
      setDeleting(false);
    }
  };

  if (exams.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-[#b8c5d8] bg-white p-12 text-center text-[#53617f]">
        Nenhum exame encontrado.
      </div>
    );
  }

  return (
    <div className="space-y-8">
      <section className="grid grid-cols-1 gap-5 sm:grid-cols-2 xl:grid-cols-4">
        <Metric icon="file" label="Total" value={String(exams.length)} detail="exames na lista" />
        <Metric icon="check" label="Concluidos" value={String(exams.filter((exam) => exam.status === "completed").length)} detail="sem revisao" />
        <Metric icon="clock" label="Tempo medio" value={completedDurations.length ? formatDuration(avg(completedDurations)) : "Sem dados"} detail={`${completedDurations.length} com duracao`} />
        <Metric icon="tokens" label="Tokens medios" value={tokenTotals.length ? formatNumber(Math.round(avg(tokenTotals))) : "Sem dados"} detail={`${tokenTotals.length} com usage real`} />
      </section>

      <section className="rounded-lg border border-[#dce5f2] bg-white p-5 shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
        <div className="flex flex-col gap-4 xl:flex-row xl:items-center">
          <label className="relative min-w-0 flex-1">
            <SearchIcon />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              className="h-12 w-full rounded-md border border-[#dce5f2] bg-white pl-12 pr-4 text-sm text-[#07122f] placeholder:text-[#7a87a3] focus:border-[#0b66f6] focus:ring-4 focus:ring-blue-100"
              placeholder="Pesquisar por nome do ficheiro..."
            />
          </label>
          <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value)} className="h-12 rounded-md border border-[#dce5f2] bg-white px-4 text-sm text-[#3d4965]">
            <option value="all">Todos os estados</option>
            {Object.keys(statusLabels).map((status) => (
              <option key={status} value={status}>{statusLabels[status]}</option>
            ))}
          </select>
          <select value={subjectFilter} onChange={(event) => setSubjectFilter(event.target.value)} className="h-12 rounded-md border border-[#dce5f2] bg-white px-4 text-sm text-[#3d4965]">
            <option value="all">Todas as disciplinas</option>
            {subjects.map((subject) => (
              <option key={subject} value={subject}>{subject}</option>
            ))}
          </select>
          <div className="hidden h-10 w-px bg-[#dce5f2] xl:block" />
          <a href="/api/exams/export-all" download className="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-[#0b66f6] px-5 text-sm font-semibold text-[#0b66f6] transition hover:bg-[#eef5ff]">
            <DownloadIcon /> Download todos
          </a>
          <button type="button" disabled={!selectedExportableCount || downloading} onClick={downloadSelected} className="inline-flex h-12 items-center justify-center gap-2 rounded-md bg-[#0b66f6] px-5 text-sm font-semibold text-white transition hover:bg-[#0052df] disabled:cursor-not-allowed disabled:bg-[#b8c5d8]">
            <DownloadIcon /> {downloading ? "A preparar..." : `Download selecionados (${selectedExportableCount})`}
          </button>
          <button type="button" disabled={!selectedCount || deleting} onClick={deleteSelected} className="inline-flex h-12 items-center justify-center gap-2 rounded-md border border-red-300 bg-white px-5 text-sm font-semibold text-red-600 transition hover:bg-red-50 disabled:cursor-not-allowed disabled:border-[#dce5f2] disabled:text-[#9aa7bb]">
            <TrashIcon /> {deleting ? "A apagar..." : `Apagar selecionados (${selectedCount})`}
          </button>
        </div>
      </section>

      <section className="space-y-7">
        {grouped.map((group) => (
          <DayTable
            key={group.key}
            group={group}
            selectedIds={selectedIds}
            visibleAllSelected={visibleAllSelected}
            onToggleVisible={toggleVisible}
            setSelectedIds={setSelectedIds}
          />
        ))}
      </section>
    </div>
  );
}

function DayTable({
  group,
  selectedIds,
  setSelectedIds,
}: {
  group: ReturnType<typeof groupByDay>[number];
  selectedIds: Set<string>;
  visibleAllSelected: boolean;
  onToggleVisible: () => void;
  setSelectedIds: Dispatch<SetStateAction<Set<string>>>;
}) {
  const groupSelected = group.exams.filter((exam) => selectedIds.has(exam.id)).length;
  const groupAllSelected = group.exams.length > 0 && groupSelected === group.exams.length;

  return (
    <div className="overflow-hidden rounded-lg border border-[#dce5f2] bg-white shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
      <div className="flex flex-col gap-3 border-b border-[#dce5f2] px-5 py-4 sm:flex-row sm:items-center sm:justify-between">
        <div>
          <h2 className="text-lg font-bold text-[#07122f]">{group.label}</h2>
          <p className="text-sm text-[#53617f]">{group.exams.length} exames · media {group.averageDuration ? formatDuration(group.averageDuration) : "sem duracao"}</p>
        </div>
        <label className="flex items-center gap-3 text-sm font-medium text-[#3d4965]">
          <input type="checkbox" checked={groupAllSelected} onChange={() => toggleGroup(group.exams, groupAllSelected, setSelectedIds)} className="h-4 w-4 rounded border-[#b8c5d8] text-[#0b66f6]" />
          {groupSelected}/{group.exams.length} selecionados · Tokens: {group.totalTokens ? formatNumber(group.totalTokens) : "sem dados"}
        </label>
      </div>

      <div className="max-w-full overflow-x-auto">
        <table className="w-full min-w-[980px] table-fixed border-collapse text-left">
          <colgroup>
            <col className="w-[4%]" />
            <col className="w-[33%]" />
            <col className="w-[10%]" />
            <col className="w-[13%]" />
            <col className="w-[18%]" />
            <col className="w-[8%]" />
            <col className="w-[7%]" />
            <col className="w-[7%]" />
          </colgroup>
          <thead className="bg-[#fbfdff] text-xs font-bold uppercase tracking-wide text-[#667392]">
            <tr className="border-b border-[#dce5f2]">
              <th className="px-5 py-4">
                <input type="checkbox" checked={groupAllSelected} onChange={() => toggleGroup(group.exams, groupAllSelected, setSelectedIds)} className="h-4 w-4 rounded border-[#b8c5d8] text-[#0b66f6]" />
              </th>
              <th className="px-4 py-4">Ficheiro</th>
              <th className="px-4 py-4">Disciplina</th>
              <th className="px-4 py-4">Estado</th>
              <th className="px-4 py-4">Progresso</th>
              <th className="px-4 py-4">Duração</th>
              <th className="px-4 py-4">Tokens</th>
              <th className="px-3 py-4 whitespace-nowrap">Criado</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-[#e8eef7]">
            {group.exams.map((exam) => (
              <tr key={exam.id} className="transition hover:bg-[#f7fbff]">
                <td className="px-5 py-4">
                  <input type="checkbox" checked={selectedIds.has(exam.id)} onChange={() => toggleExam(exam.id, setSelectedIds)} className="h-4 w-4 rounded border-[#b8c5d8] text-[#0b66f6]" aria-label={`Selecionar ${displayName(exam)}`} />
                </td>
                <td className="min-w-0 px-4 py-4">
                  <Link href={`/exams/${exam.id}`} className="flex min-w-0 items-center gap-3 font-medium text-[#28477d] hover:text-[#0b66f6]">
                    <FileIcon />
                    <span className="min-w-0 truncate">{displayName(exam)}</span>
                  </Link>
                  {exam.sourceUrl && <p className="mt-1 truncate text-xs text-[#7a87a3]">{exam.sourceUrl}</p>}
                </td>
                <td className="px-4 py-4 text-sm text-[#53617f]">{inferSubject(exam)}</td>
                <td className="px-4 py-4">
                  <span className={`inline-flex items-center gap-2 rounded-md px-3 py-1 text-xs font-semibold ${statusStyles[exam.status] || "bg-slate-100 text-slate-700"}`}>
                    <span className="h-2 w-2 rounded-full bg-current" />
                    {statusLabels[exam.status] || exam.status}
                  </span>
                </td>
                <td className="px-3 py-4">
                  <div className="flex items-center gap-3">
                    <span className="w-10 text-sm font-semibold text-[#0b66f6]">{progressFor(exam)}%</span>
                    <div className="h-2 min-w-0 flex-1 overflow-hidden rounded-full bg-[#e8eef7]">
                      <div className="h-full rounded-full bg-[#0b66f6]" style={{ width: `${progressFor(exam)}%` }} />
                    </div>
                  </div>
                </td>
                <td className="px-3 py-4 text-sm font-medium text-[#07122f] whitespace-nowrap">{formatDuration(getDurationMs(exam))}</td>
                <td className="px-3 py-4 text-sm text-[#53617f] truncate">{exam.tokenUsage?.totalTokens ? formatNumber(exam.tokenUsage.totalTokens) : "-"}</td>
                <td className="px-3 py-4 text-sm text-[#53617f] leading-tight">{formatCompactDateTime(exam.createdAt)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function Metric({ icon, label, value, detail }: { icon: "file" | "check" | "clock" | "tokens"; label: string; value: string; detail: string }) {
  return (
    <div className="flex items-center gap-6 rounded-lg border border-[#dce5f2] bg-white p-6 shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
      <div className="flex h-20 w-20 shrink-0 items-center justify-center rounded-md bg-[#eaf2ff] text-[#0b66f6]">
        <MetricIcon icon={icon} />
      </div>
      <div>
        <div className="text-xs font-bold uppercase tracking-wide text-[#667392]">{label}</div>
        <div className="mt-2 text-3xl font-bold tracking-[-0.04em] text-[#07122f]">{value}</div>
        <div className="mt-1 text-sm text-[#667392]">{detail}</div>
      </div>
    </div>
  );
}

function isExportable(exam: Exam) {
  return exportableStatuses.has(exam.status);
}

function toggleExam(id: string, setSelectedIds: Dispatch<SetStateAction<Set<string>>>) {
  setSelectedIds((previous) => {
    const next = new Set(previous);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    return next;
  });
}

function toggleGroup(exams: Exam[], allSelected: boolean, setSelectedIds: Dispatch<SetStateAction<Set<string>>>) {
  setSelectedIds((previous) => {
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
    const durations = groupExams.map(getDurationMs).filter((value): value is number => typeof value === "number" && value > 0);
    return {
      key,
      label: formatDay(groupExams[0]?.createdAt),
      exams: groupExams,
      averageDuration: durations.length ? avg(durations) : 0,
      totalTokens: groupExams.reduce((sum, exam) => sum + (exam.tokenUsage?.totalTokens || 0), 0),
    };
  });
}

function displayName(exam: Exam) {
  const source = exam.sourceUrl || exam.filename || exam.id;
  const match = source.match(/\/(20\d{2})-(\dfase)\/([^/?#]+)/i);
  if (match) return `${match[1]} ${match[2].replace("fase", ".a fase")} - ${decodeURIComponent(match[3])}`;
  return exam.batchIndex ? `#${exam.batchIndex} - ${exam.filename}` : exam.filename;
}

function inferSubject(exam: Exam) {
  const text = `${exam.filename} ${exam.sourceUrl || ""}`.toLowerCase();
  if (text.includes("historia")) return "História";
  if (text.includes("portugues")) return "Português";
  if (text.includes("matemat")) return "Matemática";
  return "Exame";
}

function progressFor(exam: Exam) {
  if (exam.status === "completed" || exam.status === "completed_with_warnings") return 100;
  if (exam.status === "processing") return 62;
  if (exam.status === "queued" || exam.status === "pending") return 0;
  if (exam.status === "needs_review" || exam.status === "partial_failed") return 85;
  if (exam.status === "error") return 0;
  return 0;
}

function dayKey(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "unknown" : date.toISOString().slice(0, 10);
}

function formatDay(value?: string) {
  if (!value) return "Sem data";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sem data";
  return new Intl.DateTimeFormat("pt-PT", { day: "numeric", month: "long", year: "numeric" }).format(date);
}

function formatCompactDateTime(value?: string) {
  if (!value) return "-";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "-";
  const day = new Intl.DateTimeFormat("pt-PT", { day: "2-digit", month: "2-digit" }).format(date);
  const time = new Intl.DateTimeFormat("pt-PT", { hour: "2-digit", minute: "2-digit" }).format(date);
  return (
    <>
      <span className="block whitespace-nowrap">{day}</span>
      <span className="block whitespace-nowrap">{time}</span>
    </>
  );
}

function getDurationMs(exam: Exam) {
  if (typeof exam.durationMs === "number") return exam.durationMs;
  if (!exam.startedAt) return undefined;
  const end = exam.completedAt || (terminalStatuses.has(exam.status) ? exam.updatedAt : undefined);
  if (!end) return undefined;
  const duration = new Date(end).getTime() - new Date(exam.startedAt).getTime();
  return Number.isFinite(duration) && duration >= 0 ? duration : undefined;
}

function formatDuration(ms?: number) {
  if (!ms) return "-";
  const totalSeconds = Math.round(ms / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes >= 60) return `${Math.floor(minutes / 60)}h ${minutes % 60}m`;
  return `${minutes}m ${seconds}s`;
}

function avg(values: number[]) {
  return values.reduce((sum, value) => sum + value, 0) / values.length;
}

function formatNumber(value: number) {
  return new Intl.NumberFormat("pt-PT").format(value);
}

function filenameFromDisposition(disposition: string | null) {
  if (!disposition) return "";
  return disposition.match(/filename="([^"]+)"/)?.[1] || "";
}

function SearchIcon() {
  return (
    <svg className="pointer-events-none absolute left-4 top-1/2 h-5 w-5 -translate-y-1/2 text-[#7a87a3]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="11" cy="11" r="7" />
      <path d="m20 20-3.5-3.5" />
    </svg>
  );
}

function DownloadIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M12 3v12" />
      <path d="m7 10 5 5 5-5" />
      <path d="M5 21h14" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M3 6h18" />
      <path d="M8 6V4h8v2" />
      <path d="m9 11 .5 8M15 11l-.5 8M6 6l1 15h10l1-15" />
    </svg>
  );
}

function FileIcon() {
  return (
    <svg className="h-5 w-5 shrink-0 text-[#0b66f6]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h4" />
    </svg>
  );
}

function MetricIcon({ icon }: { icon: "file" | "check" | "clock" | "tokens" }) {
  if (icon === "check") {
    return (
      <svg className="h-10 w-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <path d="m8 12 3 3 5-6" />
      </svg>
    );
  }
  if (icon === "clock") {
    return (
      <svg className="h-10 w-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7v6l4 2" />
      </svg>
    );
  }
  if (icon === "tokens") {
    return (
      <svg className="h-10 w-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <ellipse cx="12" cy="5" rx="7" ry="3" />
        <path d="M5 5v6c0 1.7 3.1 3 7 3s7-1.3 7-3V5" />
        <path d="M5 11v6c0 1.7 3.1 3 7 3s7-1.3 7-3v-6" />
      </svg>
    );
  }
  return (
    <svg className="h-10 w-10" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
      <path d="M9 13h6M9 17h4" />
    </svg>
  );
}
