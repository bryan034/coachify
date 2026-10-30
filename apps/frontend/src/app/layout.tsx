import type { ReactNode } from 'react';
import '../styles/globals.css';
import '../styles/career-briefing.css';
import '../styles/elo-theme.css';
import { ProfileProvider } from '@/features/profile/profile-provider';
export const metadata = { title: 'Coachify · Your career copilot', description: 'Build your background and work towards your next career move.', icons: { icon: '/brand/elo-mark.svg' } };
export default function RootLayout({ children }: { children: ReactNode }) {
 return <html lang="en"><body><ProfileProvider>{children}</ProfileProvider></body></html>;
}
