import { notFound } from 'next/navigation';
import { SettingsPage } from '@/features/settings/settings-page';
import { featureFlags } from '@/lib/feature-flags';
export default function Page() { if (!featureFlags.settings) notFound(); return <SettingsPage/>; }
