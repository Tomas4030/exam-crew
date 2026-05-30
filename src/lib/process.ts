import { spawn } from 'child_process';
import path from 'path';
import os from 'os';
import { writeFileSync } from 'fs';
import { ProcessResult } from './types';

const PROGRESS_DIR = path.join(process.cwd(), 'data');

const PIPELINE_STEPS = [
  { id: 'extract', label: 'Extrair PDF', pct: 5 },
  { id: 'extract_done', label: 'PDF extraído', pct: 10 },
  { id: 'subject', label: 'Detetar disciplina', pct: 12 },
  { id: 'filter', label: 'Filtrar páginas', pct: 14 },
  { id: 'vision', label: 'Analisar páginas (IA)', pct: 20 },
  { id: 'scoring', label: 'Extrair cotações', pct: 55 },
  { id: 'assemble', label: 'Montar estrutura', pct: 60 },
  { id: 'table', label: 'Extrair tabelas', pct: 65 },
  { id: 'source_grouping', label: 'Agrupar documentos', pct: 70 },
  { id: 'normalize', label: 'Normalizar', pct: 75 },
  { id: 'crop', label: 'Cortar imagens', pct: 80 },
  { id: 'math_normalize', label: 'Normalizar fórmulas', pct: 85 },
  { id: 'validate', label: 'Validar', pct: 90 },
  { id: 'retry', label: 'Recuperar perguntas', pct: 93 },
  { id: 'done', label: 'Concluído', pct: 100 },
];

function writeProgress(examId: string, progress: object) {
  const file = path.join(PROGRESS_DIR, `progress_${examId}.json`);
  try { writeFileSync(file, JSON.stringify(progress)); } catch {}
}

export function runPipeline(pdfPath: string, examId: string): Promise<ProcessResult> {
  return new Promise((resolve) => {
    const pipelineDir = path.join(process.cwd(), 'pipeline');
    const uvPath = process.env.UV_PATH || 'uv';
    console.log(`[Pipeline] Starting: ${examId}`);
    console.log(`[Pipeline] PDF: ${pdfPath}`);
    console.log(`[Pipeline] CWD: ${pipelineDir}`);

    // Initialize progress
    writeProgress(examId, { step: 'starting', label: 'A iniciar...', pct: 0, message: '' });

    const child = spawn(uvPath, ['run', 'python', '-m', 'src.main', pdfPath, examId], {
      cwd: pipelineDir,
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (data) => {
      const line = data.toString();
      stdout += line;
      console.log(`[Pipeline:${examId}] ${line.trim()}`);

      // Parse progress JSON lines
      for (const l of line.split('\n')) {
        const trimmed = l.trim();
        if (trimmed.startsWith('{') && trimmed.includes('"stage"')) {
          try {
            const evt = JSON.parse(trimmed);
            const stepDef = PIPELINE_STEPS.find(s => s.id === evt.stage);
            if (stepDef) {
              writeProgress(examId, {
                step: evt.stage,
                label: stepDef.label,
                pct: stepDef.pct,
                message: evt.message || '',
              });
            }
          } catch {}
        }
      }
    });

    child.stderr.on('data', (data) => {
      const line = data.toString();
      stderr += line;
      console.error(`[Pipeline:${examId}:err] ${line.trim()}`);
    });

    child.on('close', (code) => {
      console.log(`[Pipeline] ${examId} exited with code ${code}`);
      writeProgress(examId, { step: 'done', label: 'Concluído', pct: 100, message: '' });
      if (code === 0) {
        resolve({ success: true, examId });
      } else {
        resolve({ success: false, examId, error: stderr || `Exit code ${code}` });
      }
    });

    child.on('error', (err) => {
      console.error(`[Pipeline] ${examId} spawn error: ${err.message}`);
      resolve({ success: false, examId, error: err.message });
    });
  });
}
