"use client";

import { useCallback, useState } from "react";

export default function UploadDropzone() {
  const [status, setStatus] = useState<"idle" | "uploading" | "done" | "error">("idle");
  const [message, setMessage] = useState("");
  const [dragOver, setDragOver] = useState(false);

  const upload = useCallback(async (file: File) => {
    setStatus("uploading");
    setMessage("");
    const formData = new FormData();
    formData.append("file", file);
    try {
      const res = await fetch("/api/exams/upload", { method: "POST", body: formData });
      const data = await res.json();
      if (res.ok) {
        setStatus("done");
        setMessage(`Exame ${data.exam_id} em processamento.`);
      } else {
        setStatus("error");
        setMessage(data.error || "Erro no upload.");
      }
    } catch {
      setStatus("error");
      setMessage("Erro de rede.");
    }
  }, []);

  const handleDrop = (event: React.DragEvent) => {
    event.preventDefault();
    setDragOver(false);
    const file = event.dataTransfer.files[0];
    if (file?.name.toLowerCase().endsWith(".pdf")) upload(file);
    else {
      setStatus("error");
      setMessage("Apenas ficheiros PDF.");
    }
  };

  const handleChange = (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    if (file) upload(file);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        setDragOver(true);
      }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`flex min-h-[430px] flex-col items-center justify-center rounded-lg border-2 border-dashed px-8 py-12 text-center transition ${
        dragOver ? "border-[#0b66f6] bg-[#eef5ff]" : "border-[#b8c5d8] bg-white hover:border-[#0b66f6]"
      }`}
    >
      <svg className="h-20 w-20 text-[#0b66f6]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.8">
        <path d="M12 19V9" />
        <path d="m7 14 5-5 5 5" />
        <path d="M20 16.5a4.5 4.5 0 0 0-3.7-7.1A6 6 0 0 0 4.9 11.1 4 4 0 0 0 5 19h3" />
      </svg>
      <p className="mt-9 text-2xl font-bold tracking-[-0.03em] text-[#07122f]">Arraste o PDF para aqui</p>
      <p className="mt-5 text-lg text-[#53617f]">ou</p>
      <input type="file" accept=".pdf" onChange={handleChange} className="hidden" id="file-input" />
      <label
        htmlFor="file-input"
        className="mt-6 inline-flex h-16 cursor-pointer items-center justify-center rounded-md bg-[#0b66f6] px-12 text-lg font-semibold text-white shadow-[0_18px_40px_rgba(11,102,246,0.18)] transition hover:bg-[#0052df]"
      >
        Selecionar ficheiro
      </label>
      <p className="mt-8 text-lg text-[#53617f]">Apenas PDF&nbsp;&nbsp;·&nbsp;&nbsp;Máx. 100MB</p>
      {message && (
        <p
          className={`mt-6 rounded-md px-4 py-3 text-sm font-medium ${
            status === "error"
              ? "bg-red-50 text-red-700"
              : status === "done"
                ? "bg-emerald-50 text-emerald-700"
                : "bg-blue-50 text-[#0b66f6]"
          }`}
        >
          {status === "uploading" ? "A enviar..." : message}
        </p>
      )}
      {status === "uploading" && !message && (
        <p className="mt-6 rounded-md bg-blue-50 px-4 py-3 text-sm font-medium text-[#0b66f6]">A enviar...</p>
      )}
    </div>
  );
}
