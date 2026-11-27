import { afterEach, describe, expect, test, vi } from "vitest";
import { requestJSON } from "../src/api";
import { SETTINGS_KEY } from "../src/reader/constants";
import { storyDateLabel } from "../src/reader/format";
import {
	emptyProfile,
	normaliseArticle,
	normaliseMetadata,
} from "../src/reader/normalise";
import { ReaderStore } from "../src/reader/store";
import type { Article } from "../src/reader/types";
import {
	article,
	type FakeResponse,
	FakeServer,
	id,
	identifiers,
	META,
	PROFILE_KEY,
	response,
	selection,
} from "./harness";

// A store with archive information already loaded, as the Go reader's test harness had.
function loadedStore(): ReaderStore {
	const store = new ReaderStore();
	Object.assign(store.state, {
		meta: normaliseMetadata(META),
		profile: emptyProfile(),
		storageKey: PROFILE_KEY,
		method: "neural",
		loading: false,
		feedback: null,
	});
	return store;
}

function story(
	number: number,
	overrides: Record<string, unknown> = {},
): Article {
	const item = normaliseArticle(article(number, overrides));
	if (!item) throw new Error("The fixture must be a valid article.");
	return item;
}

afterEach(() => {
	vi.useRealTimers();
});

describe("browser storage", () => {
	test("storage reads only the active snapshot and recovers visibly from corrupt JSON", () => {
		const store = loadedStore();
		store.state.profile = { ...store.state.profile, liked: [id(1)] };
		store.saveProfile();
		const snapshotA = store.state.storageKey;
		store.state.storageKey = "afterline:profile:snapshot-b";
		expect(store.readProfile().liked).toHaveLength(0);
		store.state.profile = { ...emptyProfile(), disliked: [id(2)] };
		store.saveProfile();
		store.state.storageKey = snapshotA;
		expect(store.readProfile().liked).toEqual([id(1)]);
		expect(store.readProfile().disliked).toHaveLength(0);
		expect(localStorage).toHaveLength(2);
		localStorage.setItem(snapshotA, "{invalid-json");
		expect(store.readProfile().liked).toHaveLength(0);
		expect(store.state.storageWarning).toMatch(/could not be read/);
	});

	test("blocked storage reads and quota failures report session-only persistence", () => {
		for (const failure of ["getter", "getItem", "setItem"] as const) {
			const store = loadedStore();
			const spy =
				failure === "getter"
					? vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
							throw new Error("Storage blocked");
						})
					: vi.spyOn(Storage.prototype, failure).mockImplementation(() => {
							throw new Error("Storage unavailable");
						});
			if (failure === "setItem") {
				store.saveProfile();
				expect(store.state.storageWarning).toMatch(
					/Older saved choices may return/,
				);
			} else {
				expect(store.readProfile().viewed).toHaveLength(0);
			}
			expect(store.state.persistence).toBe(false);
			expect(store.state.storageWarning).toMatch(/only in this open tab/);
			expect(() => store.saveProfile()).not.toThrow();
			spy.mockRestore();
		}
	});

	test("settings accept only the known themes and survive broken JSON", () => {
		const store = loadedStore();
		localStorage.setItem(
			SETTINGS_KEY,
			JSON.stringify({ professional: true, theme: "neon" }),
		);
		expect(store.readSettings()).toEqual({ professional: true, theme: "" });
		localStorage.setItem(SETTINGS_KEY, "{broken");
		expect(store.readSettings()).toEqual({ professional: false, theme: "" });
		localStorage.setItem(SETTINGS_KEY, JSON.stringify({ theme: "dark" }));
		expect(store.readSettings()).toEqual({
			professional: false,
			theme: "dark",
		});
	});
});

