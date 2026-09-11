/**
 * The 3D terrain scene: one instanced mesh of 17,520 boxes, an orthographic camera, no
 * auto-rotation, rendered only when something changed. Three.js only; no React here.
 *
 * World units: one slot = one date = 1 unit. X runs along the 48 half-hour labels (00:00
 * nearest the viewer in the default view), Z along the date labels (January at the left in
 * the default view), Y is height: the cell's value over the mode's zero-based maximum,
 * times HMAX. Both modes use the same HMAX and their own labelled scale bar, so a change
 * of mode is a change of units, shown as such, not a stretch of one axis.
 *
 * Cells are discrete boxes with a gap between them. A cell with no charged reading is not
 * drawn at all; a cell whose readings sum to zero is a thin slab. Nothing is interpolated.
 */
import {
  BoxGeometry,
  BufferGeometry,
  DynamicDrawUsage,
  Float32BufferAttribute,
  InstancedBufferAttribute,
  InstancedMesh,
  LineBasicMaterial,
  LineSegments,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  OrthographicCamera,
  PlaneGeometry,
  Raycaster,
  RawShaderMaterial,
  Scene,
  Vector2,
  Vector3,
  WebGLRenderer,
} from "three";
import { heightNorm, monthStarts, type Mode, type Terrain } from "../../lib/terrain";
import { BAND_RGB, type Highlight } from "./flat";

export const HMAX = 34; // world units for the tallest cell in either mode
const GAP = 0.16; // the floor visible between cells
const SLAB = 0.06; // a recorded zero: present, flat
const BAND_INDEX: Record<string, number> = { L: 0, N: 1, H: 2, "-": 3 };
const FILTER_INDEX: Record<Highlight, number> = { all: -1, Low: 0, Normal: 1, High: 2, none: 3 } as Record<Highlight, number>;

export type ViewPreset = "default" | "top" | "side";
const PRESETS: Record<ViewPreset, { az: number; el: number }> = {
  default: { az: -74, el: 30 },
  top: { az: -90, el: 89 },
  side: { az: -90, el: 12 },
};

const VERT = /* glsl */ `
precision highp float;
attribute vec3 position;
attribute vec3 normal;
attribute mat4 instanceMatrix;
attribute float aBand;
attribute float aIdx;
attribute float aValue;
uniform mat4 projectionMatrix;
uniform mat4 modelViewMatrix;
uniform mat3 normalMatrix;
varying vec3 vNormalView;
varying vec3 vNormalLocal;
varying vec3 vLocal;
varying float vBand;
varying float vIdx;
varying float vValue;
void main() {
  vec4 p = instanceMatrix * vec4(position, 1.0);
  vLocal = position;
  vNormalLocal = normal;
  vNormalView = normalize(normalMatrix * normal);
  vBand = aBand;
  vIdx = aIdx;
  vValue = aValue;
  gl_Position = projectionMatrix * modelViewMatrix * p;
}`;

const FRAG = /* glsl */ `
precision highp float;
uniform vec3 uPalette[4];
uniform vec3 uLight;
uniform float uFilter;
uniform float uHover;
uniform float uCursor;
varying vec3 vNormalView;
varying vec3 vNormalLocal;
varying vec3 vLocal;
varying float vBand;
varying float vIdx;
varying float vValue;
void main() {
  int b = int(vBand + 0.5);
  vec3 c = b == 0 ? uPalette[0] : (b == 1 ? uPalette[1] : (b == 2 ? uPalette[2] : uPalette[3]));
  // the same value that sets the height also sets brightness, so the top-down view reads
  c *= 0.55 + 0.45 * vValue;
  // High-price cells carry stripes on their top face, Low-price cells a dot: shape as well
  // as hue, visible once the view is zoomed in
  if (vNormalLocal.y > 0.9) {
    if (b == 2 && fract((vLocal.x + vLocal.z) * 3.0) < 0.4) c *= 0.55;
    if (b == 0 && length(vLocal.xz) < 0.16) c *= 0.5;
  }
  if (uFilter >= 0.0 && abs(vBand - uFilter) > 0.5) c = mix(c, vec3(0.06, 0.075, 0.105), 0.78);
  if (abs(vIdx - uCursor) < 0.5) c = vec3(1.0);
  else if (abs(vIdx - uHover) < 0.5) c = mix(c, vec3(1.0), 0.55);
  float d = max(dot(vNormalView, normalize(uLight)), 0.0);
  gl_FragColor = vec4(c * (0.58 + 0.42 * d), 1.0);
}`;

