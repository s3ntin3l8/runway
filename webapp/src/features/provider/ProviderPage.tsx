import { useParams } from 'react-router';
import { PageHeader } from '@/components/layout/PageHeader';

export function ProviderPage() {
  const { providerId } = useParams();
  return (
    <>
      <PageHeader title={providerId ?? 'Provider'} />
      <div className="p-4 lg:p-8">
        <p className="text-sm text-fg-muted">Provider detail tabs land here (Phase 3).</p>
      </div>
    </>
  );
}
