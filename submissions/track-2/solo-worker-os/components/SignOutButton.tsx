'use client';

import { createSupabaseBrowserClient } from '@/lib/supabase-browser';
import { useRouter } from 'next/navigation';

export default function SignOutButton() {
  const router = useRouter();

  async function signOut() {
    const supabase = createSupabaseBrowserClient();
    await supabase.auth.signOut();
    // router.push already handles the navigation; no need for extra refresh.
    router.push('/login');
  }

  return (
    <button
      type="button"
      onClick={() => void signOut()}
      title="退出登录"
      className="flex items-center justify-center rounded-xl border border-black/[0.06] bg-black/[0.02] p-2 text-gray-400 dark:border-white/[0.06] dark:bg-white/[0.02] dark:text-white/35 transition-all duration-300 hover:border-red-400/20 hover:bg-red-400/5 hover:text-red-300"
    >
      <svg className="h-4 w-4" viewBox="0 0 20 20" fill="currentColor">
        <path fillRule="evenodd" d="M3 4.25A2.25 2.25 0 0 1 5.25 2h5.5A2.25 2.25 0 0 1 13 4.25v2a.75.75 0 0 1-1.5 0v-2a.75.75 0 0 0-.75-.75h-5.5a.75.75 0 0 0-.75.75v11.5c0 .414.336.75.75.75h5.5a.75.75 0 0 0 .75-.75v-2a.75.75 0 0 1 1.5 0v2A2.25 2.25 0 0 1 10.75 18h-5.5A2.25 2.25 0 0 1 3 15.75V4.25Z" clipRule="evenodd" />
        <path fillRule="evenodd" d="M6 10a.75.75 0 0 1 .75-.75h9.546l-1.048-.943a.75.75 0 1 1 1.004-1.114l2.5 2.25a.75.75 0 0 1 0 1.114l-2.5 2.25a.75.75 0 1 1-1.004-1.114l1.048-.943H6.75A.75.75 0 0 1 6 10Z" clipRule="evenodd" />
      </svg>
    </button>
  );
}
