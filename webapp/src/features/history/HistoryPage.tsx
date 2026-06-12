import { PageHeader } from '@/components/layout/PageHeader';

export function HistoryPage() {
  return (
    <>
      <PageHeader title="History" description="Usage over time" />
      <div className="p-4 lg:p-8">
        <p className="text-sm text-fg-muted">History charts land here (Phase 4).</p>
      </div>
    </>
  );
}
