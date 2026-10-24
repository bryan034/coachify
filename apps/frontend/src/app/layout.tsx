import type { ReactNode } from 'react';
import '../styles/globals.css';
export const metadata = { title: 'Coachify · Your background', description: 'Set your occupational status and education category.' };
export default function RootLayout({ children }: { children: ReactNode }) {
  return <html lang="en"><body>{children}</body></html>;
}
