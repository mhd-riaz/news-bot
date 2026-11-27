import { defineConfig } from "vitest/config";
import { mockApi } from "./mock/api.ts";

// The Python server serves the built app and its API from one origin. In
// development Vite forwards these paths to it, so the browser still sees one
// origin and the server's same-origin checks pass.
const server = "http://127.0.0.1:8090";
const proxy = Object.fromEntries(
	["/api", "/auth", "/health"].map((path) => [path, server]),
);

// A strict policy (CSP) with no inline scripts or styles, as the server sends.
// `npm run preview` uses it to prove the production build runs under it.
const contentSecurityPolicy = "default-src 'self'; img-src 'self' https: data:";

export default defineConfig(({ mode }) => ({
	// `--mode mock` answers the API with made-up stories instead of the server.
	plugins: mode === "mock" ? [mockApi()] : [],
	server: { port: 5173, strictPort: true, proxy },
	preview: {
		port: 4173,
		strictPort: true,
		proxy,
		headers: { "Content-Security-Policy": contentSecurityPolicy },
	},
	build: { outDir: "dist", emptyOutDir: true },
	test: {
		environment: "jsdom",
		include: ["test/**/*.test.{ts,tsx}"],
		setupFiles: ["./test/setup.ts"],
		restoreMocks: true,
		unstubGlobals: true,
	},
}));
