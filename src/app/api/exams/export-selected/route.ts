import { NextResponse } from 'next/server';
import path from 'path';
import fs from 'fs';
import archiver from 'archiver';
import { getJobs } from '@/lib/storage';

type ExportSelectedRequest = {
  ids?: string[];
};

const EXPORTABLE_STATUSES = new Set(['completed', 'completed_with_warnings']);

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
      if (!fs.existsSync(jsonPath)) continue;

      const examData = JSON.parse(fs.readFileSync(jsonPath, 'utf-8'));
      const usedFiles = collectUsedAssets(examData);
      const folder = buildFolderName(examData, id);

      archive.file(jsonPath, { name: `${folder}/exam.json` });

      for (const relPath of usedFiles) {
        const absPath = path.join(outputDir, id, relPath);
        if (fs.existsSync(absPath)) {
          archive.file(absPath, { name: `${folder}/${relPath}` });
        }
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

function buildFolderName(examData: Record<string, unknown>, id: string) {
  const metadata = examData.metadata as Record<string, unknown> | undefined;
  const subject = String(metadata?.subject || 'Exame')
    .normalize('NFD').replace(/[\u0300-\u036f]/g, '')
    .replace(/[^a-zA-Z0-9]/g, '');
  const year = metadata?.year || '';
  const phase = String(metadata?.phase || '').replace(/[^0-9]/g, '');
  const shortId = id.split('_').pop() || id.slice(-8);
  return `${subject}${year}${phase ? `Fase${phase}` : ''}_${shortId}`;
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
