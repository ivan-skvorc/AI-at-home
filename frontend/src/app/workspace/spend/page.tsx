"use client";

import { useState } from "react";

import { Button } from "@/components/ui/button";
import {
  WorkspaceBody,
  WorkspaceContainer,
  WorkspaceHeader,
} from "@/components/workspace/workspace-container";
import { useI18n } from "@/core/i18n/hooks";
import { formatTokenCount } from "@/core/messages/usage";
import { SPEND_WINDOWS, useSpendReport } from "@/core/spend/hooks";
import type {
  SpendCategoryRow,
  SpendModelRow,
  SpendThreadRow,
} from "@/core/spend/types";
import { formatCost } from "@/core/threads/token-usage";
import { cn } from "@/lib/utils";

/**
 * "Where did my money go this month."
 *
 * The chat header answers what one conversation is costing; this answers the
 * question a person actually asks at the end of a month, grouped three ways
 * over one window. Every figure is priced by the backend through the shared
 * pricing module — this page only formats and orders, so a model can never be
 * billed differently here than in the header.
 */
export default function SpendPage() {
  const { t } = useI18n();
  const sp = t.spend;
  const [days, setDays] = useState<number>(30);
  const { data, error, isLoading } = useSpendReport(days);

  const currency = data?.currency ?? null;
  const money = (amount: number | null | undefined) =>
    amount == null || !currency ? "—" : formatCost(amount, currency);

  return (
    <WorkspaceContainer>
      <WorkspaceHeader />
      <WorkspaceBody className="overflow-y-auto">
        <div className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-4 sm:p-6">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h1 className="text-xl font-semibold">{sp.title}</h1>
              <p className="text-muted-foreground mt-1 max-w-2xl text-sm">
                {sp.description}
              </p>
            </div>
            <div
              className="flex items-center gap-1"
              role="group"
              aria-label={sp.window}
            >
              {SPEND_WINDOWS.map((value) => (
                <Button
                  key={value}
                  type="button"
                  size="sm"
                  variant={days === value ? "secondary" : "ghost"}
                  aria-pressed={days === value}
                  onClick={() => setDays(value)}
                >
                  {sp.windowDays(value)}
                </Button>
              ))}
            </div>
          </div>

          {error ? (
            <p className="text-destructive text-sm">{sp.loadFailed}</p>
          ) : isLoading || !data ? (
            <p className="text-muted-foreground text-sm">…</p>
          ) : (
            <>
              <div className="grid gap-3 sm:grid-cols-3">
                <SummaryTile
                  label={sp.totalCost}
                  value={money(data.total_cost)}
                  emphasis
                />
                <SummaryTile
                  label={sp.totalTokens}
                  value={formatTokenCount(data.total_tokens)}
                />
                <SummaryTile
                  label={sp.totalRuns}
                  value={String(data.total_runs)}
                />
              </div>

              {/* A quietly low total is indistinguishable from a broken
                  feature, so say which models are missing a price — the same
                  rule the chat header follows. */}
              {data.total_cost == null && (
                <p
                  data-testid="spend-no-pricing"
                  className="text-muted-foreground text-sm"
                >
                  {sp.noPricing}
                </p>
              )}
              {data.unpriced_models.length > 0 && (
                <p
                  data-testid="spend-unpriced"
                  className="text-muted-foreground text-sm"
                >
                  {sp.unpricedNote(data.unpriced_models.join(", "))}
                </p>
              )}

              <Section title={sp.byCategory}>
                <Table
                  columns={[sp.category, sp.cost, sp.tokens]}
                  rows={data.by_category.map((row: SpendCategoryRow) => [
                    (t.spend.categories as Record<string, string>)[
                      row.category
                    ] ?? row.category,
                    money(row.cost),
                    formatTokenCount(row.tokens),
                  ])}
                  empty={sp.empty}
                />
              </Section>

              <Section title={sp.byModel}>
                <Table
                  columns={[sp.model, sp.cost, sp.tokens, sp.runs]}
                  rows={data.by_model.map((row: SpendModelRow) => [
                    row.cost == null
                      ? `${row.model} (${sp.unpriced})`
                      : row.model,
                    money(row.cost),
                    formatTokenCount(row.tokens),
                    String(row.runs),
                  ])}
                  empty={sp.empty}
                />
              </Section>

              <Section title={sp.byThread}>
                <Table
                  columns={[sp.thread, sp.cost, sp.tokens, sp.runs]}
                  rows={data.by_thread.map((row: SpendThreadRow) => [
                    row.title ?? sp.untitledThread,
                    money(row.cost),
                    formatTokenCount(row.tokens),
                    String(row.runs),
                  ])}
                  empty={sp.empty}
                />
              </Section>
            </>
          )}
        </div>
      </WorkspaceBody>
    </WorkspaceContainer>
  );
}

function SummaryTile({
  label,
  value,
  emphasis,
}: {
  label: string;
  value: string;
  emphasis?: boolean;
}) {
  return (
    <div className="rounded-lg border p-3">
      <div className="text-muted-foreground text-xs">{label}</div>
      <div
        className={cn(
          "mt-1 font-mono text-lg font-medium",
          emphasis && "text-emerald-500",
        )}
      >
        {value}
      </div>
    </div>
  );
}

function Section({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <section className="flex flex-col gap-2">
      <h2 className="text-sm font-medium">{title}</h2>
      {children}
    </section>
  );
}

function Table({
  columns,
  rows,
  empty,
}: {
  columns: string[];
  rows: string[][];
  empty: string;
}) {
  if (rows.length === 0) {
    return <p className="text-muted-foreground text-sm">{empty}</p>;
  }
  return (
    // Wide tables scroll inside their own container so the page body never
    // scrolls horizontally on a phone.
    <div className="overflow-x-auto rounded-lg border">
      <table className="w-full text-sm">
        <thead className="text-muted-foreground bg-muted/40 text-xs">
          <tr>
            {columns.map((column, index) => (
              <th
                key={column}
                className={cn(
                  "px-3 py-2 font-normal",
                  index === 0 ? "text-left" : "text-right",
                )}
              >
                {column}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row[0]} className="border-t">
              {row.map((cell, index) => (
                <td
                  key={index}
                  className={cn(
                    "px-3 py-2",
                    index === 0
                      ? "max-w-[22rem] truncate text-left"
                      : "text-right font-mono",
                  )}
                  title={index === 0 ? cell : undefined}
                >
                  {cell}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
