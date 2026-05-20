import UploadDropzone from '@/components/UploadDropzone';
import Link from 'next/link';

export default function UploadPage() {
  return (
    <div className="min-h-screen p-8 max-w-2xl mx-auto">
      <Link href="/" className="text-blue-600 hover:underline text-sm">&larr; Voltar</Link>
      <h1 className="text-2xl font-bold mt-4 mb-6">Upload de Exame</h1>
      <UploadDropzone />
    </div>
  );
}
