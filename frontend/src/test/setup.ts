import "@testing-library/jest-dom/vitest";
import { cleanup } from "@testing-library/react";
import { afterEach } from "vitest";

Object.defineProperty(globalThis, "NodeFilter", {
  configurable: true,
  value: window.NodeFilter,
});

afterEach(async () => {
  cleanup();
  await Promise.resolve();
});
