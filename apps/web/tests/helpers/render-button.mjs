import { readFileSync } from "node:fs";
import { transformSync } from "esbuild";
import { createElement, forwardRef } from "react";

// Compile the real component for SSR without a DOM or a CSS loader.
const source = readFileSync(new URL("../../src/ui/system/Button.jsx", import.meta.url), "utf8")
  .replace(/^import .*;\r?$/gm, "").replaceAll("export const ", "const ");
const { code } = transformSync(source, { loader: "jsx", jsxFactory: "createElement", jsxFragment: "Fragment" });
const components = new Function("createElement", "forwardRef", "Fragment", `${code}; return {Button, IconButton};`)(createElement, forwardRef, Symbol.for("react.fragment"));
export const { Button, IconButton } = components;
