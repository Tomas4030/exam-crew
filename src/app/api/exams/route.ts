import { NextResponse } from 'next/server';
import { getJobs } from '@/lib/storage';

export async function GET() {
  const jobs = await getJobs();
  return NextResponse.json(jobs);
}
