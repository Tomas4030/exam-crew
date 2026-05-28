import { spawn } from 'child_process';
import path from 'path';
import os from 'os';
import { ProcessResult } from './types';

export function runPipeline(pdfPath: string, examId: string): Promise<ProcessResult> {
  return new Promise((resolve) => {
    const pipelineDir = path.join(process.cwd(), 'pipeline');
    const uvPath = path.join(os.homedir(), '.local', 'bin', 'uv.exe');
    console.log(`[Pipeline] Starting: ${examId}`);
    console.log(`[Pipeline] PDF: ${pdfPath}`);
    console.log(`[Pipeline] CWD: ${pipelineDir}`);

    const child = spawn(uvPath, ['run', 'python', '-m', 'src.main', pdfPath, examId], {
      cwd: pipelineDir,
    });

    let stdout = '';
    let stderr = '';

    child.stdout.on('data', (data) => {
      const line = data.toString();
      stdout += line;
      console.log(`[Pipeline:${examId}] ${line.trim()}`);
    });

    child.stderr.on('data', (data) => {
      const line = data.toString();
      stderr += line;
      console.error(`[Pipeline:${examId}:err] ${line.trim()}`);
    });

    child.on('close', (code) => {
      console.log(`[Pipeline] ${examId} exited with code ${code}`);
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
