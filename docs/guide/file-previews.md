# File attachments and previews

## Attachments and downloads

Attachments show individual ready, uploading, uploaded, failed and cancelled states.
Failed uploads retain per-file error details; session-state messages remain localized.
Retry a failed file or remove it before sending again; successful uploads and the
message draft are retained. File cards share format icons and preserve extensions
in long filenames. Sent attachments open in the right-hand artifact panel.
Single-file downloads show preparation and retry feedback while preventing duplicate
requests. Unsupported formats offer the original file for download.
Public Showcase files keep their standalone viewer and download controls available
without requiring sign-in.

Deployments can add binary readers through the optional `artifactPreviews` browser
contribution; see the [plugin contract](../full-stack-plugins.md#artifact-previews).

## Office artifact preview extension

The optional [Office preview package](../../examples/deerflow-extension-office-preview/README.md)
adds read-only XLSX, DOCX and PPTX readers with search, worksheet/page navigation,
Word outlines, PowerPoint thumbnails and per-file reading preferences. It requires
the artifact-preview host contribution and operator installation; it is not enabled
by a catalog entry alone. Legacy binary Office files retain the download fallback.
Previews also work over LAN HTTP. Reading preferences use the file's ETag when
available, with an optional content hash on secure origins; without either, files
still open but reading preferences are not restored.
Office preview validates ZIP metadata before loading, prepares files in a cancellable
Worker with a deadline, and limits XML/layout and image sizes before DOM rendering.
Word XML/model preparation and PPT conversion run in that Worker; the UI receives
bounded models with images and document relationships preserved.
Files exceeding preview budgets retain the original-file download fallback.

See the [Office package guide](../../examples/deerflow-extension-office-preview/README.md)
for installation, supported formats, resource limits and validation commands.

A file over the 25 MiB preview cap shows "larger than the 25 MiB preview limit" with
a download, for every preview extension.

## CAD model preview extension

The [CAD model preview](../../examples/deerflow-extension-cad-preview/README.md)
draws `.glb` and `.stl` files as a model you can rotate, in the panel, the Files view
and the standalone reader, on desktop and phone widths. It ships installed and
enabled in this fork, beside the CAD module whose files it shows; turn it off with
`make extension-disable NAME=cad-preview`, after which GLB and STL files keep the
download fallback.

- Drag to rotate, scroll or pinch to zoom, right-drag to pan; Fit, Reset, Top,
  Front and Iso views and an Edges toggle. The view is drawn only when it changes
  and never turns by itself.
- `Bounding box X × Y × Z mm (from the mesh)` is shown along the CAD axes, Z up.
  A GLB is read as metres (the glTF unit) and an STL as millimetres.
- A `*.failed.glb` from a build that failed a check carries a banner naming the
  build's report file.
- Over 1,000,000 triangles or vertices, 20,000 parts, or a GLB the strict reader
  refuses (external buffers, required extensions such as Draco, broken indices),
  the panel says why and offers the original as a download.

Parsing runs in a Worker per file with a 15-second deadline; closing or switching
the preview releases its WebGL context. The original file downloads unchanged.
