### Fork-specific frontend notes

The full notes, with the tests that pin each rule, are in
[FORK_NOTES.md](FORK_NOTES.md); rationale is in [FORK.md](../../../../../FORK.md).
Read them before you change this directory. The rules that break silently:

- **Live chat slots.** `chat-instance.tsx` is fully controlled; the keep-alive
  viewport above the route mounts one `<ChatInstance>` per slot and hides the
  inactive ones with `display:none`. `syncRoute` matches a slot by its stable
  key, never by the thread id, because the new-to-real rewrite uses
  `history.replaceState`. A background slot is released from an effect after
  `onFinish`, so it never pre-empts the "conversation finished" notification.
  Nothing is persisted and there is no tab strip.
- **Concurrent chats.** Every `thread.submit` sends `onDisconnect: "continue"`
  (the Gateway default cancels the run when you leave). `syncRoute` retains the
  busy slot it leaves; it never retains an `isNew` slot and never evicts one.
- **One resizable group.** `chat-box.tsx` keeps all right panels (artifacts,
  sidecar, browser) in one `ResizablePanelGroup` and opens or closes them through
  the panel handle, not conditional rendering. Mirror a `0%` layout into state
  only from `onLayoutChanged`, after pointer release.
- **Democracy launch.** `deriveModeContext` in `core/threads/run-context.ts` is
  the single derivation of the run booleans and must send
  `max_total_subagents` for a panel. The launch handoff needs both the mount path
  and `DEMOCRACY_LAUNCH_EVENT`, and the task reaches the composer as
  `InputBox`'s `initialValue`, never through `setInput`.
- **Internet switch.** It is a `THREAD_SCOPED_CONTEXT_KEYS` entry, default on,
  sent as a strict boolean by both submit paths.
- **Auto rename.** The suggest route only reads; the title is applied through
  `useRenameThread`, and the picker shares `autoTitle.modelName` with Settings.
