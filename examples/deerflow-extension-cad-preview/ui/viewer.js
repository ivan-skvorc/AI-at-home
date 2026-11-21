import {
  BufferAttribute,
  BufferGeometry,
  DirectionalLight,
  DoubleSide,
  HemisphereLight,
  LineBasicMaterial,
  LineSegments,
  Mesh,
  MeshStandardMaterial,
  Object3D,
  PerspectiveCamera,
  Scene,
  SRGBColorSpace,
  Vector3,
  WebGLRenderer,
} from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";

import { strings } from "./text.js";
import { prepareInWorker } from "./worker-client.js";

const STYLE = `
:host{display:block;height:100%;min-width:0}*{box-sizing:border-box}
.cad{height:100%;min-width:0;display:flex;flex-direction:column;font:13px system-ui,sans-serif;color:var(--foreground);background:var(--background)}
.bar{display:flex;flex-wrap:wrap;align-items:center;gap:6px;padding:8px 12px;border-bottom:1px solid var(--border)}
.bar button,.fallback a,.lost button{color:inherit;background:var(--background);border:1px solid var(--border);border-radius:6px;min-height:32px;padding:4px 10px;font:inherit;cursor:pointer;text-decoration:none}
.bar button:hover,.fallback a:hover,.lost button:hover{background:var(--accent)}
.bar button[aria-pressed=true]{background:var(--accent);border-color:var(--ring)}
.bar button:disabled{opacity:.5;cursor:default}
button:focus-visible,a:focus-visible,.viewport:focus-visible{outline:2px solid var(--ring);outline-offset:-2px}
.gap{width:6px}
.banner{padding:8px 12px;border-bottom:1px solid var(--border);background:color-mix(in oklch,var(--destructive) 12%,var(--background));overflow-wrap:anywhere}
.viewport{position:relative;flex:1;min-height:0;overflow:hidden}
canvas{position:absolute;inset:0;width:100%;height:100%;display:block}
.dims{position:absolute;left:8px;bottom:8px;max-width:calc(100% - 16px);padding:4px 8px;border:1px solid var(--border);border-radius:6px;background:color-mix(in oklch,var(--background) 85%,transparent);font-variant-numeric:tabular-nums;pointer-events:none;overflow-wrap:anywhere}
.lost{position:absolute;inset:0;display:flex;align-items:center;justify-content:center;gap:8px;background:var(--background)}
.lost[hidden]{display:none}
.status,.fallback{height:100%;display:flex;flex-direction:column;align-items:center;justify-content:center;gap:12px;padding:24px;text-align:center;color:var(--muted-foreground)}
.fallback p{max-width:28rem;margin:0;color:var(--foreground);overflow-wrap:anywhere}
.probe{display:none}
@media (pointer:coarse){.bar button,.fallback a,.lost button{min-height:44px}}
`;

// Scene directions are Y-up; the CAD frame is Z-up, so CAD (x, y, z) is (x, z, -y) here.
const VIEWS = {
  iso: [1, 1, 1], // CAD (1, -1, 1): in front, to the right, above
  front: [0, 0, 1], // CAD -Y
  // Straight down, nudged so the orbit keeps CAD +Y pointing up the screen.
  top: [0, 1, 1e-4],
};

const element = (tag, className, text) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined) node.textContent = text;
  return node;
};

/**
 * Mount the viewer and return its idempotent dispose(). Nothing touches WebGL
 * until the model is prepared, so a preview closed while reading or parsing
 * never creates a context.
 */
export async function mountViewer(root, context) {
  const { signal } = context;
  const text = strings(context.locale);
  const style = element("style");
  style.textContent = STYLE;
  const shell = element("div", "cad");
  const waiting = element("div", "status", text.preparing);
  waiting.setAttribute("role", "status");
  shell.append(waiting);
  root.replaceChildren(style, shell);

  const blobs = [];
  let teardown = () => {};
  let disposed = false;
  const dispose = () => {
    if (disposed) return;
    disposed = true;
    teardown();
    for (const url of blobs.splice(0)) URL.revokeObjectURL(url);
    root.replaceChildren();
  };

  const bytes = await context.readFile();
  if (signal.aborted) return dispose;
  const filename = context.filename;
  const kind = filename.toLowerCase().endsWith(".stl") ? "stl" : "glb";
  let model;
  try {
    model = await prepareInWorker(bytes, kind, signal);
  } catch (error) {
    if (signal.aborted || !error?.code) throw error;
    // A parser reason: say why, and hand over the original bytes unchanged.
    const url = URL.createObjectURL(new Blob([bytes], { type: "application/octet-stream" }));
    blobs.push(url);
    const reason = element("p", "", text.reasons[error.code] ?? text.reasons["invalid-file"]);
    reason.setAttribute("role", "status");
    const link = element("a", "", text.download);
    link.href = url;
    link.download = filename;
    const box = element("div", "fallback");
    box.append(reason, link);
    shell.replaceChildren(box);
    return dispose;
  }
  if (signal.aborted) return dispose;
  return buildView({ shell, model, text, context, filename, dispose, setTeardown: (fn) => (teardown = fn) });
}

