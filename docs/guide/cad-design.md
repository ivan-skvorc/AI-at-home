# CAD design page

**Designs** in the sidebar opens a page of its own for drafting a part with the
assistant. You describe the part on the left; the assistant writes it in
OpenSCAD, and the preview on the right redraws in your browser while the code
is still arriving. Every render is kept as a version, you can edit the code or
drag the part's parameters as sliders, and **Finalize** turns the draft into a
checked CadQuery part with STEP, STL, 3MF and GLB files. It is a bundled
extension, `examples/deerflow-extension-cad-design`, on by default; the
maintainer's reasoning is in [FORK.md §58](../../FORK.md).

It sits beside the [CAD parts module](cad-parts.md), not in place of it. In a
chat, `cad_build` builds a part from a CadQuery script in one go. On the design
page you iterate on a fast draft first and build the measured part when the
draft looks right; Finalize is the same `cad_build` underneath.

## Using it

1. **Designs → New design.** Describe the part with its sizes in millimetres.
   The model picker and Thinking apply to this design's turns.
2. **Watch it draw.** While the assistant writes, the preview shows the part
   so far, marked *Live preview: the part so far*, and keeps the last good mesh
   when a partial file does not render. When the file is complete it renders in
   full and the result (errors with their lines, or the size, volume and
   whether it is a closed solid) goes to the assistant on its next turn.
3. **Edit.** The **Code** tab is an editor; a hand edit renders as you type and
   becomes a version when you leave the editor or press Ctrl/⌘+S. The
   **Parameters** tab turns top-level lines such as `width = 40; // [10:1:100]`
   into sliders (`true`/`false` become toggles; a number with no range gets a
   derived one, labelled as such). Dragging redraws without any request to the
   server; releasing writes the value into the file and makes one version. The
   assistant sees your edits as a diff on its next turn, so it builds on them.
   While the assistant is writing, the editor is held read-only.
4. **Versions.** Every render is a version, with its source (model, hand edit,
   slider, repair, finalize) and whether it rendered. Click one to view it and
   make it current; the next prompt or edit branches from it.
5. **Finalize.** On a draft that rendered without errors, Finalize asks the
   assistant to port it to CadQuery with the same parameters and build it with
   `cad_build`. The page shows the draft and the measured part side by side
   (a toggle on a phone), lists the files with download links, and compares the
   sizes.

At 768 px and narrower the page becomes tabs (Prompt, Preview, Code, with the
parameters inside Code), and Preview shows a dot when a new render lands.

## What to expect

- **Your browser runs the draft, not the server.** OpenSCAD is compiled to
  WebAssembly and runs in a background worker of your tab that has no network
  access. The Gateway stores the file and never runs it. The first render after the
  page opens downloads the engine (about 2.7 MB) and checks it against a
  fingerprint built into the page; a file that fails the check is not used.
- **A render has a time limit**: 8 seconds for the live preview, 30 for the
  full render. A file that takes longer is stopped and the page says so. The
  live preview also caps `$fn` at 24, so curves look coarser until the full
  render.
- **One automatic repair, never more.** When the assistant's draft fails to
  render, the page asks it once to fix the file and says so; if the fix fails
  too, it is up to you. An engine that cannot load or times out does not count
  as the draft's error and starts no repair.
- **Finalize compares sizes within 0.5 mm or 2 % per axis**, whichever is
  larger, because the draft is a faceted mesh and the final part has true
  curves and fillets. A part outside that is marked *Built, but the size differs
  from the draft*, and the difference goes to the assistant on its next turn.
  `cad_build` exports the part only when its own stricter checks all pass, so
  when only its box check misses by less than that tolerance, the assistant
  builds once more against the measured size; Finalize says built only once a
  STEP, GLB, STL or 3MF file exists.
- **No text.** The browser build has no fonts, so `text()` does not render; the
  assistant is told to avoid it. Engraved lettering is a job for the final
  CadQuery part, through the CAD module.
- **Designs are yours.** They are stored per user and kept out of the chat
  list. **Delete** moves a design to the Trash, where you can restore it;
  **Delete forever** also deletes its conversation, drafts and build files.

The drafting tool, `scad_draft`, and the design instructions reach design runs
only. Ordinary chats and subagents never see them and pay no tokens for them.

## Configuration

The record is in `config.example.yaml` and was added to existing installs by
config migration 78:

```yaml
plugins:
  - name: cad-design
    package: deerflow-extension-cad-design
    use: deerflow_extension_cad_design:install
    enabled: true
    required: false
    config:
      enabled: true
      storage_path: cad-design/designs.sqlite  # relative = under DEER_FLOW_HOME
      max_source_bytes: 65536    # largest OpenSCAD file a version keeps, 1024 to 262144
```

The design store lives under `DEER_FLOW_HOME`, so `make backup` includes it.
Finalize needs the CAD parts module (`cad`) on. Turn the page off with
`make extension-disable NAME=cad-design` and restart the Gateway; the record
stays, and `make extension-enable NAME=cad-design` turns it back on.

## Measuring it

`make cad-eval MODEL=... CAD_PATH=design` runs the CAD eval's specs through an
OpenSCAD draft first, the way this page does, and scores the final part on the
same ground truth: see [the design path](cad-eval.md#the-design-path).
