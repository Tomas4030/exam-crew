"use client";

import { useEffect, useState } from "react";

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
  { id: "extract", label: "Leitura de páginas", doneText: "PDF renderizado." },
  { id: "vision", label: "Separação de perguntas", doneText: "Perguntas detetadas." },
  { id: "scoring", label: "Extração de cotações", doneText: "Cotações estruturadas." },
  { id: "assemble", label: "Geração de estrutura", doneText: "JSON estruturado." },
  { id: "crop", label: "Extração de imagens", doneText: "Imagens e textos preparados." },
  { id: "validate", label: "Validação", doneText: "Regras verificadas." },
  { id: "audit", label: "Auditoria", doneText: "Qualidade validada." },
  { id: "done", label: "Exportação", doneText: "Resultado pronto." },
];

export default function ProcessingStatus({ examId }: { examId: string }) {
  const [data, setData] = useState<StatusData | null>(null);

  useEffect(() => {
    const fetchStatus = () =>
      fetch(`/api/exams/${examId}/status`).then((response) => response.json()).then((next) => {
        setData(next);
        if (["completed", "error", "completed_with_warnings", "needs_review", "partial_failed"].includes(next.status)) {
          clearInterval(intervalId);
        }
      }).catch(() => {});
    const intervalId = setInterval(fetchStatus, 2000);
    fetchStatus();
    return () => clearInterval(intervalId);
  }, [examId]);

  if (!data) {
    return (
      <div className="rounded-lg border border-[#dce5f2] bg-white p-6 text-[#53617f]">
        A carregar...
      </div>
    );
  }

  if (data.status === "error") {
    return (
      <StatusPanel tone="red" title="Erro no processamento" message={data.error || "O processamento falhou."} />
    );
  }

  if (data.status === "needs_review" || data.status === "partial_failed") {
    return (
      <StatusPanel tone="amber" title="Revisão necessária" message={data.progress?.message || "A auditoria encontrou pontos a rever."} />
    );
  }

  if (data.status === "completed" || data.status === "completed_with_warnings") {
    return (
      <StatusPanel tone="green" title="Processamento concluído" message={data.status === "completed_with_warnings" ? "Resultado pronto com avisos." : "Resultado pronto para exportar."} />
    );
  }

  const progress = data.progress;
  const currentStepIdx = progress ? Math.max(0, STEPS.findIndex((step) => step.id === progress.step)) : 0;

  return (
    <div className="rounded-lg border border-[#dce5f2] bg-white p-8 shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
      <h2 className="text-xl font-bold tracking-[-0.03em] text-[#07122f]">Progresso do pipeline</h2>
      <div className="mt-8 space-y-0">
        {STEPS.map((step, index) => {
          const isDone = index < currentStepIdx || progress?.step === "done";
          const isCurrent = index === currentStepIdx && progress?.step !== "done";
          return (
            <div key={step.id} className="grid grid-cols-[42px_minmax(0,1fr)] gap-4">
              <div className="flex flex-col items-center">
                <div className={`flex h-9 w-9 items-center justify-center rounded-full border-3 ${
                  isDone ? "border-emerald-500 text-emerald-600" : isCurrent ? "border-[#0b66f6] text-[#0b66f6]" : "border-[#b8c5d8] text-[#b8c5d8]"
                }`}>
                  {isDone ? <CheckIcon /> : isCurrent ? <span className="h-2.5 w-2.5 rounded-full bg-current" /> : null}
                </div>
                {index < STEPS.length - 1 && <div className="h-14 w-px bg-[#dce5f2]" />}
              </div>
              <div className="pb-7">
                <h3 className="text-lg font-bold tracking-[-0.02em] text-[#07122f]">{step.label}</h3>
                <p className={`mt-1 text-base ${isCurrent ? "text-[#0b66f6]" : "text-[#53617f]"}`}>
                  {isCurrent ? progress?.message || progress?.label || "A processar..." : isDone ? step.doneText : "Aguardando conclusão da etapa."}
                </p>
              </div>
            </div>
          );
        })}
      </div>
      <div className="mt-2">
        <div className="mb-2 flex justify-between text-sm font-medium text-[#53617f]">
          <span>{progress?.label || "A processar..."}</span>
          <span>{progress?.pct || 0}%</span>
        </div>
        <div className="h-2 overflow-hidden rounded-full bg-[#e8eef7]">
          <div className="h-full rounded-full bg-[#0b66f6] transition-all duration-700" style={{ width: `${progress?.pct || 0}%` }} />
        </div>
      </div>
    </div>
  );
}

function StatusPanel({ tone, title, message }: { tone: "green" | "amber" | "red"; title: string; message: string }) {
  const styles = {
    green: "border-emerald-200 bg-emerald-50 text-emerald-700",
    amber: "border-amber-200 bg-amber-50 text-amber-700",
    red: "border-red-200 bg-red-50 text-red-700",
  }[tone];

  return (
    <div className={`rounded-lg border p-6 ${styles}`}>
      <div className="flex items-start gap-4">
        <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-full border-2 border-current">
          {tone === "green" ? <CheckIcon /> : <span className="text-lg font-bold">!</span>}
        </div>
        <div>
          <h2 className="text-lg font-bold">{title}</h2>
          <p className="mt-1 text-sm">{message}</p>
        </div>
      </div>
    </div>
  );
}

function CheckIcon() {
  return (
    <svg className="h-5 w-5" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3">
      <path d="m6 12 4 4 8-8" />
    </svg>
  );
}
