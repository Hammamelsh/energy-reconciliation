import "@testing-library/jest-dom/vitest";
import { webcrypto } from "node:crypto";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

// jsdom lacks SubtleCrypto; the app verifies the bundle with it.
if (!globalThis.crypto?.subtle) {
  Object.defineProperty(globalThis, "crypto", { value: webcrypto, configurable: true });
}
if (typeof window !== "undefined" && !window.matchMedia) {
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: (query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: () => {},
      removeListener: () => {},
      addEventListener: () => {},
      removeEventListener: () => {},
      dispatchEvent: () => false,
    }),
  });
}

// jsdom has no canvas and no WebGL: a 2D context is a no-op recorder, WebGL is absent.
// The page must draw nothing and still expose every value as text.
if (typeof HTMLCanvasElement !== "undefined") {
  HTMLCanvasElement.prototype.getContext = function getContext(this: HTMLCanvasElement, kind: string) {
    if (kind !== "2d") return null;
    const calls: string[] = [];
    (this as HTMLCanvasElement & { __calls?: string[] }).__calls = calls;
    const record = (name: string) => () => calls.push(name);
    return {
      fillRect: record("fillRect"),
      clearRect: record("clearRect"),
      putImageData: record("putImageData"),
      createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4), width: w, height: h }),
      fillStyle: "",
    } as unknown as CanvasRenderingContext2D;
  } as typeof HTMLCanvasElement.prototype.getContext;
}
if (typeof window !== "undefined" && !("ResizeObserver" in window)) {
  Object.defineProperty(window, "ResizeObserver", {
    writable: true,
    value: class {
      observe() {}
      unobserve() {}
      disconnect() {}
    },
  });
}

afterEach(() => cleanup());
