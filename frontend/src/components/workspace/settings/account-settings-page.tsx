"use client";

import { LogOutIcon } from "lucide-react";
import { useEffect, useState } from "react";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Switch } from "@/components/ui/switch";
import { fetch, getCsrfHeaders } from "@/core/api/fetcher";
import { useAuth } from "@/core/auth/AuthProvider";
import { parseAuthError } from "@/core/auth/types";
import { useI18n } from "@/core/i18n/hooks";
import {
  getMultiUserMode,
  setMultiUserMode,
} from "@/core/settings/multi-user-mode";

import { SettingsSection } from "./settings-section";

export function AccountSettingsPage() {
  const { user, logout } = useAuth();
  const { t } = useI18n();
  const isSsoUser = Boolean(user?.oauth_provider);
  const [currentPassword, setCurrentPassword] = useState("");
  const [newPassword, setNewPassword] = useState("");
  const [confirmPassword, setConfirmPassword] = useState("");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(false);

  // Multi-user mode is a server-wide setting (fork feature). Default ON = each
  // login only sees its own conversations; OFF = one shared workspace where all
  // conversations are visible regardless of login. Admin-only.
  const isAdmin = user?.system_role === "admin";
  const [multiUserMode, setMultiUserModeState] = useState<boolean | null>(null);
  const [multiUserSaving, setMultiUserSaving] = useState(false);
  const [combineDialogOpen, setCombineDialogOpen] = useState(false);

  useEffect(() => {
    if (!isAdmin) return;
    let cancelled = false;
    void getMultiUserMode()
      .then((value) => {
        if (!cancelled) setMultiUserModeState(value);
      })
      .catch(() => {
        // Leave hidden if the setting can't be read.
      });
    return () => {
      cancelled = true;
    };
  }, [isAdmin]);

  const applyMultiUserMode = async (enabled: boolean) => {
    setMultiUserSaving(true);
    try {
      setMultiUserModeState(await setMultiUserMode(enabled));
    } catch (err) {
      toast.error(err instanceof Error ? err.message : String(err));
    } finally {
      setMultiUserSaving(false);
    }
  };

  const handleMultiUserToggle = (next: boolean) => {
    // Re-enabling isolation is safe and immediate; turning it OFF combines all
    // histories, so confirm first.
    if (next) {
      void applyMultiUserMode(true);
    } else {
      setCombineDialogOpen(true);
    }
  };

  const handleConfirmCombine = async () => {
    await applyMultiUserMode(false);
    setCombineDialogOpen(false);
  };

  const handleChangePassword = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    setMessage("");

    if (newPassword !== confirmPassword) {
      setError(t.settings.account.passwordMismatch);
      return;
    }
    if (newPassword.length < 8) {
      setError(t.settings.account.passwordTooShort);
      return;
    }

    setLoading(true);
    try {
      const res = await fetch("/api/v1/auth/change-password", {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          ...getCsrfHeaders(),
        },
        body: JSON.stringify({
          current_password: currentPassword,
          new_password: newPassword,
        }),
      });

      if (!res.ok) {
        const data = await res.json();
        const authError = parseAuthError(data);
        setError(authError.message);
        return;
      }

      setMessage(t.settings.account.passwordChangedSuccess);
      setCurrentPassword("");
      setNewPassword("");
      setConfirmPassword("");
    } catch {
      setError(t.settings.account.networkError);
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <SettingsSection title={t.settings.account.profileTitle}>
        <div className="space-y-2">
          <div className="grid grid-cols-[max-content_max-content] items-center gap-4">
            <span className="text-muted-foreground text-sm">
              {t.settings.account.email}
            </span>
            <span className="text-sm font-medium">{user?.email ?? "—"}</span>
            <span className="text-muted-foreground text-sm">
              {t.settings.account.role}
            </span>
            <span className="text-sm font-medium capitalize">
              {user?.system_role ?? "—"}
            </span>
            {isSsoUser && (
              <>
                <span className="text-muted-foreground text-sm">
                  {t.settings.account.ssoProvider}
                </span>
                <span className="text-sm font-medium capitalize">
                  {user?.oauth_provider}
                </span>
              </>
            )}
          </div>
        </div>
      </SettingsSection>

      {!isSsoUser ? (
        <SettingsSection
          title={t.settings.account.changePasswordTitle}
          description={t.settings.account.changePasswordDescription}
        >
          <form onSubmit={handleChangePassword} className="max-w-sm space-y-3">
            <Input
              type="password"
              placeholder={t.settings.account.currentPassword}
              value={currentPassword}
              onChange={(e) => setCurrentPassword(e.target.value)}
              required
            />
            <Input
              type="password"
              placeholder={t.settings.account.newPassword}
              value={newPassword}
              onChange={(e) => setNewPassword(e.target.value)}
              required
              minLength={8}
            />
            <Input
              type="password"
              placeholder={t.settings.account.confirmNewPassword}
              value={confirmPassword}
              onChange={(e) => setConfirmPassword(e.target.value)}
              required
              minLength={8}
            />
            {error && <p className="text-sm text-red-500">{error}</p>}
            {message && <p className="text-sm text-green-500">{message}</p>}
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={loading}
            >
              {loading
                ? t.settings.account.updating
                : t.settings.account.updatePassword}
            </Button>
          </form>
        </SettingsSection>
      ) : (
        <SettingsSection
          title={t.settings.account.changePasswordTitle}
          description={t.settings.account.ssoPasswordDescription}
        >
          <p className="text-muted-foreground text-sm">
            {t.settings.account.ssoPasswordMessage.replace(
              "{provider}",
              user?.oauth_provider ?? "",
            )}
          </p>
        </SettingsSection>
      )}

      {isAdmin && multiUserMode !== null ? (
        <SettingsSection
          title="Multi-user mode"
          description={
            <div className="flex items-start gap-3">
              <div>
                Keep each login&apos;s conversations separate. Turn this off to
                combine all histories into one shared workspace — everyone who
                can reach this server then sees every conversation, no matter how
                they log in. Leave it on unless this is your own trusted machine.
              </div>
              <div>
                <Switch
                  aria-label="Multi-user mode"
                  checked={multiUserMode}
                  disabled={multiUserSaving}
                  onCheckedChange={handleMultiUserToggle}
                />
              </div>
            </div>
          }
        >
          {!multiUserMode ? (
            <p className="text-muted-foreground rounded-md border border-amber-200 bg-amber-50 p-3 text-sm dark:border-amber-800 dark:bg-amber-950/50">
              Multi-user mode is off: all conversations are visible to anyone who
              can reach this server, regardless of how they log in.
            </p>
          ) : null}
        </SettingsSection>
      ) : null}

      <SettingsSection title="" description="">
        <Button
          variant="destructive"
          size="sm"
          onClick={logout}
          className="gap-2"
        >
          <LogOutIcon className="size-4" />
          {t.settings.account.signOut}
        </Button>
      </SettingsSection>

      <Dialog open={combineDialogOpen} onOpenChange={setCombineDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Combine all conversation histories?</DialogTitle>
            <DialogDescription>
              Turning off multi-user mode merges every conversation into one
              shared workspace. All conversations become visible to anyone who
              can reach this server, no matter which login or device created
              them. You can turn multi-user mode back on at any time to restore
              per-login separation.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => setCombineDialogOpen(false)}
              disabled={multiUserSaving}
            >
              {t.common.cancel}
            </Button>
            <Button
              variant="destructive"
              onClick={() => void handleConfirmCombine()}
              disabled={multiUserSaving}
            >
              {multiUserSaving ? t.common.loading : "Combine histories"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
