import { readFileSync, writeFileSync, renameSync, existsSync, mkdirSync } from "fs";
import path from "path";
import { runPipeline } from "@/lib/process";
import { runCriteria } from "@/lib/criteriaProcess";
import { getJobs, updateJob } from "@/lib/storage";

type QueueItem = { examId: string; pdfPath: string; sourceUrl?: string };

const DATA_DIR = path.join(process.cwd(), "data");
const QUEUE_FILE = path.join(DATA_DIR, "queue.json");

const queue: QueueItem[] = [];
let running = false;
let recovered = false;

function persistQueue() {
  try {
    mkdirSync(DATA_DIR, { recursive: true });
    const tmp = `${QUEUE_FILE}.tmp`;
    writeFileSync(tmp, JSON.stringify(queue, null, 2));
    renameSync(tmp, QUEUE_FILE);
  } catch (err) {
    console.warn("[Queue] Failed to persist queue:", err);
  }
}

/**
 * Crash recovery, run once per server start:
 *  1. Reload any queued items persisted before the restart.
 *  2. Jobs stuck in "processing" (the run died with the server) are re-enqueued
 *     when their PDF still exists, otherwise marked as error.
 */
async function recoverOnStartup() {
  if (recovered) return;
  recovered = true;

  try {
    if (existsSync(QUEUE_FILE)) {
      const saved: QueueItem[] = JSON.parse(readFileSync(QUEUE_FILE, "utf-8"));
      for (const item of saved) {
        if (!queue.some((q) => q.examId === item.examId)) queue.push(item);
      }
    }
  } catch (err) {
    console.warn("[Queue] Failed to reload persisted queue:", err);
  }

  try {
    const jobs = await getJobs();
    for (const job of jobs) {
      if (job.status !== "processing") continue;
      if (queue.some((q) => q.examId === job.id)) continue;
      const pdfPath = path.join(DATA_DIR, "uploads", `${job.id}.pdf`);
      if (existsSync(pdfPath)) {
        console.log(`[Queue] Re-enqueueing orphaned job ${job.id} after restart`);
        await updateJob(job.id, { status: "queued" });
        queue.push({ examId: job.id, pdfPath, sourceUrl: job.sourceUrl });
      } else {
        console.warn(`[Queue] Orphaned job ${job.id} has no PDF — marking as error`);
        await updateJob(job.id, {
          status: "error",
          error: "Processamento interrompido por reinício do servidor (PDF original não encontrado).",
        });
      }
    }
  } catch (err) {
    console.warn("[Queue] Orphan recovery failed:", err);
  }

  persistQueue();
}

export function enqueuePipeline(item: QueueItem) {
  queue.push(item);
  persistQueue();
  void runNext();
}

export function getQueueState() {
  return { running, queued: queue.map((i) => i.examId) };
}

async function runNext() {
  if (running) return;
  running = true;
  try {
    await recoverOnStartup();
    while (queue.length > 0) {
      const item = queue.shift()!;
      persistQueue();
      const startedAt = new Date().toISOString();
      await updateJob(item.examId, { status: "processing", startedAt });
      const result = await runPipeline(item.pdfPath, item.examId, item.sourceUrl);
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

      // Auto-build the official criteria right after a successful exam run, so the
      // Critérios badge/panel is populated without the user opening the exam.
      // Failures are logged but never block the queue — the user can still
      // trigger/reprocess manually from the CriteriaPanel.
      if (result.success) {
        try {
          const crit = await runCriteria(item.examId);
          if (!crit.success) {
            console.warn(`[Criteria:auto] ${item.examId} failed: ${crit.error}`);
          }
        } catch (err) {
          console.warn(`[Criteria:auto] ${item.examId} threw:`, err);
        }
      }
    }
  } finally {
    running = false;
  }
}

// Kick off recovery as soon as this module loads (first API hit after restart),
// so orphaned jobs are fixed even if nothing new is enqueued.
void runNext();