export type Handle = {
  readonly width: number;
  readonly depth: number;
  setMode(mode: Mode, animate: boolean): void;
  setHighlight(h: Highlight): void;
  setCursor(i: number | null): void;
  setHover(i: number | null): void;
  setView(v: ViewPreset): void;
  setZoom(z: number): void;
  orbit(dAz: number, dEl: number): void;
  pick(cssX: number, cssY: number): number | null;
  project(x: number, y: number, z: number): { x: number; y: number; visible: boolean };
  onCamera(cb: () => void): void;
  resize(): void;
  dispose(): void;
  readonly elevation: number;
  /** Diagnostics read by the measurements: frames rendered and matrices updated. */
  readonly stats: { frames: number; matrixUpdates: number; lastPickMs: number };
};

/** True when a WebGL context can be created at all; probed on a throwaway canvas. */
export function webglAvailable(): boolean {
  try {
    const c = document.createElement("canvas");
    return !!(c.getContext("webgl2") ?? c.getContext("webgl"));
  } catch {
    return false;
  }
}

function toRgb([r, g, b]: [number, number, number]): Vector3 {
  return new Vector3(r / 255, g / 255, b / 255);
}

export function createScene(
  canvas: HTMLCanvasElement,
  terrain: Terrain,
  opts: { onContextLost: (why: string) => void },
): Handle {
  const W = terrain.grid.slots;
  const D = terrain.grid.dates;
  const N = terrain.grid.cells;
  const renderer = new WebGLRenderer({ canvas, antialias: true, alpha: false, powerPreference: "low-power" });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 2));
  renderer.setClearColor(0x0f131b, 1);
  const scene = new Scene();
  const camera = new OrthographicCamera(-1, 1, 1, -1, -500, 500);

  // ------------------------------------------------------------- the cells
  const box = new BoxGeometry(1 - GAP, 1, 1 - GAP);
  box.translate(0, 0.5, 0); // y from 0 to 1, scaled per instance
  const hK = new Float32Array(N);
  const hG = new Float32Array(N);
  const band = new Float32Array(N);
  const idx = new Float32Array(N);
  const value = new Float32Array(N);
  for (let i = 0; i < N; i++) {
    const k = terrain.cells.kwh[i];
    const g = terrain.cells.charge[i];
    hK[i] = k === null ? -1 : heightNorm(k, terrain.scale.kwh.max);
    hG[i] = g === null ? -1 : heightNorm(g, terrain.scale.charge.max);
    band[i] = BAND_INDEX[terrain.cells.band[i]] ?? 3;
    idx[i] = i;
  }
  box.setAttribute("aBand", new InstancedBufferAttribute(band, 1));
  box.setAttribute("aIdx", new InstancedBufferAttribute(idx, 1));
  const valueAttr = new InstancedBufferAttribute(value, 1);
  valueAttr.setUsage(DynamicDrawUsage);
  box.setAttribute("aValue", valueAttr);
  const material = new RawShaderMaterial({
    vertexShader: VERT,
    fragmentShader: FRAG,
    uniforms: {
      uPalette: { value: [toRgb(BAND_RGB.Low), toRgb(BAND_RGB.Normal), toRgb(BAND_RGB.High), new Vector3(0.2, 0.2, 0.2)] },
      uLight: { value: new Vector3(-0.4, 0.9, 0.6) },
      uFilter: { value: -1 },
      uHover: { value: -2 },
      uCursor: { value: -2 },
    },
  });
  const mesh = new InstancedMesh(box, material, N);
  mesh.frustumCulled = false;
  scene.add(mesh);

  // the floor and month lines: an instrument grid, not decoration
  const floor = new Mesh(new PlaneGeometry(W + 0.4, D + 0.4), new MeshBasicMaterial({ color: 0x0b0e14 }));
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -0.02;
  scene.add(floor);
  const lines: number[] = [];
  const xOf = (s: number) => s - W / 2;
  const zOf = (j: number) => j - D / 2;
  for (const m of monthStarts(terrain.grid.date_labels)) {
    lines.push(xOf(0), 0, zOf(m.dateIndex), xOf(W), 0, zOf(m.dateIndex));
  }
  lines.push(xOf(0), 0, zOf(D), xOf(W), 0, zOf(D));
  for (const x of [xOf(0), xOf(W)]) lines.push(x, 0, zOf(0), x, 0, zOf(D));
  const grid = new BufferGeometry();
  grid.setAttribute("position", new Float32BufferAttribute(lines, 3));
  scene.add(new LineSegments(grid, new LineBasicMaterial({ color: 0x3a4459 })));

  // ------------------------------------------------------------ heights
  const stats = { frames: 0, matrixUpdates: 0, lastPickMs: 0 };
  const m4 = new Matrix4();
  let current = new Float32Array(N); // the normalised height now shown, per cell
  const apply = (from: Float32Array, to: Float32Array, t: number) => {
    for (let i = 0; i < N; i++) {
      const a = from[i];
      const b = to[i];
      const v = a < 0 || b < 0 ? Math.max(a, b) : a + (b - a) * t;
      current[i] = v;
      const dateIndex = Math.floor(i / W);
      const slot = i - dateIndex * W;
      if (v < 0) {
        m4.makeScale(0, 0, 0); // no reading: not drawn
      } else {
        m4.makeScale(1, Math.max(v * HMAX, SLAB), 1);
        m4.setPosition(xOf(slot) + 0.5, 0, zOf(dateIndex) + 0.5);
      }
      mesh.setMatrixAt(i, m4);
      value[i] = Math.max(v, 0);
    }
    mesh.instanceMatrix.needsUpdate = true;
    valueAttr.needsUpdate = true;
    stats.matrixUpdates += N;
    mesh.computeBoundingSphere();
  };
  let mode: Mode = "charge";
  let animation: number | null = null;
  const target = () => (mode === "kwh" ? hK : hG);
  apply(target(), target(), 1);

  // ------------------------------------------------------------- camera
  let az = PRESETS.default.az;
  let el = PRESETS.default.el;
  let zoom = 1;
  let focusCell: number | null = null;
  const cameraListeners: (() => void)[] = [];
  const corners: Vector3[] = [];
  for (const x of [xOf(0) - 2, xOf(W) + 2]) for (const y of [0, HMAX]) for (const z of [zOf(0) - 2, zOf(D) + 2]) corners.push(new Vector3(x, y, z));
  const tmp = new Vector3();
  const placeCamera = () => {
    const rad = Math.PI / 180;
    const dir = new Vector3(Math.cos(el * rad) * Math.sin(az * rad), Math.sin(el * rad), Math.cos(el * rad) * Math.cos(az * rad));
    const centre = new Vector3(0, HMAX / 4, 0);
    if (zoom > 1 && focusCell !== null) {
      const dateIndex = Math.floor(focusCell / W);
      centre.set(xOf(focusCell - dateIndex * W) + 0.5, 0, zOf(dateIndex) + 0.5);
    }
    camera.position.copy(centre).addScaledVector(dir, 400);
    camera.up.set(0, 1, 0);
    camera.lookAt(centre);
    camera.updateMatrixWorld();
    // fit the orthographic frustum to the projected extent of the grid box, at the aspect
    // of the canvas, so nothing is cropped at zoom 1
    const inv = camera.matrixWorldInverse;
    let minX = Infinity;
    let maxX = -Infinity;
    let minY = Infinity;
    let maxY = -Infinity;
    for (const c of corners) {
      tmp.copy(c).applyMatrix4(inv);
      minX = Math.min(minX, tmp.x);
      maxX = Math.max(maxX, tmp.x);
      minY = Math.min(minY, tmp.y);
      maxY = Math.max(maxY, tmp.y);
    }
    const cw = canvas.clientWidth || 1;
    const ch = canvas.clientHeight || 1;
    const aspect = cw / ch;
    const margin = 1.16; // room for the axis labels drawn by the overlay
    let halfW = ((maxX - minX) / 2) * margin;
    let halfH = ((maxY - minY) / 2) * margin;
    if (halfW / halfH > aspect) halfH = halfW / aspect;
    else halfW = halfH * aspect;
    const cx = zoom > 1 ? 0 : (minX + maxX) / 2;
    const cy = zoom > 1 ? 0 : (minY + maxY) / 2;
    camera.left = cx - halfW / zoom;
    camera.right = cx + halfW / zoom;
    camera.top = cy + halfH / zoom;
    camera.bottom = cy - halfH / zoom;
    camera.updateProjectionMatrix();
    for (const cb of cameraListeners) cb();
  };

  // ------------------------------------------------------------ rendering
  let pending = false;
  const render = () => {
    pending = false;
    renderer.render(scene, camera);
    stats.frames += 1;
  };
  const requestRender = () => {
    if (pending) return;
    pending = true;
    requestAnimationFrame(render);
  };
  const resize = () => {
    const cw = canvas.clientWidth || 1;
    const ch = canvas.clientHeight || 1;
    renderer.setSize(cw, ch, false);
    placeCamera();
    requestRender();
  };
  resize();

  const raycaster = new Raycaster();
  const ndc = new Vector2();
  const onLost = (e: Event) => {
    e.preventDefault();
    opts.onContextLost("the graphics context was lost");
  };
  canvas.addEventListener("webglcontextlost", onLost);

  return {
    width: W,
    depth: D,
    get elevation() {
      return el;
    },
    stats,
    setMode(next, animate) {
      if (next === mode) return;
      const from = Float32Array.from(current);
      mode = next;
      const to = target();
      if (animation !== null) cancelAnimationFrame(animation);
      if (!animate) {
        apply(to, to, 1);
        requestRender();
        return;
      }
      const start = performance.now();
      const dur = 600;
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / dur);
        const eased = 1 - Math.pow(1 - t, 3);
        apply(from, to, eased);
        render();
        if (t < 1) animation = requestAnimationFrame(step);
        else animation = null;
      };
      animation = requestAnimationFrame(step);
    },
    setHighlight(h) {
      material.uniforms.uFilter.value = FILTER_INDEX[h] ?? -1;
      requestRender();
    },
    setCursor(i) {
      material.uniforms.uCursor.value = i ?? -2;
      focusCell = i;
      if (zoom > 1) placeCamera();
      requestRender();
    },
    setHover(i) {
      material.uniforms.uHover.value = i ?? -2;
      requestRender();
    },
    setView(v) {
      az = PRESETS[v].az;
      el = PRESETS[v].el;
      placeCamera();
      requestRender();
    },
    setZoom(z) {
      zoom = z;
      placeCamera();
      requestRender();
    },
    orbit(dAz, dEl) {
      az += dAz;
      el = Math.max(5, Math.min(89, el + dEl));
      placeCamera();
      requestRender();
    },
    pick(cssX, cssY) {
      const t0 = performance.now();
      const cw = canvas.clientWidth || 1;
      const ch = canvas.clientHeight || 1;
      ndc.set((cssX / cw) * 2 - 1, -((cssY / ch) * 2 - 1));
      raycaster.setFromCamera(ndc, camera);
      const hit = raycaster.intersectObject(mesh, false)[0];
      stats.lastPickMs = performance.now() - t0;
      const i = hit?.instanceId ?? null;
      return i !== null && current[i] >= 0 ? i : null;
    },
    project(x, y, z) {
      tmp.set(x, y, z).project(camera);
      return {
        x: ((tmp.x + 1) / 2) * (canvas.clientWidth || 1),
        y: ((1 - tmp.y) / 2) * (canvas.clientHeight || 1),
        visible: tmp.x >= -1.05 && tmp.x <= 1.05 && tmp.y >= -1.05 && tmp.y <= 1.05,
      };
    },
    onCamera(cb) {
      cameraListeners.push(cb);
      cb();
    },
    resize,
    dispose() {
      if (animation !== null) cancelAnimationFrame(animation);
      canvas.removeEventListener("webglcontextlost", onLost);
      box.dispose();
      material.dispose();
      grid.dispose();
      floor.geometry.dispose();
      (floor.material as MeshBasicMaterial).dispose();
      renderer.dispose();
    },
  };
}
