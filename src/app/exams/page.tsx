import ExamList from '@/components/ExamList';
import Link from 'next/link';

export default function ExamsPage() {
  return (
    <div className="min-h-screen bg-slate-950 px-4 py-6 text-slate-100 sm:px-6 lg:px-8">
      <main className="mx-auto max-w-6xl">
        <Link href="/" className="text-blue-300 hover:text-blue-200 hover:underline text-sm">
          &larr; Voltar
        </Link>
        <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between mt-4 mb-6">
          <div>
            <h1 className="text-2xl font-bold text-white">Exames</h1>
            <p className="text-sm text-slate-400">
              Histórico de processamento, duração média e uso de tokens.
            </p>
          </div>
          <a
            href="/api/exams/export-all"
            download
            className="inline-flex items-center justify-center px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-md hover:bg-blue-700 transition-colors"
          >
            Download All
          </a>
        </div>
        <ExamList />
      </main>
    </div>
  );
}
