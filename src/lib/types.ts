export type ExamStatus =
  | 'queued'
  | 'pending'
  | 'processing'
  | 'completed'
  | 'completed_with_warnings'
  | 'needs_review'
  | 'partial_failed'
  | 'error';

export interface ExamJob {
  id: string;
  filename: string;
  status: ExamStatus;
  createdAt: string;
  updatedAt: string;
  error?: string;
  sourceUrl?: string;
  batchId?: string;
  batchIndex?: number;
}

export interface ProcessResult {
  success: boolean;
  examId: string;
  status?: ExamStatus;
  error?: string;
}

export interface ProgressEvent {
  examId: string;
  status: ExamStatus;
  message?: string;
}
