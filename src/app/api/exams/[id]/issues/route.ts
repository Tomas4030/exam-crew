import { NextResponse } from 'next/server';
import { readFile } from 'fs/promises';
import path from 'path';
import { getJob } from '@/lib/storage';

interface RawWarning {
  type?: string;
  message?: string;
  severity?: string;
  questionId?: string;
}

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

// Pipeline repair/cleanup operations that succeeded — informational only.
// These are NOT problems; the pipeline handled them automatically.
// Displayed separately as "Notas do pipeline" so they don't inflate the warning count.
const INFO_TYPES = new Set([
  'portuguese_points_repaired',
  'portuguese_text_sources_repaired',
  'portuguese_legacy_duplicates_removed',
  'portuguese_group_iii_duplicates_removed',
  'portuguese_group_iii_observations_removed',
  'portuguese_inline_options_stripped',
  'portuguese_composition_visual_attached',
  'portuguese_choice_options_repaired',
  'portuguese_multiblank_repaired',
  'portuguese_embedded_group_iii_removed',
  'portuguese_group_iii_recovered',
  'portuguese_multiple_compositions_collapsed',
  'portuguese_missing_questions_recovered',
  'portuguese_grupo_i_b_reconstructed',
  'portuguese_grupo_i_b_injected',
  'portuguese_recovered_from_pdf_text',
  'instruction_questions_removed',
  'recovered_questions_present',
  'partial_text_fallback_used',
  'text_fallback_used',
  'history_question_cleanup',
  'history_points_repaired',
  'history_points_repaired_from_scoring_text',
  'history_multi_select_repaired',
  'history_multiblank_repaired',
  'history_interaction_type_repaired',
  'history_false_interaction_type_repaired',
  'history_line_number_artifact_removed',
  'cross_group_ref_stripped',
  'multi_select_max_inferred',
]);

function makeIsInfoWarning(allWarnings: RawWarning[]) {
  // When the exam has a grupo_ii_points_rescaled warning, suspicious_points with low values
  // are artifacts of the rescaling algorithm (minimum 1-2 pts per item), not real issues.
  const hasRescaling = allWarnings.some((w) => w.type === 'grupo_ii_points_rescaled');

  return function isInfoWarning(w: RawWarning): boolean {
    if (w.severity === 'info') return true;
    if (INFO_TYPES.has(w.type || '')) return true;
    if (w.type === 'suspicious_points') {
      const match = /low points: (\d+)/.exec(w.message || '');
      const pts = match ? parseInt(match[1], 10) : 0;
      // Old threshold (< 8) produced many false positives; pipeline now uses < 3.
      // Filter as info: pts >= 3 always, or any pts when caused by rescaling.
      return pts >= 3 || hasRescaling;
    }
    return false;
  };
}

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
