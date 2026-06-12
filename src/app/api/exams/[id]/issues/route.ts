import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';
import { getJob } from '@/lib/storage';
import { makeIsInfoWarning, type RawWarning } from '@/lib/warningsReport';

interface IssueSummary {
  type: string;
  severity: string;
  count: number;
  sample: string;
}

// Heuristic severity when a warning doesn't declare one.
const SEVERITY_BY_TYPE: Record<string, string> = {
  SCORING_POLICY_REBUILT: 'medium',
  grupo_ii_points_rescaled: 'medium',
  possible_hallucination: 'medium',
  source_asset_pending_reference: 'low',
  missing_points_critical: 'high',
  question_count_mismatch: 'high',
  missing_table_data: 'medium',
  suspicious_points: 'low',
  invalid_page: 'low',
  recovered_questions_without_source_page: 'low',
};

export async function GET(_request: Request, { params }: { params: Promise<{ id: string }> }) {
  const { id } = await params;
  const job = await getJob(id);

  let warnings: RawWarning[] = [];
  let auditIssues: { code?: string; message?: string; severity?: string }[] = [];

  try {
    const outputPath = path.join(process.cwd(), 'data', 'output', `${id}.json`);
    const data = JSON.parse(await readFile(outputPath, 'utf-8'));
    warnings = Array.isArray(data.warnings) ? data.warnings : [];
    const audit = data.audit || {};
    auditIssues = Array.isArray(audit.issues) ? audit.issues : [];
  } catch {
    // Output may not exist yet; fall back to whatever the job carries.
  }

  // Partition warnings: real issues vs pipeline notes (info).
  const isInfoWarning = makeIsInfoWarning(warnings);
  const realWarnings = warnings.filter((w) => !isInfoWarning(w));
  const infoWarnings = warnings.filter((w) => isInfoWarning(w));

  function groupWarnings(list: RawWarning[]): IssueSummary[] {
    const grouped = new Map<string, IssueSummary>();
    for (const w of list) {
      const type = w.type || 'unknown';
      const existing = grouped.get(type);
      if (existing) {
        existing.count += 1;
        if (!existing.sample && w.message) existing.sample = w.message;
      } else {
        grouped.set(type, {
          type,
          severity: w.severity || SEVERITY_BY_TYPE[type] || 'low',
          count: 1,
          sample: w.message || '',
        });
      }
    }
    const severityRank: Record<string, number> = { blocker: 4, high: 3, medium: 2, low: 1, info: 0 };
    return Array.from(grouped.values()).sort(
      (a, b) => (severityRank[b.severity] || 0) - (severityRank[a.severity] || 0) || b.count - a.count,
    );
  }

  // Audit issues (blockers/high) — surfaced separately because they explain a review verdict.
  const audit = auditIssues.map((i) => ({
    code: i.code || 'AUDIT_ISSUE',
    severity: (i.severity || 'high').toLowerCase(),
    message: i.message || '',
  }));

  return NextResponse.json({
    id,
    status: job?.status ?? null,
    auditError: job?.error ?? null,
    items: groupWarnings(realWarnings),
    pipelineNotes: groupWarnings(infoWarnings),
    audit,
  });
}
