"use client";

import { PdfViewer } from "@geomak/ui";
import { PDF_WORKER_SRC } from "@/lib/pdf";
import styles from "./DocumentViewer.module.css";

export function documentFileUrl(documentId: string): string {
  return `/api/v1/documents/${encodeURIComponent(documentId)}/file`;
}

export function DocumentViewer({ documentId, page }: { documentId: string; page?: number }) {
  return (
    <div className={styles.viewer}>
      <PdfViewer source={documentFileUrl(documentId)} workerSrc={PDF_WORKER_SRC} page={page} />
    </div>
  );
}