function buildView({ shell, model, text, context, filename, dispose, setTeardown }) {
  const failed = /\.failed\.glb$/i.test(filename);
  const bar = element("div", "bar");
  const viewport = element("div", "viewport");
  viewport.tabIndex = 0;
  viewport.setAttribute("aria-label", text.viewport);
  const dims = element("div", "dims");
  dims.setAttribute("role", "status");
  const format = new Intl.NumberFormat(context.locale, { maximumFractionDigits: 2 });
  dims.textContent = text.dimensions(...model.size.map((value) => format.format(value)));
  const lost = element("div", "lost");
  lost.hidden = true;
  lost.setAttribute("role", "alert");
  const reload = element("button", "", text.reload);
  reload.type = "button";
  lost.append(element("span", "", `${text.lost} –`), reload);
  const probe = element("span", "probe");
  viewport.append(dims, lost);
  shell.replaceChildren(bar);
  if (failed) {
    const report = filename.replace(/\.failed\.glb$/i, ".report.json");
    const banner = element("div", "banner", text.failed(report));
    banner.setAttribute("role", "note");
    shell.append(banner);
  }
  shell.append(viewport, probe);

  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(model.positions, 3));
  geometry.setAttribute("normal", new BufferAttribute(model.normals, 3));
  if (model.indices) geometry.setIndex(new BufferAttribute(model.indices, 1));
  const material = new MeshStandardMaterial({
    roughness: 0.65,
    metalness: 0.05,
    side: DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
  });
  const mesh = new Mesh(geometry, material);
  // One draw call; each node's triangle range is kept for picking a body later.
  mesh.userData.groups = model.groups;
  const edgeGeometry = new BufferGeometry();
  if (model.edges) edgeGeometry.setAttribute("position", new BufferAttribute(model.edges, 3));
  const edgeMaterial = new LineBasicMaterial({ transparent: true, opacity: 0.7 });
  const edges = new LineSegments(edgeGeometry, edgeMaterial);
  const scene = new Scene();
  scene.add(mesh, edges);
  scene.add(new HemisphereLight(0xffffff, 0x8a8a8a, 2));
  const camera = new PerspectiveCamera(30, 1, 0.1, 1000);
  // A headlight just above the eye: every face turned towards the viewer is lit.
  const headlight = new DirectionalLight(0xffffff, 1.4);
  const aim = new Object3D();
  aim.position.set(0, 0, -1);
  headlight.position.set(0.25, 0.5, 0);
  headlight.target = aim;
  camera.add(headlight, aim);
  scene.add(camera);

  const [min, max] = [model.box.min, model.box.max];
  const center = new Vector3((min[0] + max[0]) / 2, (min[1] + max[1]) / 2, (min[2] + max[2]) / 2);
  const radius = Math.max(new Vector3(...max).distanceTo(new Vector3(...min)) / 2, 1e-3);
  camera.near = radius / 100;
  camera.far = radius * 1000;

  const saved = context.getReadingState?.();
  const restored = saved?.version === 1 ? saved : {};
  let edgesShown = model.edges ? restored.edges !== false : false;
  edges.visible = edgesShown;

  // Colours come from the host's theme tokens, which may be oklch(): a probe
  // resolves var(), a 1×1 canvas turns any CSS colour into sRGB bytes.
  const swatch = element("canvas");
  swatch.width = swatch.height = 1;
  const paint = swatch.getContext("2d", { willReadFrequently: true });
  const resolve = (token, fallback) => {
    probe.style.color = `var(${token}, ${fallback})`;
    paint.clearRect(0, 0, 1, 1);
    paint.fillStyle = fallback;
    paint.fillStyle = getComputedStyle(probe).color;
    paint.fillRect(0, 0, 1, 1);
    return [...paint.getImageData(0, 0, 1, 1).data.slice(0, 3)];
  };
  const hex = (rgb) => `#${rgb.map((v) => v.toString(16).padStart(2, "0")).join("")}`;
  const applyTheme = () => {
    const edge = resolve("--foreground", "#202020");
    const neutral = resolve("--muted-foreground", "#8a8a8a");
    // A failed part leans to the error colour without hiding its shading.
    const warning = resolve("--destructive", "#c03030");
    const surface = failed ? neutral.map((value, i) => Math.round(value * 0.4 + warning[i] * 0.6)) : neutral;
    edgeMaterial.color.setRGB(edge[0] / 255, edge[1] / 255, edge[2] / 255, SRGBColorSpace);
    material.color.setRGB(surface[0] / 255, surface[1] / 255, surface[2] / 255, SRGBColorSpace);
    if (shell.dataset.edgeColor !== hex(edge)) {
      shell.dataset.edgeColor = hex(edge);
      requestRender();
    }
  };

  let renderer = null;
  let controls = null;
  let canvas = null;
  let frame = 0;
  let disposed = false;
  const requestRender = () => {
    if (frame || disposed || !renderer) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!disposed && renderer) renderer.render(scene, camera);
    });
  };
  const save = () => {
    if (disposed || context.signal.aborted || !controls) return;
    context.saveReadingState?.({
      version: 1,
      position: camera.position.toArray(),
      target: controls.target.toArray(),
      edges: edgesShown,
    });
  };
  const fit = (direction) => {
    const toward = direction
      ? new Vector3(...direction).normalize()
      : camera.position.clone().sub(controls.target).normalize();
    const vertical = (camera.fov * Math.PI) / 180;
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
    const distance = (radius / Math.sin(Math.min(vertical, horizontal) / 2)) * 1.05;
    camera.position.copy(center).addScaledVector(toward, distance);
    controls.target.copy(center);
    controls.update();
    requestRender();
    save();
  };
  const onLost = () => {
    lost.hidden = false;
  };
  const onRestored = () => {
    lost.hidden = true;
    requestRender();
  };
  const onResize = () => {
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    if (!width || !height || !renderer) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    // About ten degrees per key press.
    controls.keyRotateSpeed = height / 36;
    requestRender();
  };

  const createView = () => {
    canvas = element("canvas");
    viewport.prepend(canvas);
    renderer = new WebGLRenderer({ canvas, antialias: true, alpha: true, powerPreference: "low-power" });
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    canvas.addEventListener("webglcontextlost", onLost);
    canvas.addEventListener("webglcontextrestored", onRestored);
    const position = camera.position.clone();
    const target = controls?.target.clone();
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = false;
    controls.autoRotate = false;
    controls.screenSpacePanning = true;
    controls.minDistance = radius * 0.05;
    controls.maxDistance = radius * 200;
    controls.listenToKeyEvents(viewport);
    controls.addEventListener("change", requestRender);
    controls.addEventListener("end", save);
    if (target) {
      camera.position.copy(position);
      controls.target.copy(target);
      controls.update();
    }
    const width = viewport.clientWidth || 1;
    const height = viewport.clientHeight || 1;
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
  };
  const destroyView = () => {
    if (controls) {
      controls.stopListenToKeyEvents();
      controls.dispose();
    }
    if (renderer) {
      canvas.removeEventListener("webglcontextlost", onLost);
      canvas.removeEventListener("webglcontextrestored", onRestored);
      renderer.renderLists.dispose();
      renderer.dispose();
      renderer.forceContextLoss();
      canvas.width = canvas.height = 0;
      canvas.remove();
    }
    renderer = null;
  };

  const resizeObserver = new ResizeObserver(onResize);
  const themeObserver = new MutationObserver(applyTheme);
  const scheme = window.matchMedia("(prefers-color-scheme: dark)");
  setTeardown(() => {
    disposed = true;
    if (frame) cancelAnimationFrame(frame);
    frame = 0;
    resizeObserver.disconnect();
    themeObserver.disconnect();
    scheme.removeEventListener("change", applyTheme);
    if (controls) {
      controls.stopListenToKeyEvents();
      controls.dispose();
      controls = null;
    }
    geometry.dispose();
    edgeGeometry.dispose();
    material.dispose();
    edgeMaterial.dispose();
    destroyView();
    swatch.width = swatch.height = 0;
  });

  try {
    createView();
  } catch {
    dispose();
    context.onError();
    return dispose;
  }
  reload.addEventListener("click", () => {
    destroyView();
    try {
      createView();
      lost.hidden = true;
      onResize();
    } catch {
      dispose();
      context.onError();
    }
  });

  const button = (label, title, action) => {
    const node = element("button", "", label);
    node.type = "button";
    node.title = title;
    node.setAttribute("aria-label", title);
    node.addEventListener("click", action);
    return node;
  };
  const edgesButton = button(text.edges, model.edges ? text.edgesLabel : text.edgesSkipped, () => {
    edgesShown = !edgesShown;
    edges.visible = edgesShown;
    edgesButton.setAttribute("aria-pressed", String(edgesShown));
    requestRender();
    save();
  });
  edgesButton.setAttribute("aria-pressed", String(edgesShown));
  edgesButton.disabled = !model.edges;
  bar.append(
    button(text.fit, text.fitLabel, () => fit()),
    button(text.reset, text.resetLabel, () => fit(VIEWS.iso)),
    element("span", "gap"),
    button(text.top, text.viewLabel(text.top), () => fit(VIEWS.top)),
    button(text.front, text.viewLabel(text.front), () => fit(VIEWS.front)),
    button(text.iso, text.viewLabel(text.iso), () => fit(VIEWS.iso)),
    element("span", "gap"),
    edgesButton,
  );

  applyTheme();
  const vector = (value) => Array.isArray(value) && value.length === 3 && value.every(Number.isFinite);
  if (vector(restored.position) && vector(restored.target)) {
    camera.position.fromArray(restored.position);
    controls.target.fromArray(restored.target);
    controls.update();
  } else fit(VIEWS.iso);
  onResize();
  resizeObserver.observe(viewport);
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "style", "data-theme"],
  });
  scheme.addEventListener("change", applyTheme);
  requestRender();
  return dispose;
}
