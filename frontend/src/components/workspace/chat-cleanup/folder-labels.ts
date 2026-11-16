import { parentIdOfFolder, type ChatFolder } from "@/core/threads/chat-folders";

/**
 * A folder's display label with its ancestors, "Work / Python", so two
 * subfolders that share a name stay tellable apart in a flat list. Walks at
 * most the list's length, so a malformed parent loop cannot hang the render.
 */
export function folderPathLabel(
  folders: readonly ChatFolder[],
  folderId: string,
): string {
  const byId = new Map(folders.map((folder) => [folder.id, folder]));
  const names: string[] = [];
  const seen = new Set<string>();
  let current = byId.get(folderId);
  while (current && !seen.has(current.id) && names.length <= folders.length) {
    seen.add(current.id);
    names.unshift(current.name);
    const parentId = parentIdOfFolder(current);
    current = parentId ? byId.get(parentId) : undefined;
  }
  return names.join(" / ");
}
