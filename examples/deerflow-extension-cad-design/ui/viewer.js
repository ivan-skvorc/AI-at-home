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
 * One WebGL context for the life of the design view. Each body (a model
 * prepared by cad-preview's mesh.js: millimetres, Y up) is one mesh with its
 * edges and its own colour, kept by name: a new model for a body replaces its
 * geometry in place, and the canvas, renderer and camera stay. Frames are
 * drawn on demand only.
 */
export function createViewer(viewport, { label, onLost }) {
  viewport.tabIndex = 0;
  viewport.setAttribute("aria-label", label);
  const probe = element("span");
  probe.style.display = "none";
  viewport.append(probe);

  const edgeMaterial = new LineBasicMaterial({
    transparent: true,
    opacity: 0.7,
  });
  /** name -> { group, mesh, edges, material, model } */
  const bodies = new Map();
  const scene = new Scene();
  scene.add(new HemisphereLight(0xffffff, 0x8a8a8a, 2));
  const camera = new PerspectiveCamera(30, 1, 0.1, 1000);
  const headlight = new DirectionalLight(0xffffff, 1.4);
  const aim = new Object3D();
  aim.position.set(0, 0, -1);
  headlight.position.set(0.25, 0.5, 0);
  headlight.target = aim;
  camera.add(headlight, aim);
  scene.add(camera);

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
  const applyTheme = () => {
    const [r, g, b] = resolve("--foreground", "#202020");
    edgeMaterial.color.setRGB(r / 255, g / 255, b / 255, SRGBColorSpace);
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
    for (const body of bodies.values()) {
      if (!body.model || !body.group.visible) continue;
      min.min(new Vector3(...body.model.box.min));
      max.max(new Vector3(...body.model.box.max));
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

  const release = (body) => {
    scene.remove(body.group);
    body.mesh.geometry.dispose();
    body.edges.geometry.dispose();
    body.material.dispose();
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
    /** Show `model` as body `name` in `color`, replacing that body's last model. */
    setBody(name, model, { color = "#8a8a8a", visible = true } = {}) {
      ensureRenderer();
      let body = bodies.get(name);
      if (!body) {
        const material = new MeshStandardMaterial({
          roughness: 0.65,
          metalness: 0.05,
          side: DoubleSide,
          polygonOffset: true,
          polygonOffsetFactor: 1,
          polygonOffsetUnits: 1,
        });
        const mesh = new Mesh(new BufferGeometry(), material);
        const edges = new LineSegments(new BufferGeometry(), edgeMaterial);
        const group = new Object3D();
        group.add(mesh, edges);
        scene.add(group);
        body = { group, mesh, edges, material, model: null };
        bodies.set(name, body);
      }
      body.material.color.set(color);
      const previous = [body.mesh.geometry, body.edges.geometry];
      body.mesh.geometry = geometryOf(model);
      body.edges.geometry = edgesOf(model);
      for (const geometry of previous) geometry.dispose();
      body.model = model;
      body.group.visible = visible;
      if (!userMoved || outgrown()) fit();
      requestRender();
    },
    setVisible(name, visible) {
      const body = bodies.get(name);
      if (!body) return;
      body.group.visible = visible;
      requestRender();
    },
    /** Drop every body whose name is not in `names`. */
    keep(names) {
      const wanted = new Set(names);
      for (const [name, body] of bodies)
        if (!wanted.has(name)) {
          release(body);
          bodies.delete(name);
        }
      requestRender();
    },
    has: (name) => bodies.has(name),
    hasBodies: () => bodies.size > 0,
    fit: (direction) => fit(direction),
    /** Forget the bodies and the camera so the next design is framed afresh. */
    reset() {
      userMoved = false;
      fittedBox = null;
      for (const body of bodies.values()) release(body);
      bodies.clear();
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
      for (const body of bodies.values()) release(body);
      bodies.clear();
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
