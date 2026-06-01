import { NextResponse } from 'next/server';
import { writeFile, mkdir } from 'fs/promises';
import path from 'path';
import { createJob } from '@/lib/storage';
import { enqueuePipeline } from '@/lib/pipelineQueue';
import { ExamJob } from '@/lib/types';

export const runtime = 'nodejs';

export async function POST(request: Request) {
  const formData = await request.formData();
  const file = formData.get('file') as File | null;

  if (!file || !file.name.endsWith('.pdf')) {
    return NextResponse.json({ error: 'PDF file required' }, { status: 400 });
  }

  const examId = `exam_${Date.now()}_${Math.random().toString(36).slice(2, 8)}`;
  const uploadsDir = path.join(process.cwd(), 'data', 'uploads');
  await mkdir(uploadsDir, { recursive: true });

  const filePath = path.join(uploadsDir, `${examId}.pdf`);
  await writeFile(filePath, Buffer.from(await file.arrayBuffer()));

  const job: ExamJob = {
    id: examId,
    filename: file.name,
    status: 'queued',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  await createJob(job);

  enqueuePipeline({ examId, pdfPath: filePath });

  return NextResponse.json({ exam_id: examId, status: 'queued' });
}
