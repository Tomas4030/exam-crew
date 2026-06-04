import { NextResponse } from 'next/server';
import path from 'path';
import { rm } from 'fs/promises';
import { deleteJobs } from '@/lib/storage';

type DeleteSelectedRequest = {
  ids?: string[];
};

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as DeleteSelectedRequest;
  const ids = [...new Set((body.ids || []).filter(id => typeof id === 'string' && /^exam_[a-zA-Z0-9_]+$/.test(id)))];

  if (!ids.length) {
    return NextResponse.json({ error: 'No exams selected' }, { status: 400 });
  }

  const dataDir = path.join(process.cwd(), 'data');
  const targets = ids.flatMap(id => [
    path.join(dataDir, 'uploads', `${id}.pdf`),
    path.join(dataDir, 'extracted', id),
    path.join(dataDir, 'output', id),
    path.join(dataDir, 'output', `${id}.json`),
    path.join(dataDir, `progress_${id}.json`),
  ]);

  await Promise.all(targets.map(target => rm(target, { recursive: true, force: true })));
  const deletedJobs = await deleteJobs(ids);

  return NextResponse.json({ deletedJobs, requested: ids.length });
}
