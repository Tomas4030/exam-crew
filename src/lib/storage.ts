import { readFile, writeFile, mkdir, rename } from 'fs/promises';
import path from 'path';
import { ExamJob } from './types';

const DATA_DIR = path.join(process.cwd(), 'data');
const JOBS_FILE = path.join(DATA_DIR, 'jobs.json');

async function ensureDataDir() {
  await mkdir(DATA_DIR, { recursive: true });
}

// In-process mutex: serializes every read-modify-write on jobs.json so two
// concurrent API requests can't clobber each other's updates.
let writeLock: Promise<void> = Promise.resolve();

function withLock<T>(fn: () => Promise<T>): Promise<T> {
  const result = writeLock.then(fn, fn);
  writeLock = result.then(
    () => undefined,
    () => undefined,
  );
  return result;
}

// Atomic write: write to a temp file then rename, so a crash mid-write can
// never leave jobs.json truncated/corrupted.
async function writeJobsAtomic(jobs: ExamJob[]): Promise<void> {
  await ensureDataDir();
  const tmp = `${JOBS_FILE}.tmp`;
  await writeFile(tmp, JSON.stringify(jobs, null, 2));
  await rename(tmp, JOBS_FILE);
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
  return withLock(async () => {
    const jobs = await getJobs();
    const idx = jobs.findIndex(j => j.id === id);
    if (idx !== -1) {
      jobs[idx] = { ...jobs[idx], ...updates, updatedAt: new Date().toISOString() };
      await writeJobsAtomic(jobs);
    }
  });
}

export async function createJob(job: ExamJob): Promise<void> {
  return withLock(async () => {
    const jobs = await getJobs();
    jobs.push(job);
    await writeJobsAtomic(jobs);
  });
}

export async function deleteJobs(ids: string[]): Promise<number> {
  const idSet = new Set(ids);
  if (!idSet.size) return 0;

  return withLock(async () => {
    const jobs = await getJobs();
    const nextJobs = jobs.filter(job => !idSet.has(job.id));
    const deleted = jobs.length - nextJobs.length;

    if (deleted > 0) {
      await writeJobsAtomic(nextJobs);
    }

    return deleted;
  });
}
