export function normalizeExamForExport(examData: Record<string, any>) {
  const normalized = { ...examData };
  const metadata = { ...(normalized.metadata || {}) };
  const sourceUrl = metadata.sourceUrl || normalized.sourceUrl || metadata.fileUrl || "";
  const urlInfo = parseExamUrl(String(sourceUrl || ""));

  if (urlInfo.year) metadata.year = urlInfo.year;
  if (urlInfo.phase) metadata.phase = `${urlInfo.phase}ª Fase`;
  if (normalized.processingStatus) metadata.processingStatus = normalized.processingStatus;
  if (typeof normalized.needsHumanReview === "boolean") {
    metadata.needsHumanReview = normalized.needsHumanReview;
  }

  normalized.metadata = metadata;
  return normalized;
}

export function buildExamExportName(examData: Record<string, any>, id: string) {
  const normalized = normalizeExamForExport(examData);
  const metadata = normalized.metadata || {};
  const subject = String(metadata.subject || "Exame")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9]/g, "");
  const year = metadata.year || "";
  const phase = String(metadata.phase || "").replace(/[^0-9]/g, "");
  const shortId = id.split("_").pop() || id.slice(-8);
  return `${subject}${year}${phase ? `Fase${phase}` : ""}_${shortId}`;
}

function parseExamUrl(sourceUrl: string) {
  const match = sourceUrl.match(/\/(20\d{2})-([12])fase\//i);
  return {
    year: match?.[1] || "",
    phase: match?.[2] || "",
  };
}
