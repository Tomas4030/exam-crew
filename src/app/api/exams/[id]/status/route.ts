import { NextResponse } from 'next/server';
import { getJob } from '@/lib/storage';
import { readFileSync } from 'fs';
import path from 'path';

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const job = await getJob(id);
  if (!job) {
    return NextResponse.json({ error: 'Not found' }, { status: 404 });
  }

  // Read progress file if processing
  let progress = null;
  if (job.status === 'processing') {
    try {
      const file = path.join(process.cwd(), 'data', `progress_${id}.json`);
      progress = JSON.parse(readFileSync(file, 'utf-8'));
    } catch {}
  }

  return NextResponse.json({
    id: job.id,
    status: job.status,
    error: job.error,
    progress,
  });
}
