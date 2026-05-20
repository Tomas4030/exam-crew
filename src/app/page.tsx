import Link from 'next/link';

export default function Home() {
  return (
    <div className="min-h-screen flex flex-col items-center justify-center p-8">
      <h1 className="text-4xl font-bold mb-4">ExamCrew</h1>
      <p className="text-lg text-gray-600 mb-8 text-center max-w-md">
        Processamento inteligente de exames com IA. Faz upload de um PDF e obtém resultados estruturados.
      </p>
      <div className="flex gap-4">
        <Link href="/upload" className="px-6 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700">
          Upload de Exame
        </Link>
        <Link href="/exams" className="px-6 py-3 border border-gray-300 rounded-lg hover:bg-gray-50">
          Ver Exames
        </Link>
      </div>
    </div>
  );
}
