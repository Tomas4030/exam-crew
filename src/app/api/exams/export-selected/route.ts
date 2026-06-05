import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';
import { getJobs } from '@/lib/storage';
import { buildExamExportName, normalizeExamForExport } from '@/lib/examExport';

type ExportSelectedRequest = {
  ids?: string[];
};

const EXPORTABLE_STATUSES = new Set(['completed', 'completed_with_warnings', 'needs_review', 'partial_failed', 'error']);

export async function POST(request: Request) {
  const body = (await request.json().catch(() => ({}))) as ExportSelectedRequest;
  const requestedIds = [...new Set((body.ids || []).filter(id => typeof id === 'string' && id.trim()))];

  if (!requestedIds.length) {
    return NextResponse.json({ error: 'No exams selected' }, { status: 400 });
  }

  const jobs = await getJobs();
  const jobsById = new Map(jobs.map(job => [job.id, job]));
  const selectedJobs = requestedIds
    .map(id => jobsById.get(id))
    .filter(job => job && EXPORTABLE_STATUSES.has(job.status));

  if (!selectedJobs.length) {
    return NextResponse.json({ error: 'No exportable selected exams found' }, { status: 404 });
  }

  const outputDir = path.join(process.cwd(), 'data', 'output');
  const archive = archiver('zip', { zlib: { level: 6 } });
  const chunks: Buffer[] = [];

  await new Promise<void>((resolve, reject) => {
    archive.on('data', (chunk: Buffer) => chunks.push(chunk));
    archive.on('end', resolve);
    archive.on('error', reject);

    for (const job of selectedJobs) {
      if (!job) continue;
      const id = job.id;
      const jsonPath = path.join(outputDir, `${id}.json`);
      const hasExamJson = fs.existsSync(jsonPath);
      const examData = hasExamJson
        ? normalizeExamForExport(JSON.parse(fs.readFileSync(jsonPath, 'utf-8')))
        : null;
      const folder = examData ? buildExamExportName(examData, id) : buildFallbackExportName(job, id);

      if (examData) {
        const usedFiles = collectUsedAssets(examData);
        archive.append(JSON.stringify(examData, null, 2), { name: `${folder}/exam.json` });

        for (const relPath of usedFiles) {
          const absPath = path.join(outputDir, id, relPath);
          if (fs.existsSync(absPath)) {
            archive.file(absPath, { name: `${folder}/${relPath}` });
          }
        }
      }

      if (job.status === 'error' || job.error) {
        archive.append(JSON.stringify(buildErrorReport(job, examData), null, 2), { name: `${folder}/error.json` });
      }
    }

    archive.finalize();
  });

  const buffer = Buffer.concat(chunks);
  if (!buffer.length) {
    return NextResponse.json({ error: 'Selected exams have no exportable files' }, { status: 404 });
  }

  const timestamp = new Date().toISOString().slice(0, 10).replace(/-/g, '');
  const zipFilename = `SelectedExams_${timestamp}_${selectedJobs.length}.zip`;

  return new NextResponse(buffer, {
    headers: {
      'Content-Type': 'application/zip',
      'Content-Disposition': `attachment; filename="${zipFilename}"`,
    },
  });
}

function buildFallbackExportName(job: { filename?: string; sourceUrl?: string }, id: string) {
  const source = `${job.sourceUrl || ''}/${job.filename || 'Exame'}`;
  const year = source.match(/\/(20\d{2})-/)?.[1] || '';
  const phase = source.match(/-(\d)fase\//i)?.[1] || '';
  const subject = String(job.filename || 'Exame')
    .replace(/\.pdf$/i, '')
    .normalize('NFD')
    .replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]/g, '') || 'Exame';
  const shortId = id.split('_').pop() || id.slice(-8);
  return `${subject}${year}${phase ? `Fase${phase}` : ''}_${shortId}`;
}

function buildErrorReport(job: Record<string, any>, examData: Record<string, any> | null) {
  const metadata = examData?.metadata || {};
  const audit = metadata.portugueseAudit || metadata.historyAudit || null;
  return {
    id: job.id,
    filename: job.filename,
    status: job.status,
    error: job.error || null,
    sourceUrl: job.sourceUrl || metadata.sourceUrl || null,
    createdAt: job.createdAt || null,
    startedAt: job.startedAt || null,
    completedAt: job.completedAt || null,
    updatedAt: job.updatedAt || null,
    processingStatus: examData?.processingStatus || metadata.processingStatus || null,
    needsHumanReview: examData?.needsHumanReview ?? metadata.needsHumanReview ?? null,
    audit,
  };
}

function collectUsedAssets(examData: Record<string, unknown>): string[] {
  const paths = new Set<string>();

  const addVisualPath = (rel?: unknown) => {
    if (typeof rel === 'string' && rel.startsWith('assets/')) paths.add(rel);
  };

  const addVisualCrop = (crop?: Record<string, unknown>) => {
    addVisualPath(crop?.relativePath);
  };

  const assets = (examData.assets as Record<string, unknown>[]) || [];
  const findAsset = (id: string) => assets.find((a) => a.id === id);

  const addAssetVisual = (asset?: Record<string, unknown>) => {
    if (!asset) return;
    addVisualPath(asset.relativePath);
    if (typeof asset.url === 'string') {
      const match = asset.url.match(/\/assets\/(.+)$/);
      if (match) addVisualPath(`assets/${match[1]}`);
    }
    const crops = asset.crops as Record<string, unknown> | undefined;
    if (crops?.visual) addVisualCrop(crops.visual as Record<string, unknown>);
    addVisualCrop(asset.crop as Record<string, unknown>);
  };

  for (const q of (examData.questions as Record<string, unknown>[]) || []) {
    const media = q.media as { url?: string; relativePath?: string }[] | undefined;
    if (media) {
      for (const m of media) {
        addVisualPath(m.relativePath);
        if (m.url) {
          const match = m.url.match(/\/assets\/(.+)$/);
          if (match) addVisualPath(`assets/${match[1]}`);
        }
      }
    }

    const allRefs = [
      ...((q.imageRefs as string[]) || []),
      ...((q.assetRefs as string[]) || []),
      ...((q.tableRefs as string[]) || []),
    ];
    for (const refId of allRefs) {
      const asset = findAsset(refId);
      if (asset) addAssetVisual(asset);
    }

    const options = q.options as { imageUrl?: string }[] | undefined;
    if (options) {
      for (const opt of options) {
        if (opt.imageUrl) {
          const match = opt.imageUrl.match(/\/assets\/(.+)$/);
          if (match) addVisualPath(`assets/${match[1]}`);
        }
      }
    }
  }

  for (const src of (examData.sources as Record<string, unknown>[]) || []) {
    const crops = src.crops as Record<string, unknown> | undefined;
    if (crops) {
      for (const key of ['best', 'full', 'document', 'visual']) {
        const crop = crops[key] as Record<string, unknown> | undefined;
        if (crop?.relativePath) addVisualPath(crop.relativePath);
      }
    }
    const childCrops = src.childCrops as Record<string, Record<string, unknown>> | undefined;
    if (childCrops) {
      for (const crop of Object.values(childCrops)) {
        addVisualCrop(crop);
      }
    }
  }

  return [...paths];
}