describe("requests", () => {
	test("request bodies cap profiles and use same-origin JSON with the selected seed, topic, and lens", async () => {
		const store = loadedStore();
		store.state.profile = {
			liked: identifiers(70),
			disliked: identifiers(70, 100),
			viewed: identifiers(2050),
			onboarded: false,
		};
		store.state.seed = id(4);
		store.state.topic = "0";
		store.state.method = "svd";
		const body = store.bodyFor();
		expect([
			body.liked.length,
			body.disliked.length,
			body.viewed.length,
		]).toEqual([50, 50, 2000]);
		expect(body).toMatchObject({
			limit: 25,
			method: "svd",
			seed_id: id(4),
			topic: "0",
		});
		const explore = store.bodyFor(true);
		expect([
			explore.liked.length,
			explore.disliked.length,
			explore.viewed.length,
		]).toEqual([0, 50, 2000]);
		expect("seed_id" in explore || "topic" in explore).toBe(false);

		vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
		const server = new FakeServer();
		server.meta = () => response({});
		server.recommend = () => response({});
		await requestJSON("/api/v1/recommendations/meta", new AbortController());
		await requestJSON("/api/v1/recommendations", new AbortController(), body);
		const [meta, post] = server.calls;
		expect(meta?.init.method).toBe("GET");
		expect(post?.path).toBe("/api/v1/recommendations");
		expect(post?.init).toMatchObject({
			method: "POST",
			headers: { "Content-Type": "application/json" },
			credentials: "same-origin",
			cache: "no-store",
		});
		expect(post?.body).toEqual(JSON.parse(JSON.stringify(body)));
		expect(vi.getTimerCount()).toBe(0);
	});

	test("views send their news window, related reading spans every window, and focus sends professional tags", () => {
		const store = loadedStore();
		const meta = store.state.meta;
		if (!meta) throw new Error("The harness loads metadata.");
		store.state.meta = {
			...meta,
			domains: { ai: 3, "data-science": 1, "Not A Tag": 1 },
		};
		store.state.profile = { ...emptyProfile(), viewed: [id(1)] };
		const fresh = store.bodyFor();
		expect([fresh.window, fresh.limit, "domains" in fresh]).toEqual([
			"fresh",
			25,
			false,
		]);
		store.state.professional = true;
		expect(store.bodyFor().domains).toEqual(["ai", "data-science"]);
		store.state.seed = id(4);
		const related = store.bodyFor();
		expect("window" in related).toBe(false);
		expect(related.seed_id).toBe(id(4));
		store.state.seed = "";
		store.state.view = "yesterday";
		const edition = store.bodyFor();
		expect([edition.window, edition.limit, edition.viewed.length]).toEqual([
			"yesterday",
			10,
			0,
		]);
		const explore = store.bodyFor(true);
		expect([explore.window, explore.limit]).toEqual(["yesterday", 24]);
	});

	test("related reading asks for six stories around the open one", () => {
		const store = loadedStore();
		const meta = store.state.meta;
		if (!meta) throw new Error("The harness loads metadata.");
		store.state.meta = { ...meta, domains: { ai: 3 } };
		store.state.professional = true;
		store.state.profile = { ...emptyProfile(), viewed: [id(1)] };
		expect(store.relatedBody(story(1))).toEqual({
			liked: [],
			disliked: [],
			viewed: [id(1)],
			method: "neural",
			limit: 6,
			seed_id: id(1),
			domains: ["ai"],
		});
	});

	test("cancelled requests cannot replace current content, clear a newer loading state, or mark stale items viewed", async () => {
		vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
		for (const staleFirst of [true, false]) {
			const store = loadedStore();
			const server = new FakeServer();
			const pending: {
				resolve: (value: FakeResponse) => void;
				reject: (reason: unknown) => void;
				signal: AbortSignal | null | undefined;
			}[] = [];
			server.recommend = (call) =>
				new Promise((resolve, reject) => {
					pending.push({ resolve, reject, signal: call.init.signal });
				});
			const older = store.loadFeed(true);
			const newer = store.loadFeed(true);
			const [first, second] = pending;
			if (!first || !second) throw new Error("Both requests must be sent.");
			expect(first.signal?.aborted).toBe(true);
			expect(store.state.loading).toBe(true);
			if (staleFirst) {
				first.resolve(response(selection([article(11)])));
				await older;
				expect(store.state.loading).toBe(true);
				expect(store.state.items).toHaveLength(0);
				expect(store.state.profile.viewed).toHaveLength(0);
			}
			second.resolve(response(selection([article(22), article(23)])));
			await newer;
			if (!staleFirst) {
				first.reject(
					new Error("Old request failed after the new one finished."),
				);
				await older;
			}
			expect(store.state.items.map((item) => item.id)).toEqual([
				id(22),
				id(23),
			]);
			expect(store.state.profile.viewed).toHaveLength(0);
			expect(store.state.feedback).toBe(null);
			expect(store.state.loading).toBe(false);
			expect(vi.getTimerCount()).toBe(0);
		}
	});

	test("timeouts abort the request, clear busy state and timers, and leave retry available", async () => {
		vi.useFakeTimers({ toFake: ["setTimeout", "clearTimeout"] });
		const store = loadedStore();
		const server = new FakeServer();
		server.recommend = (call) =>
			new Promise((_resolve, reject) => {
				call.init.signal?.addEventListener(
					"abort",
					() => reject(new Error("Aborted")),
					{
						once: true,
					},
				);
			});
		const pending = store.loadFeed(true);
		expect(store.state.loading).toBe(true);
		expect(vi.getTimerCount()).toBe(1);
		vi.advanceTimersByTime(24_999);
		expect(server.calls[0]?.init.signal?.aborted).toBe(false);
		vi.advanceTimersByTime(1);
		await pending;
		expect(server.calls[0]?.init.signal?.aborted).toBe(true);
		expect(store.state.loading).toBe(false);
		expect(store.state.feedback?.kind).toBe("error");
		expect(store.state.feedback?.message).toMatch(/took too long/);
		expect(store.state.retryKind).toBe("feed");
		expect(store.state.profile.viewed).toHaveLength(0);
		expect(vi.getTimerCount()).toBe(0);
	});
});

describe("history", () => {
	test("opening a story keeps only the newest 2,000 opened stories", () => {
		new FakeServer().serve(selection([]));
		vi.spyOn(window.history, "pushState").mockImplementation(() => {});
		const store = loadedStore();
		store.state.items = [story(1)];
		store.state.profile = { ...emptyProfile(), viewed: identifiers(2000) };
		store.openStory("feed", 0);
		expect(store.state.profile.viewed).toHaveLength(2000);
		expect(store.state.profile.viewed[0]).toBe(id(2));
		expect(store.state.profile.viewed.at(-1)).toBe(id(1));
	});
});

describe("dates", () => {
	test("story dates use the edition time zone and keep it when a zone is unknown", () => {
		const store = loadedStore();
		store.setTimeZone("Asia/Kolkata");
		expect(
			storyDateLabel(story(1, { date_verified: false }), store.formats),
		).toBe("Published 2 March 2024 · date unverified");
		expect(
			storyDateLabel(story(2, { date_verified: true }), store.formats),
		).toBe("Published 2 March 2024");
		store.setTimeZone("Not/AZone");
		expect(store.formats.timeZone).toBe("Asia/Kolkata");
		expect(storyDateLabel(story(3), store.formats)).toBe(
			"Published 2 March 2024",
		);
		store.setTimeZone("UTC");
		expect(storyDateLabel(story(4), store.formats)).toBe(
			"Published 1 March 2024",
		);
	});
});
