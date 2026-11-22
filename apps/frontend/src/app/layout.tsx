import type { ReactNode } from 'react';
import { headers } from 'next/headers';
import { SecurityNonceProvider } from '@/components/security-nonce';
import '../styles/globals.css';
import '../styles/career-briefing.css';
import '../styles/elo-theme.css';
import '../styles/processing.css';
import { ProfileProvider } from '@/features/profile/profile-provider';
export const metadata = { title: 'elo · Your career copilot', description: 'Build your background and work towards your next career move.', icons: { icon: { url: '/brand/elo-app-icon.svg', type: 'image/svg+xml', sizes: 'any' } } };
export default async function RootLayout({ children }: { children: ReactNode }) {
 const nonce = (await headers()).get('x-nonce') || '';
 return <html lang="en"><body><SecurityNonceProvider nonce={nonce}><ProfileProvider>{children}</ProfileProvider></SecurityNonceProvider></body></html>;
}
