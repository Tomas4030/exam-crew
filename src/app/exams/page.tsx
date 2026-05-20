import ExamList from '@/components/ExamList';
import Link from 'next/link';

export default function ExamsPage() {
  return (
    <div className="min-h-screen p-8 max-w-2xl mx-auto">
      <Link href="/" className="text-blue-600 hover:underline text-sm">&larr; Voltar</Link>
      <h1 className="text-2xl font-bold mt-4 mb-6">Exames</h1>
      <ExamList />
    </div>
  );
}
