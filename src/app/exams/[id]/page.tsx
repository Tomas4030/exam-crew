'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import ProcessingStatus from '@/components/ProcessingStatus';
import JsonViewer from '@/components/JsonViewer';

export default function ExamDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [status, setStatus] = useState<string>('');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);

  useEffect(() => {
    const check = () =>
      fetch(`/api/exams/${id}/status`).then(r => r.json()).then(d => {
        setStatus(d.status);
        if (d.status === 'completed') {
          fetch(`/api/exams/${id}/result`).then(r => r.json()).then(setResult);
        }
      }).catch(() => {});
    check();
    const interval = setInterval(check, 3000);
    return () => clearInterval(interval);
  }, [id]);

  return (
    <div className="min-h-screen p-8 max-w-3xl mx-auto">
      <Link href="/exams" className="text-blue-600 hover:underline text-sm">&larr; Voltar</Link>
      <h1 className="text-2xl font-bold mt-4 mb-6">Exame: {id}</h1>
      <ProcessingStatus examId={id} />
      {status === 'completed' && result && (
        <div className="mt-6">
          <h2 className="text-lg font-semibold mb-3">Resultado</h2>
          <JsonViewer data={result} />
        </div>
      )}
    </div>
  );
}
