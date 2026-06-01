"use client";

import { useState } from "react";
import Link from "next/link";

export default function PreloadPage() {
  const [text, setText] = useState("");
  const [status, setStatus] = useState<"idle" | "sending" | "done" | "error">("idle");
  const [message, setMessage] = useState("");

  async function submit() {
    setStatus("sending");
    setMessage("");
    try {
      const res = await fetch("/api/exams/preload", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ text }),
      });
      const data = await res.json();
      if (!res.ok) { setStatus("error"); setMessage(data.error || "Erro."); return; }
      setStatus("done");
      setMessage(`Batch ${data.batch_id}: ${data.total} exames em fila.`);
    } catch {
      setStatus("error");
      setMessage("Erro de rede.");
    }
  }

  return (
    <div className="min-h-screen p-8 max-w-3xl mx-auto">
      <Link href="/" className="text-blue-600 hover:underline text-sm">← Voltar</Link>
      <h1 className="text-2xl font-bold mt-4 mb-2">Preload de PDFs por URL</h1>
      <p className="text-slate-600 mb-6">
        Cola um URL de PDF por linha. O sistema descarrega cada PDF e processa automaticamente um de cada vez.
      </p>
      <textarea
        value={text}
        onChange={(e) => setText(e.target.value)}
        className="w-full h-72 rounded-lg border border-slate-300 p-3 font-mono text-sm"
        placeholder={"https://.../exame1.pdf\nhttps://.../exame2.pdf"}
      />
      <button
        onClick={submit}
        disabled={status === "sending" || !text.trim()}
        className="mt-4 px-5 py-2.5 rounded-lg bg-blue-600 text-white font-semibold disabled:opacity-50"
      >
        {status === "sending" ? "A criar fila..." : "Criar fila"}
      </button>
      {message && (
        <p className={`mt-4 ${status === "error" ? "text-red-600" : "text-green-700"}`}>
          {message}
        </p>
      )}
    </div>
  );
}
