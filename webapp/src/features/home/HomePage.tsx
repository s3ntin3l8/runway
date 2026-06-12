import { PageHeader } from '@/components/layout/PageHeader';

export function HomePage() {
  return (
    <>
      <PageHeader title="Home" description="Quota risk at a glance" />
      <div className="p-4 lg:p-8">
        <p className="text-sm text-fg-muted">Risk-first dashboard lands here (Phase 2).</p>
      </div>
    </>
  );
}
