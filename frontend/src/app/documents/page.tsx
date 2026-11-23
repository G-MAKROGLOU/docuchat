import { DocumentsBrowser } from "@/components/documents/DocumentsBrowser";
import { PageHeading } from "@/components/layout/PageHeading";

export default function DocumentsPage() {
  return (
    <section aria-label="Documents">
      <PageHeading title="Documents" />
      <DocumentsBrowser />
    </section>
  );
}
