import ExamList from '@/components/ExamList';
import Link from 'next/link';

export default function ExamsPage() {
  return (
    <div className="min-h-screen p-8 max-w-2xl mx-auto">
      <Link href="/" className="text-blue-600 hover:underline text-sm">&larr; Voltar</Link>
      <div className="flex items-center justify-between mt-4 mb-6">
        <h1 className="text-2xl font-bold">Exames</h1>
        <a
          href="/api/exams/export-all"
          download
          className="px-4 py-2 bg-blue-600 text-white text-sm font-medium rounded-lg hover:bg-blue-700 transition-colors"
        >
          ⬇ Download All
        </a>
      </div>
      <ExamList />
    </div>
  );
}
