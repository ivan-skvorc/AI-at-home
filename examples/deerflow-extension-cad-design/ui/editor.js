import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from "@codemirror/commands";
import {
  HighlightStyle,
  StreamLanguage,
  bracketMatching,
  indentOnInput,
  syntaxHighlighting,
} from "@codemirror/language";
import {
  Compartment,
  EditorState,
  StateEffect,
  StateField,
} from "@codemirror/state";
import {
  Decoration,
  EditorView,
  highlightActiveLine,
  keymap,
  lineNumbers,
} from "@codemirror/view";
import { tags } from "@lezer/highlight";

import { openscadMode } from "./scad-language.js";

const highlight = HighlightStyle.define([
  { tag: tags.keyword, color: "var(--cad-keyword)", fontWeight: "600" },
  { tag: tags.comment, color: "var(--muted-foreground)", fontStyle: "italic" },
  { tag: tags.string, color: "var(--cad-string)" },
  { tag: tags.number, color: "var(--cad-number)" },
  { tag: [tags.atom, tags.bool], color: "var(--cad-atom)" },
  {
    tag: [tags.standard(tags.variableName), tags.function(tags.variableName)],
    color: "var(--cad-builtin)",
  },
  {
    tag: tags.definition(tags.variableName),
    color: "var(--cad-builtin)",
    fontWeight: "600",
  },
]);

const theme = EditorView.theme({
  "&": {
    height: "100%",
    color: "var(--foreground)",
    backgroundColor: "var(--background)",
    fontSize: "13px",
  },
  ".cm-scroller": {
    fontFamily: "ui-monospace, SFMono-Regular, Menlo, Consolas, monospace",
    lineHeight: "1.5",
  },
  ".cm-content": { caretColor: "var(--foreground)" },
  ".cm-gutters": {
    backgroundColor: "var(--background)",
    color: "var(--muted-foreground)",
    borderRight: "1px solid var(--border)",
  },
  ".cm-activeLine": {
    backgroundColor: "color-mix(in oklch, var(--accent) 50%, transparent)",
  },
  ".cm-activeLineGutter": { backgroundColor: "transparent" },
  "&.cm-focused": { outline: "2px solid var(--ring)", outlineOffset: "-2px" },
  ".cm-selectionBackground, &.cm-focused .cm-selectionBackground": {
    backgroundColor:
      "color-mix(in oklch, var(--ring) 30%, transparent) !important",
  },
  ".cm-error-line": {
    backgroundColor: "color-mix(in oklch, var(--destructive) 15%, transparent)",
  },
});

const setErrors = StateEffect.define();
const errorField = StateField.define({
  create: () => Decoration.none,
  update(value, transaction) {
    value = value.map(transaction.changes);
    for (const effect of transaction.effects)
      if (effect.is(setErrors)) {
        const lines = [...new Set(effect.value)]
          .filter((n) => n >= 1 && n <= transaction.state.doc.lines)
          .sort((a, b) => a - b);
        value = Decoration.set(
          lines.map((n) =>
            Decoration.line({ class: "cm-error-line" }).range(
              transaction.state.doc.line(n).from,
            ),
          ),
        );
      }
    return value;
  },
  provide: (field) => EditorView.decorations.from(field),
});

/**
 * The Code tab's editor. `onChange(text)` fires for the user's edits only;
 * `onSave()` on Ctrl/Cmd+S and when the editor loses focus.
 */
export function createEditor(
  parent,
  { doc = "", root, label, onChange, onSave },
) {
  const editable = new Compartment();
  let programmatic = false;
  const view = new EditorView({
    parent,
    root,
    state: EditorState.create({
      doc,
      extensions: [
        lineNumbers(),
        history(),
        highlightActiveLine(),
        bracketMatching(),
        indentOnInput(),
        StreamLanguage.define(openscadMode),
        syntaxHighlighting(highlight),
        errorField,
        theme,
        editable.of([
          EditorState.readOnly.of(false),
          EditorView.editable.of(true),
        ]),
        keymap.of([
          { key: "Mod-s", preventDefault: true, run: () => (onSave(), true) },
          indentWithTab,
          ...defaultKeymap,
          ...historyKeymap,
        ]),
        EditorView.contentAttributes.of({ "aria-label": label }),
        EditorView.updateListener.of((update) => {
          if (update.docChanged && !programmatic)
            onChange(update.state.doc.toString());
        }),
        EditorView.domEventHandlers({ blur: () => onSave() }),
      ],
    }),
  });
  return {
    view,
    getDoc: () => view.state.doc.toString(),
    setDoc(text) {
      if (text === view.state.doc.toString()) return;
      programmatic = true;
      try {
        view.dispatch({
          changes: { from: 0, to: view.state.doc.length, insert: text },
        });
      } finally {
        programmatic = false;
      }
    },
    setReadOnly(readOnly) {
      view.dispatch({
        effects: editable.reconfigure([
          EditorState.readOnly.of(readOnly),
          EditorView.editable.of(!readOnly),
        ]),
      });
    },
    markErrors(lines) {
      view.dispatch({ effects: setErrors.of(lines ?? []) });
    },
    goToLine(n) {
      if (n < 1 || n > view.state.doc.lines) return;
      const line = view.state.doc.line(n);
      view.dispatch({ selection: { anchor: line.from }, scrollIntoView: true });
      view.focus();
    },
    dispose: () => view.destroy(),
  };
}
