// Dev-only design-system gallery (route exists only when import.meta.env.DEV).
import { PageHeader } from '@/components/layout/PageHeader';

export function KitPage() {
  return (
    <>
      <PageHeader title="UI Kit" description="Design-system gallery (dev only)" />
      <div className="p-4 lg:p-8">
        <p className="text-sm text-fg-muted">Primitives gallery lands here (Phase 1).</p>
      </div>
    </>
  );
}
