"use client";

import { useState } from "react";
import Link from "next/link";
import AppShell from "@/components/AppShell";

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
      if (!res.ok) {
        setStatus("error");
        setMessage(data.error || "Erro.");
        return;
      }
      setStatus("done");
      setMessage(`Batch ${data.batch_id}: ${data.total} exames em fila.`);
    } catch {
      setStatus("error");
      setMessage("Erro de rede.");
    }
  }

  return (
    <AppShell active="upload">
      <main className="mx-auto max-w-7xl px-6 py-14 lg:px-10">
        <div className="mb-12">
          <h1 className="text-4xl font-bold tracking-[-0.04em] text-[#07122f]">Upload de exame</h1>
          <p className="mt-5 text-xl text-[#53617f]">
            Cola vários PDFs por URL para criar uma fila de processamento.
          </p>
        </div>

        <section className="rounded-lg border border-[#dce5f2] bg-white p-8 shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
          <div className="mb-8 flex gap-10 border-b border-[#dce5f2]">
            <Link href="/upload" className="px-3 pb-5 text-lg font-semibold text-[#53617f] transition hover:text-[#0b66f6]">
              Upload de PDF
            </Link>
            <span className="border-b-3 border-[#0b66f6] px-3 pb-5 text-lg font-semibold text-[#0b66f6]">
              Por URL
            </span>
          </div>

          <textarea
            value={text}
            onChange={(event) => setText(event.target.value)}
            className="h-80 w-full resize-y rounded-md border border-[#b8c5d8] bg-[#fbfdff] p-5 font-mono text-sm leading-6 text-[#07122f] shadow-inner transition placeholder:text-[#7a87a3] focus:border-[#0b66f6] focus:ring-4 focus:ring-blue-100"
            placeholder={"https://.../exame1.pdf\nhttps://.../exame2.pdf"}
          />
          <div className="mt-6 flex flex-col gap-4 sm:flex-row sm:items-center">
            <button
              onClick={submit}
              disabled={status === "sending" || !text.trim()}
              className="inline-flex h-14 items-center justify-center rounded-md bg-[#0b66f6] px-8 text-base font-semibold text-white shadow-[0_18px_40px_rgba(11,102,246,0.18)] transition hover:bg-[#0052df] disabled:cursor-not-allowed disabled:bg-[#b8c5d8]"
            >
              {status === "sending" ? "A criar fila..." : "Criar fila"}
            </button>
            {message && (
              <p className={`text-sm font-medium ${status === "error" ? "text-red-600" : "text-emerald-700"}`}>
                {message}
              </p>
            )}
          </div>
        </section>
      </main>
    </AppShell>
  );
}
