import { defineConfig } from "vitest/config";
import { loadEnv, type Plugin } from "vite";
import react from "@vitejs/plugin-react";

const PLACEHOLDER = "%VITE_SITE_URL%";

// VITE_SITE_URL is the site's public origin, set by the host at build time so the canonical
// link and the Open Graph image URL are absolute. Vite substitutes %VITE_*% only for variables
// that exist, so an unset variable would ship the placeholder text itself; this plugin runs
// first and, when no origin is known, drops every tag that needs one instead.
function siteUrl(origin: string | undefined): Plugin {
  const url = origin?.trim().replace(/\/+$/, "");
  return {
    name: "site-url",
    transformIndexHtml: {
      order: "pre",
      handler(html) {
        if (url) return html.replaceAll(PLACEHOLDER, url);
        return html.replace(/^[ \t]*<(?:link|meta)\b(?:[^>]*%VITE_SITE_URL%|[^>]*property="og:image:)[^>]*>\r?\n/gm, "");
      },
    },
  };
}

export default defineConfig(({ mode }) => {
  const env = { ...loadEnv(mode, process.cwd(), "VITE_"), ...process.env };
  return {
    plugins: [siteUrl(env.VITE_SITE_URL), react()],
    build: { sourcemap: false, target: "es2022" },
    test: {
      environment: "jsdom",
      setupFiles: ["./src/test/setup.ts"],
      css: false,
    },
  };
});
