import { expect, test } from "vitest";
import page from "../index.html?raw";

const sources = import.meta.glob<string>("../src/**/*.{ts,tsx}", {
	query: "?raw",
	import: "default",
	eager: true,
});

test("the page shell has a no-JavaScript message and nothing inline that the CSP would block", () => {
	const html = new DOMParser().parseFromString(page, "text/html");
	expect(html.documentElement.lang).toBe("en");
	expect(html.querySelector("noscript")?.textContent).toMatch(
		/needs JavaScript/,
	);
	const scripts = [...html.querySelectorAll("script")];
	expect(
		scripts.map((script) => [script.type, script.getAttribute("src")]),
	).toEqual([["module", "/src/main.tsx"]]);
	expect(scripts.every((script) => !script.textContent?.trim())).toBe(true);
	expect(html.querySelectorAll("style, [style]")).toHaveLength(0);
});

test("no source file writes HTML from strings (rule 7)", () => {
	expect(Object.keys(sources).length).toBeGreaterThan(10);
	for (const [path, source] of Object.entries(sources)) {
		expect(source, path).not.toMatch(
			/dangerouslySetInnerHTML|innerHTML|outerHTML|insertAdjacentHTML/,
		);
	}
});
