import Link from 'next/link';
import { ProfileForm } from '@/features/profile/profile-form';

export default function Page() {
  return <><Link className="text-link profile-return" href="/profile">← Back to profile</Link><ProfileForm /></>;
}
