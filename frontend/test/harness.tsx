import { render, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, vi } from "vitest";
import { App } from "../src/App";

// The same fixtures as the Go reader's stories.test.mjs.
export const id = (number: number): string =>
	`00000000-0000-4000-8000-${number.toString(16).padStart(12, "0")}`;

export const identifiers = (length: number, start = 1): string[] =>
	Array.from({ length }, (_, index) => id(start + index));

export function article(
	number: number,
	overrides: Record<string, unknown> = {},
) {
	return {
		id: id(number),
		title: `Archived story ${number}`,
		source_name: "Test source",
		url: "https://example.invalid/article",
		text: "Stored article text.",
		text_kind: "Stored summary",
		input_kind: "summary",
		published_at: "2024-03-01T23:30:00Z",
		collected_at: "2024-03-02T00:30:00Z",
		date_kind: "Stored publication date",
		group: "0",
		score: 0.5,
		...overrides,
	};
}

export function selection(
	items: unknown[],
	overrides: Record<string, unknown> = {},
) {
	return {
		snapshot_id: "snapshot-a",
		method: "neural",
		items,
		exhausted: true,
		unavailable_ids: [],
		ignored_viewed_ids: 0,
		...overrides,
	};
}

export const META = {
	snapshot_id: "snapshot-a",
	articles: 5000,
	methods: ["neural", "tfidf", "svd"],
	topics: [],
};

export const PROFILE_KEY = "afterline:profile:snapshot-a";

export interface FakeResponse {
	ok: boolean;
	status: number;
	json: () => Promise<unknown>;
}

export function response(value: unknown, status = 200): FakeResponse {
	return {
		ok: status >= 200 && status < 300,
		status,
		json: async () => value,
	};
}

export interface Call {
	path: string;
	init: RequestInit;
	body: Record<string, unknown> | null;
}

type Handler = (
	call: Call,
) => FakeResponse | Promise<FakeResponse> | Promise<never>;

// A stand-in for the Python server. Every request must be answered by a handler.
export class FakeServer {
	calls: Call[] = [];
	session: unknown = {
		auth_enabled: false,
		signed_in: false,
		reader: null,
		login_url: "/auth/google/login",
	};
	sessionAnswer: Handler = () => response(this.session);
	meta: Handler = () => response(META);
	recommend: Handler = () => response(selection([]));
	logout: Handler = () => response(null, 204);

	constructor() {
		vi.stubGlobal(
			"fetch",
			vi.fn((path: string, init: RequestInit = {}) => {
				const body =
					typeof init.body === "string"
						? (JSON.parse(init.body) as Record<string, unknown>)
						: null;
				const call = { path, init, body };
				this.calls.push(call);
				if (path === "/api/v1/session") return this.sessionAnswer(call);
				if (path === "/api/v1/recommendations/meta") return this.meta(call);
				if (path === "/api/v1/recommendations") return this.recommend(call);
				if (path === "/auth/logout") return this.logout(call);
				return Promise.reject(new Error(`Unexpected request to ${path}`));
			}),
		);
	}

	// Feed requests carry no seed; related reading always does.
	feedCalls(): Call[] {
		return this.calls.filter(
			(call) =>
				call.path === "/api/v1/recommendations" &&
				call.body &&
				!("seed_id" in call.body),
		);
	}

	lastBody(): Record<string, unknown> {
		const body = this.calls.at(-1)?.body;
		if (!body) throw new Error("The last request had no body.");
		return body;
	}

	// Answers every recommendation request with one selection.
	serve(value: unknown, status = 200): void {
		this.recommend = () => response(value, status);
	}
}

export const $ = <T extends HTMLElement = HTMLElement>(
	elementId: string,
): T => {
	const element = document.getElementById(elementId);
	if (!element) throw new Error(`#${elementId} is not on the page.`);
	return element as T;
};

export function tileTitles(gridId = "story-grid"): string[] {
	return [...$(gridId).querySelectorAll(".tile-open")].map(
		(button) => button.textContent ?? "",
	);
}

export function openButton(
	index: number,
	gridId = "story-grid",
): HTMLButtonElement {
	const button =
		$(gridId).querySelectorAll<HTMLButtonElement>(".tile-open")[index];
	if (!button) throw new Error(`No story tile at ${index}.`);
	return button;
}

export function storedProfile(): Record<string, unknown> {
	return JSON.parse(localStorage.getItem(PROFILE_KEY) ?? "null") as Record<
		string,
		unknown
	>;
}

export async function settled(): Promise<void> {
	await waitFor(() =>
		expect($("reader-panel").getAttribute("aria-busy")).toBe("false"),
	);
}

// Renders the whole app and waits until the first stories have loaded.
export async function renderReader() {
	const user = userEvent.setup();
	const view = render(<App />);
	await settled();
	return { user, ...view };
}

// Records history calls without letting jsdom navigate, as the Go reader's tests did.
export function recordHistory(): string[] {
	const history: string[] = [];
	vi.spyOn(window.history, "pushState").mockImplementation(() => {
		history.push("push");
	});
	vi.spyOn(window.history, "back").mockImplementation(() => {
		history.push("back");
	});
	return history;
}
