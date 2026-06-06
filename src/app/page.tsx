import Link from "next/link";
import AppShell from "@/components/AppShell";

export default function Home() {
  return (
    <AppShell active="upload">
      <main className="mx-auto flex min-h-[calc(100vh-5rem)] max-w-7xl flex-col px-6 py-16 lg:px-10">
        <section className="flex flex-1 flex-col items-center justify-center text-center">
          <h1 className="text-7xl font-bold tracking-[-0.055em] text-[#0b66f6] sm:text-8xl">
            ExamCrew
          </h1>
          <p className="mt-8 max-w-2xl text-2xl leading-snug tracking-[-0.02em] text-[#3d4965]">
            Processamento estruturado de exames em PDF.
            <br />
            Faz upload, acompanha o pipeline e exporta resultados em JSON e ZIP.
          </p>
          <div className="mt-12 flex w-full max-w-3xl flex-col gap-5 sm:flex-row sm:justify-center">
            <Link
              href="/upload"
              className="inline-flex h-16 flex-1 items-center justify-center rounded-md bg-[#0b66f6] px-8 text-lg font-semibold text-white shadow-[0_18px_40px_rgba(11,102,246,0.22)] transition hover:bg-[#0052df]"
            >
              Upload de exame
            </Link>
            <Link
              href="/exams"
              className="inline-flex h-16 flex-1 items-center justify-center rounded-md border border-[#0b66f6] bg-white px-8 text-lg font-semibold text-[#0b66f6] transition hover:bg-[#eef5ff]"
            >
              Ver processamentos
            </Link>
            <Link
              href="/preload"
              className="inline-flex h-16 flex-1 items-center justify-center rounded-md border border-[#0b66f6] bg-white px-8 text-lg font-semibold text-[#0b66f6] transition hover:bg-[#eef5ff]"
            >
              Preload por URLs
            </Link>
          </div>
        </section>

        <section className="border-y border-[#d5deec] py-8">
          <div className="grid gap-6 text-[#3d4965] md:grid-cols-3 md:divide-x md:divide-[#cdd8e8]">
            <Feature icon="list" label="Separação de perguntas" />
            <Feature icon="image" label="Extração de imagens" />
            <Feature icon="file" label="Exportação JSON + ZIP" />
          </div>
        </section>
        <p className="py-9 text-center text-lg text-[#53617f]">
          Suporte para exames nacionais, PDFs multipágina e processamento em segundo plano.
        </p>
      </main>
    </AppShell>
  );
}

function Feature({ icon, label }: { icon: "list" | "image" | "file"; label: string }) {
  return (
    <div className="flex items-center justify-center gap-5 text-lg font-medium">
      <FeatureIcon icon={icon} />
      <span>{label}</span>
    </div>
  );
}

function FeatureIcon({ icon }: { icon: "list" | "image" | "file" }) {
  if (icon === "list") {
    return (
      <svg className="h-9 w-9 text-[#0b66f6]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M8 6h13M8 12h13M8 18h13" />
        <path d="M3 6h.01M3 12h.01M3 18h.01" strokeWidth="4" />
      </svg>
    );
  }
  if (icon === "image") {
    return (
      <svg className="h-9 w-9 text-[#0b66f6]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="4" y="3" width="16" height="18" rx="2" />
        <circle cx="9" cy="8" r="1.6" />
        <path d="m6 17 4.5-4.5 3 3L16 13l2 2" />
      </svg>
    );
  }
  return (
    <svg className="h-9 w-9 text-[#0b66f6]" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8Z" />
      <path d="M14 3v5h5" />
    </svg>
  );
}
