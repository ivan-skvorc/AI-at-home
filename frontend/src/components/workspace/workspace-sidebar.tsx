"use client";

import {
  type Sidebar,
  SidebarHeader,
  SidebarContent,
  SidebarFooter,
  SidebarRail,
  useSidebar,
} from "@/components/ui/sidebar";
import { useThreadActivity } from "@/core/threads/activity";

import { WorkspaceChannelsList } from "./channels/workspace-channels-list";
import { PluginNavigation } from "./plugin-navigation";
import { ProjectsSection } from "./projects-section";
import { RecentChatList } from "./recent-chat-list";
import { SidebarSelectionProvider } from "./sidebar-selection";
import { ThreadDeleteDialogProvider } from "./thread-delete-dialog";
import { WorkspaceHeader } from "./workspace-header";
import { WorkspaceNavChatList } from "./workspace-nav-chat-list";
import { WorkspaceNavMenu } from "./workspace-nav-menu";
import {
  WorkspaceSidebarFrame,
  useWorkspaceSidebarExpanded,
} from "./workspace-sidebar-frame";

export function WorkspaceSidebar({
  ...props
}: React.ComponentProps<typeof Sidebar>) {
  // One activity poll per workspace (off unless the Gateway offers it): new
  // and changed server-created threads reach the thread lists without a
  // reload, and a read on another device clears their dots here.
  useThreadActivity();
  // Both providers sit above the frame: the chat lists unmount when the
  // sidebar collapses (and the mobile drawer closes), and a selection or a
  // delete confirmation must outlive that.
  return (
    <ThreadDeleteDialogProvider>
      <SidebarSelectionProvider>
        <WorkspaceSidebarFrame variant="sidebar" collapsible="icon" {...props}>
          <WorkspaceSidebarContents />
        </WorkspaceSidebarFrame>
      </SidebarSelectionProvider>
    </ThreadDeleteDialogProvider>
  );
}

function WorkspaceSidebarContents() {
  const isSidebarOpen = useWorkspaceSidebarExpanded();
  const { isMobile } = useSidebar();
  return (
    <>
      <SidebarHeader className="py-0">
        <WorkspaceHeader />
      </SidebarHeader>
      <SidebarContent>
        <WorkspaceNavChatList />
        <PluginNavigation />
        <WorkspaceChannelsList />
        {isSidebarOpen && (
          <>
            <ProjectsSection />
            <RecentChatList />
          </>
        )}
      </SidebarContent>
      <SidebarFooter>
        <WorkspaceNavMenu />
      </SidebarFooter>
      {!isMobile && <SidebarRail />}
    </>
  );
}
