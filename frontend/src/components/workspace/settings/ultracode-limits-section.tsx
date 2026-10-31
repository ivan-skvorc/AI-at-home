"use client";

import { useEffect, useId, useState } from "react";

import { Input } from "@/components/ui/input";
import { useFrontendExtensions } from "@/core/extensions/hooks";
import { useI18n } from "@/core/i18n/hooks";
import { useLocalSettings } from "@/core/settings";
import {
  isUltracodeAvailable,
  normalizeUltracodeLimits,
  ULTRACODE_LIMIT_CEILINGS,
  type UltracodeLimits,
} from "@/core/threads/ultracode";

/**
 * Settings → Subagents: how large a workflow Double Plus Ultracode may plan
 * (fork feature, FORK.md §44). Stored per browser and sent with each run in that
 * mode; the Script workflows extension clamps both values to the operator's own
 * limits, so a number here can only make a run smaller.
 */
export function UltracodeLimitsSection() {
  const { t } = useI18n();
  const [settings, setSettings] = useLocalSettings();
  const { data: extensions, isSuccess } = useFrontendExtensions();
  const limits = settings.ultracode;

  return (
    <section
      className="space-y-3 rounded-md border p-4"
      data-testid="ultracode-limits"
    >
      <div className="space-y-1">
        <h3 className="text-sm font-medium">
          {t.settings.subagents.ultracodeTitle}
        </h3>
        <p className="text-muted-foreground text-sm">
          {t.settings.subagents.ultracodeDescription}
        </p>
        {isSuccess && !isUltracodeAvailable(extensions) && (
          <p className="text-muted-foreground text-sm">
            {t.settings.subagents.ultracodeUnavailable}
          </p>
        )}
      </div>
      <div className="grid gap-4 sm:grid-cols-2">
        <LimitField
          label={t.settings.subagents.ultracodeMaxAgents}
          hint={t.settings.subagents.ultracodeRange(
            ULTRACODE_LIMIT_CEILINGS.maxAgents,
          )}
          field="maxAgents"
          limits={limits}
          onCommit={(next) => setSettings("ultracode", next)}
        />
        <LimitField
          label={t.settings.subagents.ultracodeMaxParallel}
          hint={t.settings.subagents.ultracodeRange(
            ULTRACODE_LIMIT_CEILINGS.maxParallel,
          )}
          field="maxParallel"
          limits={limits}
          onCommit={(next) => setSettings("ultracode", next)}
        />
      </div>
    </section>
  );
}

function LimitField({
  label,
  hint,
  field,
  limits,
  onCommit,
}: {
  label: string;
  hint: string;
  field: keyof UltracodeLimits;
  limits: UltracodeLimits;
  onCommit: (next: UltracodeLimits) => void;
}) {
  const id = useId();
  const stored = limits[field];
  const [draft, setDraft] = useState(String(stored));
  // A change from another tab (the storage event) replaces an untouched draft.
  useEffect(() => setDraft(String(stored)), [stored]);

  const commit = () => {
    const parsed = Number(draft);
    const next = normalizeUltracodeLimits({ ...limits, [field]: parsed });
    // Out-of-range or non-integer input snaps back to the stored value rather
    // than being saved as the default the normalizer would substitute.
    if (next[field] !== parsed) {
      setDraft(String(stored));
      return;
    }
    if (parsed !== stored) {
      onCommit(next);
    }
  };

  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="text-sm font-medium">
        {label}
      </label>
      <Input
        id={id}
        inputMode="numeric"
        type="number"
        min={1}
        max={ULTRACODE_LIMIT_CEILINGS[field]}
        step={1}
        value={draft}
        onChange={(event) => setDraft(event.target.value)}
        onBlur={commit}
        onKeyDown={(event) => {
          if (event.key === "Enter") {
            event.currentTarget.blur();
          }
        }}
      />
      <p className="text-muted-foreground text-xs">{hint}</p>
    </div>
  );
}
