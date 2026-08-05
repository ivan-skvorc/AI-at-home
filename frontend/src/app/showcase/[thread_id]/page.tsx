import { notFound } from "next/navigation";

import { ClassicChatPage } from "@/app/workspace/chats/[thread_id]/page";
import { DEMO_THREAD_IDS, isDemoThreadId } from "@/core/threads/static-demo";

export const dynamicParams = false;

export function generateStaticParams() {
  return DEMO_THREAD_IDS.map((thread_id) => ({ thread_id }));
}

export default async function PublicShowcasePage({
  params,
}: {
  params: Promise<{ thread_id: string }>;
}) {
  const { thread_id: threadId } = await params;
  if (!isDemoThreadId(threadId)) {
    notFound();
  }
  // Render the inline single-chat directly. The default `ChatPage` export
  // becomes a keep-alive registrar in app builds (it renders nothing on its
  // own and relies on the workspace-level viewport), which is absent on this
  // standalone public route — so the showcase must use the classic renderer.
  return <ClassicChatPage />;
}
