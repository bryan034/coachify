import { notFound } from 'next/navigation';
import { RoadmapSettingsPage } from '@/features/settings/settings-page';
import { featureFlags } from '@/lib/feature-flags';
export default function Page() { if (!featureFlags.settings || !featureFlags.roadmapSettings) notFound(); return <RoadmapSettingsPage/>; }
