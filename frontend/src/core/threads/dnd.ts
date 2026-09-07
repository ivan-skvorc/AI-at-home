/**
 * Drag-and-drop payload types for the sidebar chat tree.
 *
 * A chat row advertises its thread id under {@link CHAT_DND_THREAD_MIME} so a
 * folder row (and the tree's root drop zone) can accept it. Kept in its own
 * module because both the drag source and every drop target import it, and a
 * MIME string that drifts between them fails *silently* — the drop is simply
 * ignored, with nothing in the console to say why.
 */

/** A conversation being dragged; the data is the thread id. */
export const CHAT_DND_THREAD_MIME = "application/x-deerflow-thread-id";
