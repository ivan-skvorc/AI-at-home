import { useMutation } from "@tanstack/react-query";

import { suggestThreadTitle } from "./api";
import { useRenameThread } from "./hooks";

/**
 * The chat header's "Auto rename" (fork feature, FORK.md §38).
 *
 * Two calls, in this order and never merged into one:
 *
 * 1. `POST /api/threads/{id}/title/suggest` writes a title from the
 *    conversation's opening exchanges. It only reads.
 * 2. `useRenameThread` applies it — the same mutation the ⋯-menu rename uses.
 *
 * The split is the design, in both directions. A rename is a checkpoint write
 * and the Gateway refuses one with 409 while a run is in flight; writing the
 * title on the suggest route as well would put that rule in two places, and
 * the new one would not hold `reserve_checkpoint_write`. Delegating step 2
 * rather than re-implementing it is the other half: the rename's cache dance
 * (cancel pending snapshot reads *before* writing the title in, or a response
 * that started earlier restores the old one) has to happen here too, and a
 * second copy of it is a copy that stops matching.
 */
export function useAutoRenameThread() {
  const { mutateAsync: renameThread } = useRenameThread();
  return useMutation({
    mutationFn: async ({
      threadId,
      modelName,
      signal,
    }: {
      threadId: string;
      modelName?: string | null;
      signal?: AbortSignal;
    }): Promise<string> => {
      const { title } = await suggestThreadTitle({
        threadId,
        modelName,
        signal,
      });
      await renameThread({ threadId, title });
      return title;
    },
  });
}
