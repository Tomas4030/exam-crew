'use client';

import { useState, useCallback } from 'react';

export default function UploadDropzone() {
  const [status, setStatus] = useState<'idle' | 'uploading' | 'done' | 'error'>('idle');
  const [message, setMessage] = useState('');
  const [dragOver, setDragOver] = useState(false);

  const upload = useCallback(async (file: File) => {
    setStatus('uploading');
    const formData = new FormData();
    formData.append('file', file);
    try {
      const res = await fetch('/api/exams/upload', { method: 'POST', body: formData });
      const data = await res.json();
      if (res.ok) {
        setStatus('done');
        setMessage(`Exam ${data.exam_id} em processamento.`);
      } else {
        setStatus('error');
        setMessage(data.error || 'Erro no upload');
      }
    } catch {
      setStatus('error');
      setMessage('Erro de rede');
    }
  }, []);

  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file?.name.endsWith('.pdf')) upload(file);
    else setMessage('Apenas ficheiros PDF');
  };

  const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) upload(file);
  };

  return (
    <div
      onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
      onDragLeave={() => setDragOver(false)}
      onDrop={handleDrop}
      className={`border-2 border-dashed rounded-xl p-12 text-center cursor-pointer transition-colors ${
        dragOver ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'
      }`}
    >
      <p className="text-lg text-gray-600 mb-4">Arrasta um PDF aqui ou clica para selecionar</p>
      <input type="file" accept=".pdf" onChange={handleChange} className="hidden" id="file-input" />
      <label htmlFor="file-input" className="px-4 py-2 bg-blue-600 text-white rounded-lg cursor-pointer hover:bg-blue-700">
        Selecionar PDF
      </label>
      {status === 'uploading' && <p className="mt-4 text-blue-600">A enviar...</p>}
      {status === 'done' && <p className="mt-4 text-green-600">{message}</p>}
      {status === 'error' && <p className="mt-4 text-red-600">{message}</p>}
    </div>
  );
}
