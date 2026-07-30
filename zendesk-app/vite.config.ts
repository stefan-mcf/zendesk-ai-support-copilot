import { resolve } from "node:path";

import { defineConfig } from "vite";

export default defineConfig({
  base: "./",
  plugins: [
    {
      name: "zendesk-relative-assets",
      enforce: "post",
      generateBundle(_options, bundle) {
        const iframe = bundle["assets/iframe.html"];
        if (iframe?.type === "asset" && typeof iframe.source === "string") {
          iframe.source = iframe.source.replaceAll("../assets/", "./");
        }
      },
    },
  ],
  root: "src",
  publicDir: resolve(__dirname, "public"),
  build: {
    outDir: resolve(__dirname, "dist"),
    emptyOutDir: true,
    rollupOptions: {
      input: resolve(__dirname, "src/assets/iframe.html"),
    },
  },
  test: {
    environment: "jsdom",
  },
});
