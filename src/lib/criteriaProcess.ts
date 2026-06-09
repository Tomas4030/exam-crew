import { spawn } from 'child_process';
import path from 'path';

export interface CriteriaRunResult {
  success: boolean;
  examId: string;
  message?: string;
  error?: string;
}

/**
 * Run the official criteria pipeline for an exam:
 *   uv run python -m src.criteria.run <examId>
 * Downloads or receives the critérios PDF, parses it, matches to questions,
 * audits, and writes data/output/{examId}.criteria.json.
 *
 * opts.pdfPath  — absolute path to an already-saved criteria PDF (user upload)
 * opts.url      — override the remote URL to download the PDF from
 * (neither)     — pipeline resolves the URL automatically
 */
export function runCriteria(
  examId: string,
  opts?: { url?: string; pdfPath?: string },
): Promise<CriteriaRunResult> {
  return new Promise((resolve) => {
    const pipelineDir = path.join(process.cwd(), 'pipeline');
    const uvPath = process.env.UV_PATH || 'uv';

    const args = ['run', 'python', '-m', 'src.criteria.run', examId];
    if (opts?.pdfPath) args.push('--pdf', opts.pdfPath);
    else if (opts?.url) args.push('--url', opts.url);

    console.log(`[Criteria] Starting: ${examId}`);
    const child = spawn(uvPath, args, { cwd: pipelineDir, env: { ...process.env } });

    let stdout = '';
    let stderr = '';
    let lastError = '';
    let lastMessage = '';

    child.stdout.on('data', (data) => {
      const line = data.toString();
      stdout += line;
      console.log(`[Criteria:${examId}] ${line.trim()}`);
      for (const l of line.split('\n')) {
        const t = l.trim();
        if (t.startsWith('{') && t.includes('"stage"')) {
          try {
            const evt = JSON.parse(t);
            if (evt.stage === 'error') lastError = evt.message || '';
            else if (evt.message) lastMessage = evt.message;
          } catch {}
        }
      }
    });

    child.stderr.on('data', (data) => {
      const line = data.toString();
      stderr += line;
      console.error(`[Criteria:${examId}:err] ${line.trim()}`);
    });

    child.on('close', (code) => {
      console.log(`[Criteria] ${examId} exited with code ${code}`);
      if (code === 0) {
        resolve({ success: true, examId, message: lastMessage });
      } else {
        resolve({
          success: false,
          examId,
          error: lastError || stderr.trim() || `Exit code ${code}`,
        });
      }
    });

    child.on('error', (err) => {
      console.error(`[Criteria] ${examId} spawn error: ${err.message}`);
      resolve({ success: false, examId, error: err.message });
    });
  });
}
