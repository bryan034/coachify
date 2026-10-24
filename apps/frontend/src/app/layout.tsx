import type { ReactNode } from 'react';
import '../styles/globals.css';
export const metadata = { title: 'Coachify · Your career copilot', description: 'Build your background and work towards your next career move.' };
export default function RootLayout({ children }: { children: ReactNode }) {
 return <html lang="en"><body>{children}</body></html>;
}
