'use client';

import { useState, useEffect } from 'react';
import { useParams } from 'next/navigation';
import Link from 'next/link';
import ProcessingStatus from '@/components/ProcessingStatus';

export default function ExamDetailPage() {
  const { id } = useParams<{ id: string }>();
  const [status, setStatus] = useState<string>('');
  const [auditReason, setAuditReason] = useState<string>('');

  useEffect(() => {
    const check = () =>
      fetch(`/api/exams/${id}/status`).then(r => r.json()).then(d => {
        setStatus(d.status);
        if (d.status === 'needs_review') {
          setAuditReason(d.error || d.progress?.message || '');
        }
        if (['completed', 'completed_with_warnings', 'needs_review', 'partial_failed'].includes(d.status)) {
          clearInterval(interval);
        }
      }).catch(() => {});
    check();
    const interval = setInterval(check, 3000);
    return () => clearInterval(interval);
  }, [id]);

  const showActions = ['completed', 'completed_with_warnings', 'needs_review'].includes(status);
  const isNeedsReview = status === 'needs_review';

  return (
    <div className="min-h-screen p-8 max-w-3xl mx-auto">
      <Link href="/exams" className="text-blue-600 hover:underline text-sm">&larr; Voltar</Link>
      <h1 className="text-2xl font-bold mt-4 mb-6">Exame: {id}</h1>
      <ProcessingStatus examId={id} />
      {isNeedsReview && (
        <div className="mt-4 rounded-lg border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800">
          <strong>Precisa de revisão.</strong>{' '}
          {auditReason
            ? auditReason
            : 'A auditoria de qualidade encontrou problemas que requerem verificação manual. Podes inspecionar o JSON e as imagens abaixo.'}
        </div>
      )}
      {showActions && (
        <div className="mt-6 flex flex-wrap gap-3">
          <a
            href={`/api/exams/${id}/export`}
            download
            className="inline-flex items-center gap-2 px-5 py-3 bg-blue-600 text-white rounded-lg hover:bg-blue-700 font-medium"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path fillRule="evenodd" d="M3 17a1 1 0 011-1h12a1 1 0 110 2H4a1 1 0 01-1-1zm3.293-7.707a1 1 0 011.414 0L9 10.586V3a1 1 0 112 0v7.586l1.293-1.293a1 1 0 111.414 1.414l-3 3a1 1 0 01-1.414 0l-3-3a1 1 0 010-1.414z" clipRule="evenodd" />
            </svg>
            Download ZIP
          </a>
          <Link
            href={`/exams/${id}/preview`}
            className="inline-flex items-center gap-2 px-5 py-3 bg-green-600 text-white rounded-lg hover:bg-green-700 font-medium"
          >
            <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
              <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
              <path fillRule="evenodd" d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z" clipRule="evenodd" />
            </svg>
            {isNeedsReview ? 'Inspecionar Quiz' : 'Preview Quiz'}
          </Link>
          {!isNeedsReview && (
            <a
              href={`/api/exams/${id}/export-quiz`}
              download
              className="inline-flex items-center gap-2 px-5 py-3 bg-purple-600 text-white rounded-lg hover:bg-purple-700 font-medium"
            >
              <svg xmlns="http://www.w3.org/2000/svg" className="h-5 w-5" viewBox="0 0 20 20" fill="currentColor">
                <path fillRule="evenodd" d="M12.316 3.051a1 1 0 01.633 1.265l-4 12a1 1 0 11-1.898-.632l4-12a1 1 0 011.265-.633zM5.707 6.293a1 1 0 010 1.414L3.414 10l2.293 2.293a1 1 0 11-1.414-1.414l-3-3a1 1 0 010-1.414l3-3a1 1 0 011.414 0zm8.586 0a1 1 0 011.414 0l3 3a1 1 0 010 1.414l-3 3a1 1 0 11-1.414-1.414L16.586 10l-2.293-2.293a1 1 0 010-1.414z" clipRule="evenodd" />
              </svg>
              Quiz HTML
            </a>
          )}
        </div>
      )}
    </div>
  );
}
