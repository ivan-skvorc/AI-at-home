"use client";

import { MessageSquarePlus, UsersRoundIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { useWorkspaceSidebarExpanded } from "./workspace-sidebar-frame";
import { WorkspaceSidebarTrigger } from "./workspace-sidebar-trigger";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const { isMobile } = useSidebar();
  const isSidebarOpen = useWorkspaceSidebarExpanded();
  const pathname = usePathname();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {!isSidebarOpen ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div
              className={cn(
                "text-primary block pt-1 font-serif group-hover/workspace-header:hidden",
                isMobile && "hidden",
              )}
            >
              DF
            </div>
            <WorkspaceSidebarTrigger
              className={cn(
                "pl-2",
                !isMobile && "hidden group-hover/workspace-header:block",
              )}
            />
          </div>
        ) : (
          <div className="flex items-center justify-between gap-2">
            {env.NEXT_PUBLIC_STATIC_WEBSITE_ONLY === "true" ? (
              <Link href="/" className="text-primary ml-2 font-serif">
                DeerFlow
              </Link>
            ) : (
              <div className="text-primary ml-2 cursor-default font-serif">
                DeerFlow
              </div>
            )}
            <WorkspaceSidebarTrigger />
          </div>
        )}
      </div>
      <SidebarMenu>
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname === "/workspace/chats/new"}
            asChild
          >
            <Link className="text-muted-foreground" href="/workspace/chats/new">
              <MessageSquarePlus size={16} />
              <span>{t.sidebar.newChat}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {/* Democracy sits directly under New chat because it is the same kind of
            action — start a conversation — and it navigates to its own setup
            page for the same reason New chat navigates: the roster and the cost
            warning need a page, not a modal over whatever was already open. */}
        <SidebarMenuItem>
          <SidebarMenuButton
            isActive={pathname.startsWith("/workspace/democracy")}
            asChild
          >
            <Link
              className="text-muted-foreground"
              href="/workspace/democracy/new"
            >
              <UsersRoundIcon size={16} />
              <span>{t.democracy.launch}</span>
            </Link>
          </SidebarMenuButton>
        </SidebarMenuItem>
        {/* No image-generation entry here, deliberately. Generation still
            works — the media tools stay bound and `/workspace/image/new`
            still renders — but the feature is no longer advertised in the
            sidebar or the README, so the shop window does not promise a GPU
            this install may not have. Re-adding a SidebarMenuButton pointing
            at `/workspace/image` is how that decision gets silently undone,
            which is what `workspace-header.dom.test.tsx` watches for. */}
      </SidebarMenu>
    </>
  );
}
