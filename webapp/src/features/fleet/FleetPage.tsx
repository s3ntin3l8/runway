import { PageHeader } from '@/components/layout/PageHeader';

export function FleetPage() {
  return (
    <>
      <PageHeader title="Fleet" description="Sidecar registry" />
      <div className="p-4 lg:p-8">
        <p className="text-sm text-fg-muted">Sidecar management lands here (Phase 5).</p>
      </div>
    </>
  );
}
