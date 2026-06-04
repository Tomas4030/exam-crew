import { runPipeline } from "@/lib/process";
import { updateJob } from "@/lib/storage";

type QueueItem = { examId: string; pdfPath: string };

const queue: QueueItem[] = [];
let running = false;

export function enqueuePipeline(item: QueueItem) {
  queue.push(item);
  void runNext();
}

export function getQueueState() {
  return { running, queued: queue.map((i) => i.examId) };
}

async function runNext() {
  if (running) return;
  running = true;
  try {
    while (queue.length > 0) {
      const item = queue.shift()!;
      const startedAt = new Date().toISOString();
      await updateJob(item.examId, { status: "processing", startedAt });
      const result = await runPipeline(item.pdfPath, item.examId);
      const completedAt = new Date().toISOString();
      const durationMs = Math.max(0, new Date(completedAt).getTime() - new Date(startedAt).getTime());
      await updateJob(item.examId, result.success
        ? {
            status: result.status || "completed",
            completedAt,
            durationMs,
            tokenUsage: result.tokenUsage,
          }
        : {
            status: "error",
            error: result.error || "Pipeline failed",
            completedAt,
            durationMs,
          }
      );
    }
  } finally {
    running = false;
  }
}
