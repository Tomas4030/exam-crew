'use client';

import { useState, useEffect } from 'react';
import Link from 'next/link';

interface Exam {
  id: string;
  filename: string;
  status: string;
  createdAt: string;
}

const statusColors: Record<string, string> = {
  pending: 'bg-yellow-100 text-yellow-800',
  processing: 'bg-blue-100 text-blue-800',
  completed: 'bg-green-100 text-green-800',
  error: 'bg-red-100 text-red-800',
};

export default function ExamList() {
  const [exams, setExams] = useState<Exam[]>([]);

  useEffect(() => {
    const fetchExams = () => fetch('/api/exams').then(r => r.json()).then(setExams).catch(() => {});
    fetchExams();
    const interval = setInterval(fetchExams, 5000);
    return () => clearInterval(interval);
  }, []);

  if (exams.length === 0) return <p className="text-gray-500">Nenhum exame encontrado.</p>;

  return (
    <ul className="space-y-3">
      {exams.map(exam => (
        <li key={exam.id}>
          <Link href={`/exams/${exam.id}`} className="block p-4 border rounded-lg hover:bg-gray-50 transition-colors">
            <div className="flex justify-between items-center">
              <span className="font-medium">{exam.filename}</span>
              <span className={`px-2 py-1 rounded text-xs font-medium ${statusColors[exam.status] || ''}`}>
                {exam.status}
              </span>
            </div>
            <p className="text-sm text-gray-500 mt-1">{new Date(exam.createdAt).toLocaleString()}</p>
          </Link>
        </li>
      ))}
    </ul>
  );
}
