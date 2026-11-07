"use client";

import {
  Tooltip as TooltipPrimitive,
  TooltipContent,
  TooltipTrigger,
} from "@/components/ui/tooltip";

export function Tooltip({
  children,
  content,
  side,
  delayDuration = 500,
  contentClassName,
  ...props
}: {
  children: React.ReactNode;
  content?: React.ReactNode;
  side?: "top" | "right" | "bottom" | "left";
  delayDuration?: number;
  contentClassName?: string;
}) {
  return (
    <TooltipPrimitive delayDuration={delayDuration} {...props}>
      <TooltipTrigger asChild>{children}</TooltipTrigger>
      <TooltipContent side={side} className={contentClassName}>
        {content}
      </TooltipContent>
    </TooltipPrimitive>
  );
}
