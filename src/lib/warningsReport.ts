// Shared warning classification + human-readable warnings.txt builder.
// Used by the issues API route and both ZIP exports so the info/real split
// stays consistent everywhere.

export interface RawWarning {
  type?: string;
  message?: string;
  severity?: string;
  questionId?: string;
}

interface CriteriaIssue {
  code?: string;
  severity?: string;
  message?: string;
}

// Pipeline repair/cleanup operations that succeeded — informational only.
// These are NOT problems; the pipeline handled them automatically.
export const INFO_WARNING_TYPES = new Set([
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

export function makeIsInfoWarning(allWarnings: RawWarning[]) {
  // When the exam has a grupo_ii_points_rescaled warning, suspicious_points with low
  // values are artifacts of the rescaling algorithm, not real issues.
  const hasRescaling = allWarnings.some((w) => w.type === 'grupo_ii_points_rescaled');

  return function isInfoWarning(w: RawWarning): boolean {
    if (w.severity === 'info') return true;
    if (INFO_WARNING_TYPES.has(w.type || '')) return true;
    if (w.type === 'suspicious_points') {
      const match = /low points: (\d+)/.exec(w.message || '');
      const pts = match ? parseInt(match[1], 10) : 0;
      return pts >= 3 || hasRescaling;
    }
    return false;
  };
}

/** Build the human-readable warnings.txt content shipped inside export ZIPs. */
export function buildWarningsReport(
  examId: string,
  examData: Record<string, unknown>,
  criteriaDoc: Record<string, unknown> | null,
): string {
  const lines: string[] = [];
  lines.push(`Relatório de avisos — ${examId}`);
  lines.push(`Gerado em: ${new Date().toISOString()}`);
  lines.push(`Estado do processamento: ${examData.processingStatus ?? '?'}`);
  lines.push('');

  const warnings = (Array.isArray(examData.warnings) ? examData.warnings : []) as RawWarning[];
  const isInfo = makeIsInfoWarning(warnings);
  const real = warnings.filter((w) => !isInfo(w));
  const info = warnings.filter((w) => isInfo(w));

  lines.push(`=== Avisos da extração (${real.length}) ===`);
  if (real.length === 0) {
    lines.push('Sem avisos reais — extração limpa.');
  } else {
    for (const w of real) {
      const sev = (w.severity || 'low').toUpperCase();
      lines.push(`[${sev}] ${w.type || 'unknown'} — ${w.message || ''}`);
    }
  }
  lines.push('');

  if (info.length > 0) {
    lines.push(`=== Reparações automáticas do pipeline (${info.length}) — informativo ===`);
    for (const w of info) {
      lines.push(`[INFO] ${w.type || 'unknown'} — ${w.message || ''}`);
    }
    lines.push('');
  }

  if (criteriaDoc) {
    const audit = (criteriaDoc.audit ?? {}) as { verdict?: string; issues?: CriteriaIssue[] };
    const meta = (criteriaDoc.metadata ?? {}) as { matchedQuestions?: number };
    const issues = Array.isArray(audit.issues) ? audit.issues : [];
    lines.push(`=== Critérios de classificação ===`);
    lines.push(`Verdict: ${audit.verdict ?? '?'}`);
    if (meta.matchedQuestions != null) lines.push(`Itens associados: ${meta.matchedQuestions}`);
    if (issues.length === 0) {
      lines.push('Sem problemas nos critérios.');
    } else {
      lines.push(`Problemas (${issues.length}):`);
      for (const i of issues) {
        lines.push(`[${(i.severity || 'high').toUpperCase()}] ${i.code || ''} — ${i.message || ''}`);
      }
    }
    lines.push('');
  } else {
    lines.push('=== Critérios de classificação ===');
    lines.push('Ainda não construídos para este exame.');
    lines.push('');
  }

  return lines.join('\n');
}
