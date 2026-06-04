import { NextResponse } from 'next/server';
import { getJobs } from '@/lib/storage';

export async function GET() {
  const jobs = (await getJobs()).sort((a, b) =>
    new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
  return NextResponse.json(jobs);
}
