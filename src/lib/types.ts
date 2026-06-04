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
  startedAt?: string;
  completedAt?: string;
  durationMs?: number;
  tokenUsage?: TokenUsage;
  error?: string;
  sourceUrl?: string;
  batchId?: string;
  batchIndex?: number;
}

export interface TokenUsage {
  calls?: number;
  models?: string[];
  promptTokens?: number;
  completionTokens?: number;
  reasoningTokens?: number;
  totalTokens?: number;
}

export interface ProcessResult {
  success: boolean;
  examId: string;
  status?: ExamStatus;
  tokenUsage?: TokenUsage;
  error?: string;
}

export interface ProgressEvent {
  examId: string;
  status: ExamStatus;
  message?: string;
}
