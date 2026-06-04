import { readFile, writeFile, mkdir } from 'fs/promises';
import path from 'path';
import { ExamJob } from './types';

const DATA_DIR = path.join(process.cwd(), 'data');
const JOBS_FILE = path.join(DATA_DIR, 'jobs.json');

async function ensureDataDir() {
  await mkdir(DATA_DIR, { recursive: true });
}

export async function getJobs(): Promise<ExamJob[]> {
  try {
    const data = await readFile(JOBS_FILE, 'utf-8');
    return JSON.parse(data);
  } catch {
    return [];
  }
}

export async function getJob(id: string): Promise<ExamJob | undefined> {
  const jobs = await getJobs();
  return jobs.find(j => j.id === id);
}

export async function updateJob(id: string, updates: Partial<ExamJob>): Promise<void> {
  const jobs = await getJobs();
  const idx = jobs.findIndex(j => j.id === id);
  if (idx !== -1) {
    jobs[idx] = { ...jobs[idx], ...updates, updatedAt: new Date().toISOString() };
    await ensureDataDir();
    await writeFile(JOBS_FILE, JSON.stringify(jobs, null, 2));
  }
}

export async function createJob(job: ExamJob): Promise<void> {
  const jobs = await getJobs();
  jobs.push(job);
  await ensureDataDir();
  await writeFile(JOBS_FILE, JSON.stringify(jobs, null, 2));
}

export async function deleteJobs(ids: string[]): Promise<number> {
  const idSet = new Set(ids);
  if (!idSet.size) return 0;

  const jobs = await getJobs();
  const nextJobs = jobs.filter(job => !idSet.has(job.id));
  const deleted = jobs.length - nextJobs.length;

  if (deleted > 0) {
    await ensureDataDir();
    await writeFile(JOBS_FILE, JSON.stringify(nextJobs, null, 2));
  }

  return deleted;
}
