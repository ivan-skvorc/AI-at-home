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

// Scene directions are Y-up; the CAD frame is Z-up, so CAD (x, y, z) is (x, z, -y) here.
export const VIEWS = { iso: [1, 1, 1], front: [0, 0, 1], top: [0, 1, 1e-4] };

const element = (tag, className) => {
  const node = document.createElement(tag);
  if (className) node.className = className;
  return node;
};

function geometryOf(model) {
  const geometry = new BufferGeometry();
  geometry.setAttribute("position", new BufferAttribute(model.positions, 3));
  geometry.setAttribute("normal", new BufferAttribute(model.normals, 3));
  if (model.indices) geometry.setIndex(new BufferAttribute(model.indices, 1));
  return geometry;
}

function edgesOf(model) {
  const geometry = new BufferGeometry();
  if (model.edges)
    geometry.setAttribute("position", new BufferAttribute(model.edges, 3));
  return geometry;
}

/**
 * One WebGL context for the life of the design view. Models (prepared by
 * cad-preview's mesh.js: millimetres, Y up) replace the geometry in place; the
 * canvas, renderer and camera stay. Frames are drawn on demand only.
 * `viewport` is the element the canvas fills; `probe` resolves theme colours.
 */
export function createViewer(viewport, { label, onLost }) {
  viewport.tabIndex = 0;
  viewport.setAttribute("aria-label", label);
  const probe = element("span");
  probe.style.display = "none";
  viewport.append(probe);

  const material = new MeshStandardMaterial({
    roughness: 0.65,
    metalness: 0.05,
    side: DoubleSide,
    polygonOffset: true,
    polygonOffsetFactor: 1,
    polygonOffsetUnits: 1,
    transparent: true,
  });
  const finalMaterial = material.clone();
  const edgeMaterial = new LineBasicMaterial({
    transparent: true,
    opacity: 0.7,
  });
  const draft = new Mesh(new BufferGeometry(), material);
  const draftEdges = new LineSegments(new BufferGeometry(), edgeMaterial);
  const final = new Mesh(new BufferGeometry(), finalMaterial);
  const finalEdges = new LineSegments(new BufferGeometry(), edgeMaterial);
  const draftGroup = new Object3D();
  draftGroup.add(draft, draftEdges);
  const finalGroup = new Object3D();
  finalGroup.add(final, finalEdges);
  const scene = new Scene();
  scene.add(draftGroup, finalGroup, new HemisphereLight(0xffffff, 0x8a8a8a, 2));
  const camera = new PerspectiveCamera(30, 1, 0.1, 1000);
  const headlight = new DirectionalLight(0xffffff, 1.4);
  const aim = new Object3D();
  aim.position.set(0, 0, -1);
  headlight.position.set(0.25, 0.5, 0);
  headlight.target = aim;
  camera.add(headlight, aim);
  scene.add(camera);

  let draftModel = null;
  let finalModel = null;
  let compare = "draft";
  let renderer = null;
  let controls = null;
  let canvas = null;
  let frame = 0;
  let disposed = false;
  // The camera follows the model (re-framed as it grows) until the user moves it.
  let userMoved = false;
  let fittedBox = null;

  const swatch = element("canvas");
  swatch.width = swatch.height = 1;
  const paint = swatch.getContext("2d", { willReadFrequently: true });
  const resolve = (token, fallback) => {
    probe.style.color = `var(${token}, ${fallback})`;
    if (!paint) return [128, 128, 128];
    paint.clearRect(0, 0, 1, 1);
    paint.fillStyle = fallback;
    paint.fillStyle = getComputedStyle(probe).color;
    paint.fillRect(0, 0, 1, 1);
    return [...paint.getImageData(0, 0, 1, 1).data.slice(0, 3)];
  };
  const setColor = (target, rgb) =>
    target.color.setRGB(
      rgb[0] / 255,
      rgb[1] / 255,
      rgb[2] / 255,
      SRGBColorSpace,
    );
  const applyTheme = () => {
    setColor(edgeMaterial, resolve("--foreground", "#202020"));
    setColor(material, resolve("--muted-foreground", "#8a8a8a"));
    setColor(finalMaterial, resolve("--primary", "#4a6fd0"));
    requestRender();
  };

  const requestRender = () => {
    if (frame || disposed || !renderer) return;
    frame = requestAnimationFrame(() => {
      frame = 0;
      if (!disposed && renderer) renderer.render(scene, camera);
    });
  };

  const box = () => {
    const min = new Vector3(Infinity, Infinity, Infinity);
    const max = new Vector3(-Infinity, -Infinity, -Infinity);
    for (const [group, model] of [
      [draftGroup, draftModel],
      [finalGroup, finalModel],
    ]) {
      if (!model || !group.visible) continue;
      min.min(new Vector3(...model.box.min).add(group.position));
      max.max(new Vector3(...model.box.max).add(group.position));
    }
    return Number.isFinite(min.x) ? { min, max } : null;
  };

  const fit = (direction) => {
    const bounds = box();
    if (!bounds || !controls) return;
    fittedBox = bounds;
    const center = bounds.min.clone().add(bounds.max).multiplyScalar(0.5);
    const radius = Math.max(bounds.max.distanceTo(bounds.min) / 2, 1e-3);
    camera.near = radius / 100;
    camera.far = radius * 1000;
    controls.minDistance = radius * 0.05;
    controls.maxDistance = radius * 200;
    const toward = direction
      ? new Vector3(...direction).normalize()
      : camera.position.clone().sub(controls.target).normalize();
    if (!Number.isFinite(toward.x) || toward.lengthSq() === 0)
      toward.set(...VIEWS.iso).normalize();
    const vertical = (camera.fov * Math.PI) / 180;
    const horizontal = 2 * Math.atan(Math.tan(vertical / 2) * camera.aspect);
    const distance =
      (radius / Math.sin(Math.min(vertical, horizontal) / 2)) * 1.05;
    camera.position.copy(center).addScaledVector(toward, distance);
    controls.target.copy(center);
    camera.updateProjectionMatrix();
    controls.update();
    requestRender();
  };

  const onContextLost = (event) => {
    event.preventDefault();
    onLost?.();
  };
  const onResize = () => {
    const width = viewport.clientWidth;
    const height = viewport.clientHeight;
    if (!width || !height || !renderer) return;
    renderer.setSize(width, height, false);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    controls.keyRotateSpeed = height / 36;
    if (!userMoved && fittedBox) fit();
    requestRender();
  };
  const outgrown = () => {
    const bounds = box();
    if (!bounds) return false;
    if (!fittedBox) return true;
    return !(
      fittedBox.min.x <= bounds.min.x &&
      fittedBox.min.y <= bounds.min.y &&
      fittedBox.min.z <= bounds.min.z &&
      bounds.max.x <= fittedBox.max.x &&
      bounds.max.y <= fittedBox.max.y &&
      bounds.max.z <= fittedBox.max.z
    );
  };
  // Without WebGL (disabled, blocklisted, out of contexts) the viewer stays empty and
  // says so once; the canvas it tried goes, and later models never throw.
  let unavailable = false;
  const ensureRenderer = () => {
    if (renderer || disposed || unavailable) return;
    canvas = element("canvas");
    viewport.prepend(canvas);
    try {
      renderer = new WebGLRenderer({
        canvas,
        antialias: true,
        alpha: true,
        powerPreference: "low-power",
      });
    } catch {
      unavailable = true;
      canvas.remove();
      canvas = null;
      onLost?.();
      return;
    }
    renderer.setClearColor(0x000000, 0);
    renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
    canvas.addEventListener("webglcontextlost", onContextLost);
    controls = new OrbitControls(camera, canvas);
    controls.enableDamping = false;
    controls.autoRotate = false;
    controls.screenSpacePanning = true;
    controls.listenToKeyEvents(viewport);
    controls.addEventListener("change", requestRender);
    controls.addEventListener("start", () => {
      userMoved = true;
    });
    applyTheme();
    onResize();
    resizeObserver.observe(viewport);
  };

  const layout = () => {
    draftGroup.visible = !!draftModel && compare !== "final";
    finalGroup.visible = !!finalModel && compare !== "draft";
    finalGroup.position.set(0, 0, 0);
    if (draftModel && finalModel && compare === "both") {
      // Side by side along X with the bottoms and backs aligned.
      const gap =
        Math.max(draftModel.box.max[0] - draftModel.box.min[0], 1) * 0.2;
      finalGroup.position.set(
        draftModel.box.max[0] + gap - finalModel.box.min[0],
        draftModel.box.min[1] - finalModel.box.min[1],
        draftModel.box.min[2] - finalModel.box.min[2],
      );
    }
  };

  const swap = (mesh, edges, model) => {
    const previous = [mesh.geometry, edges.geometry];
    mesh.geometry = model ? geometryOf(model) : new BufferGeometry();
    edges.geometry = model ? edgesOf(model) : new BufferGeometry();
    for (const geometry of previous) geometry.dispose();
  };

  const resizeObserver = new ResizeObserver(onResize);
  const themeObserver = new MutationObserver(applyTheme);
  themeObserver.observe(document.documentElement, {
    attributes: true,
    attributeFilter: ["class", "style", "data-theme"],
  });
  const scheme = window.matchMedia("(prefers-color-scheme: dark)");
  scheme.addEventListener("change", applyTheme);

  return {
    /** Show a draft model in place of the last; `partial` dims it while the code streams. */
    setDraft(model, { partial = false } = {}) {
      ensureRenderer();
      draftModel = model;
      swap(draft, draftEdges, model);
      material.opacity = partial ? 0.55 : 1;
      material.depthWrite = !partial;
      layout();
      if (model && (!userMoved || outgrown())) fit();
      requestRender();
    },
    setFinal(model) {
      ensureRenderer();
      finalModel = model;
      swap(final, finalEdges, model);
      layout();
      requestRender();
    },
    setCompare(mode) {
      compare = mode;
      layout();
      fit();
    },
    hasDraft: () => !!draftModel,
    fit: (direction) => fit(direction),
    /** Forget the camera so the next model is framed afresh (a different design). */
    reset() {
      userMoved = false;
      fittedBox = null;
      draftModel = finalModel = null;
      swap(draft, draftEdges, null);
      swap(final, finalEdges, null);
      compare = "draft";
      layout();
      requestRender();
    },
    resize: onResize,
    dispose() {
      if (disposed) return;
      disposed = true;
      if (frame) cancelAnimationFrame(frame);
      resizeObserver.disconnect();
      themeObserver.disconnect();
      scheme.removeEventListener("change", applyTheme);
      if (controls) {
        controls.stopListenToKeyEvents();
        controls.dispose();
      }
      for (const object of [draft, draftEdges, final, finalEdges])
        object.geometry.dispose();
      material.dispose();
      finalMaterial.dispose();
      edgeMaterial.dispose();
      if (renderer) {
        canvas.removeEventListener("webglcontextlost", onContextLost);
        renderer.renderLists.dispose();
        renderer.dispose();
        renderer.forceContextLoss();
        canvas.width = canvas.height = 0;
        canvas.remove();
      }
      renderer = null;
      swatch.width = swatch.height = 0;
      probe.remove();
    },
  };
}
