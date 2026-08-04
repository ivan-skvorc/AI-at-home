import { isStaticWebsiteOnly } from "@/core/static-mode";
import { DEMO_THREAD_IDS } from "@/core/threads/static-demo";

export function generateStaticParams() {
  if (!isStaticWebsiteOnly()) {
    return [];
  }
  return DEMO_THREAD_IDS.map((thread_id) => ({ thread_id }));
}

// The per-chat provider stack now lives inside each mounted <ChatInstance> so
// that keep-alive chat tabs can mount several isolated instances at once
// outside this route. This layout only anchors the route (and its static demo
// params); the page renders either a route registrar (app) or a classic inline
// chat (static demo).
export default function ChatLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return <>{children}</>;
}
