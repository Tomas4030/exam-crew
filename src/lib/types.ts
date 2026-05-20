export type ExamStatus = 'pending' | 'processing' | 'completed' | 'error';

export interface ExamJob {
  id: string;
  filename: string;
  status: ExamStatus;
  createdAt: string;
  updatedAt: string;
  error?: string;
}

export interface ProcessResult {
  success: boolean;
  examId: string;
  error?: string;
}

export interface ProgressEvent {
  examId: string;
  status: ExamStatus;
  message?: string;
}
