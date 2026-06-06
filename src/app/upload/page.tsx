import Link from "next/link";
import AppShell from "@/components/AppShell";
import UploadDropzone from "@/components/UploadDropzone";

export default function UploadPage() {
  return (
    <AppShell active="upload">
      <main className="mx-auto max-w-7xl px-6 py-14 lg:px-10">
        <div className="mb-12">
          <h1 className="text-4xl font-bold tracking-[-0.04em] text-[#07122f]">Upload de exame</h1>
          <p className="mt-5 text-xl text-[#53617f]">
            Envie um PDF ou carregue por URL para iniciar o processamento.
          </p>
        </div>

        <div className="grid gap-8 lg:grid-cols-[minmax(0,1.7fr)_minmax(360px,1fr)]">
          <section className="rounded-lg border border-[#dce5f2] bg-white p-8 shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
            <div className="mb-8 flex gap-10 border-b border-[#dce5f2]">
              <span className="border-b-3 border-[#0b66f6] px-3 pb-5 text-lg font-semibold text-[#0b66f6]">
                Upload de PDF
              </span>
              <Link
                href="/preload"
                className="px-3 pb-5 text-lg font-semibold text-[#53617f] transition hover:text-[#0b66f6]"
              >
                Por URL
              </Link>
            </div>
            <UploadDropzone />
          </section>

          <aside className="rounded-lg border border-[#dce5f2] bg-white p-9 shadow-[0_18px_55px_rgba(25,45,78,0.05)]">
            <h2 className="text-2xl font-bold tracking-[-0.03em] text-[#07122f]">O que acontece depois?</h2>
            <div className="mt-10 space-y-10">
              <InfoCard icon="lock" title="PDFs protegidos são encriptados" body="A sua palavra-passe nunca é guardada." />
              <InfoCard icon="camera" title="Resultados com elevada qualidade" body="Extrações precisas graças a digitalizações nítidas e inteligentes." />
              <InfoCard icon="clock" title="Processamento em segundo plano" body="Pode fechar a página e voltar mais tarde." />
            </div>
          </aside>
        </div>
      </main>
    </AppShell>
  );
}

function InfoCard({ icon, title, body }: { icon: "lock" | "camera" | "clock"; title: string; body: string }) {
  return (
    <div className="grid grid-cols-[56px_minmax(0,1fr)] gap-5">
      <div className="flex h-14 w-14 items-center justify-center rounded-md bg-[#eaf2ff] text-[#0b66f6]">
        <InfoIcon icon={icon} />
      </div>
      <div>
        <h3 className="text-lg font-bold tracking-[-0.02em] text-[#07122f]">{title}</h3>
        <p className="mt-2 text-lg leading-snug text-[#53617f]">{body}</p>
      </div>
    </div>
  );
}

function InfoIcon({ icon }: { icon: "lock" | "camera" | "clock" }) {
  if (icon === "lock") {
    return (
      <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <rect x="5" y="10" width="14" height="10" rx="2" />
        <path d="M8 10V7a4 4 0 0 1 8 0v3" />
        <path d="M12 14v3" />
      </svg>
    );
  }
  if (icon === "camera") {
    return (
      <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
        <path d="M6 8h3l1.5-2h3L15 8h3a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2Z" />
        <circle cx="12" cy="14" r="3" />
      </svg>
    );
  }
  return (
    <svg className="h-8 w-8" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v6l4 2" />
    </svg>
  );
}
