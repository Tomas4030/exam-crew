'use client';

import { useState, useEffect } from 'react';

interface StatusData {
  id: string;
  status: string;
  error?: string;
}

export default function ProcessingStatus({ examId }: { examId: string }) {
  const [data, setData] = useState<StatusData | null>(null);

  useEffect(() => {
    const fetchStatus = () =>
      fetch(`/api/exams/${examId}/status`).then(r => r.json()).then(setData).catch(() => {});
    fetchStatus();
    const interval = setInterval(fetchStatus, 3000);
    return () => clearInterval(interval);
  }, [examId]);

  if (!data) return <p className="text-gray-500">A carregar...</p>;

  const colors: Record<string, string> = {
    pending: 'text-yellow-600',
    processing: 'text-blue-600',
    completed: 'text-green-600',
    error: 'text-red-600',
  };

  return (
    <div className="p-4 border rounded-lg">
      <p className="text-sm text-gray-500">Estado</p>
      <p className={`text-lg font-semibold ${colors[data.status] || ''}`}>{data.status}</p>
      {data.error && <p className="mt-2 text-sm text-red-500">{data.error}</p>}
    </div>
  );
}
