import AppShell from "@/components/AppShell";
import ExamList from "@/components/ExamList";

export default function ExamsPage() {
  return (
    <AppShell active="processamentos">
      <main className="mx-auto max-w-7xl px-6 py-12 lg:px-10">
        <div className="mb-10">
          <h1 className="text-4xl font-bold tracking-[-0.04em] text-[#07122f]">Processamentos</h1>
          <p className="mt-3 text-lg text-[#53617f]">
            Acompanhe o estado e os detalhes dos seus exames.
          </p>
        </div>
        <ExamList />
      </main>
    </AppShell>
  );
}
