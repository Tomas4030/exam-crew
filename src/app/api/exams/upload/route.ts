import { NextResponse } from 'next/server';
import { writeFile, mkdir } from 'fs/promises';
import path from 'path';
import { createJob, updateJob } from '@/lib/storage';
import { runPipeline } from '@/lib/process';
import { ExamJob } from '@/lib/types';

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
  const buffer = Buffer.from(await file.arrayBuffer());
  await writeFile(filePath, buffer);

  const job: ExamJob = {
    id: examId,
    filename: file.name,
    status: 'processing',
    createdAt: new Date().toISOString(),
    updatedAt: new Date().toISOString(),
  };
  await createJob(job);

  // Launch pipeline in background
  runPipeline(filePath, examId).then(async (result) => {
    if (result.success) {
      await updateJob(examId, { status: 'completed' });
    } else {
      await updateJob(examId, { status: 'error', error: result.error });
    }
  });

  return NextResponse.json({ exam_id: examId, status: 'processing' });
}
