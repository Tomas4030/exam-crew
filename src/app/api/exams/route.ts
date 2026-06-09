import { NextResponse } from 'next/server';
import fs from 'fs';
import path from 'path';
import { getJobs } from '@/lib/storage';

const OUTPUT_DIR = path.join(process.cwd(), 'data', 'output');

interface CriteriaAuditIssue {
  code: string;
  severity: string;
  message: string;
}

function readCriteriaSummary(id: string): {
  hasCriteria: boolean;
  criteriaVerdict: string | null;
  criteriaIssues: CriteriaAuditIssue[] | null;
  criteriaMatchedQuestions: number | null;
} {
  const criteriaPath = path.join(OUTPUT_DIR, `${id}.criteria.json`);
  if (!fs.existsSync(criteriaPath)) {
    return { hasCriteria: false, criteriaVerdict: null, criteriaIssues: null, criteriaMatchedQuestions: null };
  }
  try {
    const raw = fs.readFileSync(criteriaPath, 'utf-8');
    const doc = JSON.parse(raw);
    return {
      hasCriteria: true,
      criteriaVerdict: doc.audit?.verdict ?? null,
      criteriaIssues: doc.audit?.issues ?? null,
      criteriaMatchedQuestions: doc.metadata?.matchedQuestions ?? null,
    };
  } catch {
    return { hasCriteria: true, criteriaVerdict: null, criteriaIssues: null, criteriaMatchedQuestions: null };
  }
}

export async function GET() {
  const jobs = (await getJobs()).sort((a, b) =>
    new Date(b.createdAt).getTime() - new Date(a.createdAt).getTime()
  );
  const withCriteria = jobs.map((job) => ({
    ...job,
    ...readCriteriaSummary(job.id),
  }));
  return NextResponse.json(withCriteria);
}
