"use client";

import { MessageSquarePlus, UsersRoundIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";

import {
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarTrigger,
  useSidebar,
} from "@/components/ui/sidebar";
import { useI18n } from "@/core/i18n/hooks";
import { env } from "@/env";
import { cn } from "@/lib/utils";

import { DemocracyDialog } from "./democracy-dialog";

export function WorkspaceHeader({ className }: { className?: string }) {
  const { t } = useI18n();
  const [democracyOpen, setDemocracyOpen] = useState(false);
  const { state } = useSidebar();
  const pathname = usePathname();
  return (
    <>
      <div
        className={cn(
          "group/workspace-header flex h-12 flex-col justify-center",
          className,
        )}
      >
        {state === "collapsed" ? (
          <div className="group-has-data-[collapsible=icon]/sidebar-wrapper:-translate-y flex w-full cursor-pointer items-center justify-center">
            <div className="text-primary block pt-1 font-serif group-hover/workspace-header:hidden">
              DF
            </div>
            <SidebarTrigger className="hidden pl-2 group-hover/workspace-header:block" />
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
            <SidebarTrigger />
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
            action — start a conversation — that happens to need a panel picked
            first. It opens a dialog rather than navigating, since the roster has
            to exist before the thread does. */}
        <SidebarMenuItem>
          <SidebarMenuButton
            className="text-muted-foreground"
            onClick={() => setDemocracyOpen(true)}
          >
            <UsersRoundIcon size={16} />
            <span>{t.democracy.launch}</span>
          </SidebarMenuButton>
        </SidebarMenuItem>
      </SidebarMenu>
      <DemocracyDialog open={democracyOpen} onOpenChange={setDemocracyOpen} />
    </>
  );
}
