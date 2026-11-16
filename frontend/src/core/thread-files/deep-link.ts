/**
 * `?panel=files` on a chat URL opens that chat's side panel on the Files tab;
 * the chat then removes the parameter so a reload or Back does not reopen it.
 */
export const THREAD_FILES_PANEL_PARAM = "panel";
export const THREAD_FILES_PANEL_VALUE = "files";

interface SearchParamsLike {
  get(name: string): string | null;
  toString(): string;
}

function decodeSegment(segment: string): string | null {
  try {
    return decodeURIComponent(segment);
  } catch {
    return null;
  }
}

/**
 * True when `pathname` is the chat route of `threadId`
 * (`…/chats/{threadId}`, default or custom-agent chat).
 *
 * Keep-alive chats stay mounted for other threads while the URL already names
 * the next one, so only the chat the URL is about may act on its parameters.
 */
export function routeShowsThread(pathname: string, threadId: string): boolean {
  const segments = pathname.split("/").filter(Boolean);
  const last = segments.at(-1);
  return (
    segments.at(-2) === "chats" &&
    last !== undefined &&
    decodeSegment(last) === threadId
  );
}

/** True when the URL asks the chat of `threadId` to open its Files tab. */
export function requestsThreadFilesPanel(
  pathname: string,
  searchParams: SearchParamsLike,
  threadId: string,
): boolean {
  return (
    searchParams.get(THREAD_FILES_PANEL_PARAM) === THREAD_FILES_PANEL_VALUE &&
    routeShowsThread(pathname, threadId)
  );
}

/** The same URL without the `panel` parameter, keeping every other one. */
export function withoutThreadFilesPanel(
  pathname: string,
  searchParams: SearchParamsLike,
): string {
  const next = new URLSearchParams(searchParams.toString());
  next.delete(THREAD_FILES_PANEL_PARAM);
  const query = next.toString();
  return query ? `${pathname}?${query}` : pathname;
}
