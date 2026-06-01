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
      await updateJob(item.examId, { status: "processing" });
      const result = await runPipeline(item.pdfPath, item.examId);
      await updateJob(item.examId, result.success
        ? { status: "completed" }
        : { status: "error", error: result.error || "Pipeline failed" }
      );
    }
  } finally {
    running = false;
  }
}
