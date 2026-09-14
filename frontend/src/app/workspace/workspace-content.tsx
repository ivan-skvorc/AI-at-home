import { cookies } from "next/headers";
import { Toaster } from "sonner";

import { QueryClientProvider } from "@/components/query-client-provider";
import { SidebarInset, SidebarProvider } from "@/components/ui/sidebar";
// Direct file import (not the barrel): this server component must reach the
// client viewport across a proper "use client" boundary without pulling the
// whole chats barrel into the server module graph.
import { KeepAliveChatViewport } from "@/components/workspace/chats/keep-alive-chat-viewport";
import { CommandPalette } from "@/components/workspace/command-palette";
import { GatewayOfflineBanner } from "@/components/workspace/gateway-offline-banner";
import { ModelLoadErrorBanner } from "@/components/workspace/model-load-error-banner";
import { SettingsDialogHost } from "@/components/workspace/settings";
import { WorkspaceSettingsDeepLink } from "@/components/workspace/workspace-settings-deep-link";
import { WorkspaceSidebar } from "@/components/workspace/workspace-sidebar";
<<<<<<< HEAD
import { LiveChatSlotsProvider } from "@/core/threads/live-chat-slots-context";
=======
import { UserPreferencesBoundary } from "@/core/settings/user-preferences-boundary";
>>>>>>> upstream/main

function parseSidebarOpenCookie(
  value: string | undefined,
): boolean | undefined {
  if (value === "true") return true;
  if (value === "false") return false;
  return undefined;
}

export async function WorkspaceContent({
  children,
  gatewayUnavailable = false,
}: Readonly<{
  children: React.ReactNode;
  gatewayUnavailable?: boolean;
}>) {
  const cookieStore = await cookies();
  const initialSidebarOpen = parseSidebarOpenCookie(
    cookieStore.get("sidebar_state")?.value,
  );

  return (
    <QueryClientProvider>
<<<<<<< HEAD
      <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
        <LiveChatSlotsProvider>
=======
      <UserPreferencesBoundary>
        <SidebarProvider className="h-screen" defaultOpen={initialSidebarOpen}>
>>>>>>> upstream/main
          <WorkspaceSidebar />
          <SidebarInset className="min-w-0">
            <GatewayOfflineBanner gatewayUnavailable={gatewayUnavailable} />
            <ModelLoadErrorBanner gatewayUnavailable={gatewayUnavailable} />
<<<<<<< HEAD
            {/* Persistent keep-alive host for chat tabs. Mounted above the
                route so navigating between chats never remounts them; hidden
                (but still mounted) on non-chat workspace routes. */}
            <KeepAliveChatViewport />
            {children}
          </SidebarInset>
        </LiveChatSlotsProvider>
      </SidebarProvider>
      <CommandPalette />
      <SettingsDialogHost />
      <WorkspaceSettingsDeepLink />
      <Toaster position="top-center" />
=======
            {children}
          </SidebarInset>
        </SidebarProvider>
        <CommandPalette />
        <SettingsDialogHost />
        <WorkspaceSettingsDeepLink />
        <Toaster position="top-center" />
      </UserPreferencesBoundary>
>>>>>>> upstream/main
    </QueryClientProvider>
  );
}
