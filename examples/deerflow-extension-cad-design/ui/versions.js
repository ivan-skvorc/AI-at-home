/**
 * The Versions tab's rows, newest first. A version whose parent is not the
 * version just before it was branched from an earlier one (the user stepped
 * back and prompted from there); `branchFrom` names that parent's number.
 */
export function timeline(versions, headId = null) {
  const valid = (Array.isArray(versions) ? versions : []).filter(
    (v) => v && typeof v.id === "string" && Number.isInteger(v.seq),
  );
  const byId = new Map(valid.map((v) => [v.id, v]));
  const bySeq = new Map(valid.map((v) => [v.seq, v]));
  return [...valid]
    .sort((a, b) => b.seq - a.seq)
    .map((v) => {
      const parent = v.parent_id ? byId.get(v.parent_id) : null;
      const previous = bySeq.get(v.seq - 1);
      const render = v.render && typeof v.render === "object" ? v.render : null;
      return {
        id: v.id,
        seq: v.seq,
        source: typeof v.source === "string" ? v.source : "model",
        createdAt: typeof v.created_at === "string" ? v.created_at : null,
        status: !render ? "pending" : render.ok ? "ok" : "error",
        error:
          render && !render.ok && typeof render.error === "string"
            ? render.error
            : null,
        final: v.final && typeof v.final === "object" ? v.final : null,
        parentSeq: parent ? parent.seq : null,
        branchFrom:
          parent && previous && parent.id !== previous.id ? parent.seq : null,
        isHead: v.id === headId,
      };
    });
}
