// The entry stays tiny: three.js loads only when a model is opened.
export default {
  apiVersion: 1,
  module: "cad-preview",
  artifactPreviews: [
    {
      id: "model",
      extensions: ["glb", "stl"],
      mount(root, context) {
        const controller = new AbortController();
        const abort = () => controller.abort();
        context.signal.addEventListener("abort", abort, { once: true });
        if (context.signal.aborted) abort();
        let dispose = () => {};
        if (!controller.signal.aborted)
          import("./viewer.js")
            .then(async ({ mountViewer }) => {
              if (controller.signal.aborted) return;
              dispose = await mountViewer(root, { ...context, signal: controller.signal });
              if (controller.signal.aborted) dispose();
            })
            .catch(() => {
              if (!controller.signal.aborted) context.onError();
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
