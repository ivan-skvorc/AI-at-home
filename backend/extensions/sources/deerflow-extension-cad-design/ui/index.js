// The entry stays tiny: the page, three.js and CodeMirror load when it opens,
// and OpenSCAD's WebAssembly when the first render is asked for.
export default {
  apiVersion: 1,
  module: "cad-design",
  surfaces: [
    {
      id: "designs",
      slot: "page",
      title: "Designs",
      navigation: { label: "Designs", labelZh: "设计", icon: "box" },
      layout: "full",
      mount(root, context) {
        const controller = new AbortController();
        const abort = () => controller.abort();
        context.signal.addEventListener("abort", abort, { once: true });
        if (context.signal.aborted) abort();
        let dispose = () => {};
        if (!controller.signal.aborted)
          import("./page.js")
            .then(({ mountPage }) => {
              if (controller.signal.aborted) return;
              dispose = mountPage(root, {
                ...context,
                signal: controller.signal,
              });
            })
            .catch(() => {
              if (controller.signal.aborted) return;
              root.textContent = "The design page could not be loaded.";
            });
        return {
          dispose() {
            controller.abort();
            context.signal.removeEventListener("abort", abort);
            dispose();
            root.replaceChildren();
          },
        };
      },
    },
  ],
};
