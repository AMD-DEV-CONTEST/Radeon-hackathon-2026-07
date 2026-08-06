import ChatClient, { type UIMessage } from '@/components/ChatClient';
import { getServerT } from '@/lib/i18n-server';

export const dynamic = 'force-dynamic';

export default async function ChatPage() {
  const t = getServerT();

  // Load messages client-side to avoid server-side Supabase timeout
  const initialMessages: UIMessage[] = [];

  return (
    <div className="flex h-[calc(100vh-7rem)] flex-col animate-fade-up">
      <ChatClient initialMessages={initialMessages} />
    </div>
  );
}
