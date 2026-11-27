import {
	act,
	fireEvent,
	render,
	waitFor,
	within,
} from "@testing-library/react";
import { describe, expect, test, vi } from "vitest";
import { App } from "../src/App";
import { SAVED_KEY, SETTINGS_KEY } from "../src/reader/constants";
import {
	$,
	article,
	FakeServer,
	id,
	identifiers,
	META,
	openButton,
	PROFILE_KEY,
	recordHistory,
	renderReader,
	response,
	selection,
	settled,
	storedProfile,
	tileTitles,
} from "./harness";

const dialog = (name: string) => $<HTMLDialogElement>(name);
const button = (name: string) => $<HTMLButtonElement>(name);
const savedItems = () =>
	JSON.parse(localStorage.getItem(SAVED_KEY) ?? "[]") as {
		id: string;
		note: string;
	}[];

function stubColourScheme(dark: boolean) {
	const listeners = new Set<() => void>();
	const query = {
		matches: dark,
		media: "(prefers-color-scheme: dark)",
		addEventListener: (_type: string, listener: () => void) =>
			listeners.add(listener),
		removeEventListener: (_type: string, listener: () => void) =>
			listeners.delete(listener),
	};
	vi.stubGlobal(
		"matchMedia",
		vi.fn((media: string) =>
			media.includes("prefers-color-scheme")
				? query
				: {
						matches: false,
						media,
						addEventListener() {},
						removeEventListener() {},
					},
		),
	);
	return {
		set(value: boolean) {
			query.matches = value;
			for (const listener of listeners) listener();
		},
	};
}

describe("loading and errors", () => {
	test("initial loading renders before the server chooses a default lens", async () => {
		const server = new FakeServer();
		server.meta = (call) =>
			new Promise((_resolve, reject) => {
				call.init.signal?.addEventListener("abort", () =>
					reject(new DOMException("Aborted", "AbortError")),
				);
			});
		render(<App />);
		await waitFor(() => expect($("lens-note").textContent).toMatch(/Loading/));
		expect(button("method").disabled).toBe(true);
		expect($("reader-panel").getAttribute("aria-busy")).toBe("true");
		expect($("feedback-title").textContent).toBe("Opening the stories.");
		expect(button("view-fresh").disabled).toBe(true);
	});

	test("service errors, invalid JSON, and connection failures show retryable errors and recover", async () => {
		const failures: [FakeServer["recommend"], RegExp][] = [
			[
				() =>
					response(
						{
							error: {
								code: "unavailable",
								message: "Recommendation service is not ready.",
							},
						},
						503,
					),
				/not ready/,
			],
			[() => response({}, 503), /unavailable/],
			[
				() => ({
					ok: true,
					status: 200,
					json: async () => {
						throw new SyntaxError("Bad JSON");
					},
				}),
				/readable JSON/,
			],
			[
				() => Promise.reject(new TypeError("Failed to fetch")),
				/Check your connection/,
			],
		];
		for (const [failure, expected] of failures) {
			const server = new FakeServer();
			server.recommend = failure;
			const { user, unmount } = await renderReader();
			expect($("feed-feedback").hidden).toBe(false);
			expect($("feedback-kicker").textContent).toBe("An honest pause");
			expect($("feedback-message").textContent).toMatch(expected);
			expect($("retry-feed").hidden).toBe(false);
			expect($("retry-feed").textContent).toBe("Try again");
			expect($("reader-panel").getAttribute("aria-busy")).toBe("false");
			expect(storedProfile()).toBe(null);
			server.serve(selection([article(1)]));
			await user.click($("retry-feed"));
			await waitFor(() => expect(tileTitles()).toEqual(["Archived story 1"]));
			expect($("feed-feedback").hidden).toBe(true);
			expect($("retry-feed").hidden).toBe(true);
			unmount();
		}
	});

	test("a changed snapshot requires metadata reload without applying new items to the old profile", async () => {
		const server = new FakeServer();
		server.serve(selection([article(1)], { exhausted: false }));
		const { user } = await renderReader();
		server.serve(selection([article(22)], { snapshot_id: "snapshot-b" }));
		await user.click($("load-more"));
		await settled();
		expect($("feed-feedback").hidden).toBe(false);
		expect($("retry-feed").textContent).toBe("Reload archive");
		expect($("feedback-message").textContent).toMatch(/snapshot changed/);
		expect(tileTitles()).toEqual(["Archived story 1"]);
		expect(storedProfile()).toBe(null);
		server.meta = () => response({ ...META, snapshot_id: "snapshot-b" });
		await user.click($("retry-feed"));
		await waitFor(() => expect(tileTitles()).toEqual(["Archived story 22"]));
		expect($("snapshot-label").textContent).toBe("Snapshot snapshot-b");
	});

	test("an unreadable saved profile is reported on the page", async () => {
		localStorage.setItem(PROFILE_KEY, "{invalid-json");
		new FakeServer().serve(selection([article(1)]));
		await renderReader();
		expect($("storage-warning").hidden).toBe(false);
		expect($("storage-warning").textContent).toMatch(/could not be read/);
	});
});

describe("the grid and the reading view", () => {
	test("the grid shows a page without marking it viewed; opening, Next and More behave like a reader", async () => {
		const server = new FakeServer();
		server.serve(
			selection([article(1), article(2), article(3)], { exhausted: false }),
		);
		const { user } = await renderReader();
		expect(tileTitles()).toEqual([
			"Archived story 1",
			"Archived story 2",
			"Archived story 3",
		]);
		const tiles = $("story-grid").querySelectorAll("article");
		expect([tiles[0]?.className, tiles[1]?.className]).toEqual([
			"tile tile-lead",
			"tile",
		]);
		expect($("story-grid").hidden).toBe(false);
		expect($("load-more").hidden).toBe(false);
		expect(storedProfile()).toBe(null);
		await user.click(openButton(1));
		expect(dialog("story-dialog").open).toBe(true);
		expect($("story-title").textContent).toBe("Archived story 2");
		expect(storedProfile().viewed).toEqual([id(2)]);
		expect([
			$("position-current").textContent,
			$("position-total").textContent,
		]).toEqual(["2", "3+"]);
		await user.click($("previous-story"));
		expect($("story-title").textContent).toBe("Archived story 1");
		expect(button("previous-story").disabled).toBe(true);
		await user.click($("next-story"));
		await user.click($("next-story"));
		expect($("story-title").textContent).toBe("Archived story 3");
		expect(storedProfile()).toMatchObject({ liked: [], disliked: [] });
		expect(server.feedCalls()).toHaveLength(1);
		server.serve(selection([article(1), article(4)]));
		await user.click($("next-story"));
		await waitFor(() =>
			expect($("story-title").textContent).toBe("Archived story 4"),
		);
		const more = server.feedCalls()[1]?.body;
		expect(more?.limit).toBe(24);
		const viewed = (more?.viewed ?? []) as string[];
		expect([...viewed].sort()).toEqual([id(1), id(2), id(3)]);
		expect(tileTitles()).toEqual([
			"Archived story 1",
			"Archived story 2",
			"Archived story 3",
			"Archived story 4",
		]);
		expect(button("next-story").disabled).toBe(true);
		await user.keyboard("{ArrowRight}");
		expect(server.feedCalls()).toHaveLength(2);
		await user.click($("close-story"));
		expect(dialog("story-dialog").open).toBe(false);
		expect($("feed-end").hidden).toBe(false);
		expect($("load-more").hidden).toBe(true);
	});

	test("story rendering keeps fetched text literal, labels absolute dates, and handles headline-only input", async () => {
		const hostile = "<img src=x onerror=alert(1)>";
		new FakeServer().serve(
			selection([
				article(1, {
					title: hostile,
					text: hostile,
					reason: hostile,
					source_name: hostile,
					url: "javascript:alert(1)",
					image_url: "http://example.invalid/image",
					date_kind: "Collected",
					published_at: "2031-01-01",
					score: Number.POSITIVE_INFINITY,
				}),
				article(2, { text: "", published_at: "invalid", collected_at: "" }),
			]),
		);
		const { user } = await renderReader();
		await user.click(openButton(0));
		for (const name of [
			"story-title",
			"story-text",
			"story-reason",
			"story-source",
		]) {
			expect($(name).textContent).toBe(hostile);
		}
		expect(document.querySelector("img[src='x']")).toBe(null);
		expect($("story-date").textContent).toBe("Collected 2 March 2024");
		expect($("story-date").getAttribute("datetime")).toBe(
			"2024-03-02T00:30:00.000Z",
		);
		expect($("read-original").hidden).toBe(true);
		expect($("read-original").hasAttribute("href")).toBe(false);
		expect($("original-unavailable").hidden).toBe(false);
		expect(document.getElementById("story-image")).toBe(null);
		expect($("story-score").textContent).toBe(
			"Neural content lens. No match score was supplied.",
		);
		await user.click($("next-story"));
		expect($("story-text-kind").textContent).toBe("Headline only");
		expect($("story-text").textContent).toMatch(/Only the headline is stored/);
		expect($("story-date").textContent).toBe("Stored date unavailable");
		expect($("story-date").hasAttribute("datetime")).toBe(false);
		expect($("read-original").getAttribute("href")).toBe(
			"https://example.invalid/article",
		);
		expect($("read-original-label").textContent).toBe(
			"Read the full story at Test source",
		);
		expect($("story-score").textContent).toMatch(
			/^Neural match score: 0\.500\./,
		);
	});

	test("long stored text opens with a lead and the rest behind Continue", async () => {
		const words = Array.from(
			{ length: 200 },
			(_, index) => `word${index}`,
		).join(" ");
		new FakeServer().serve(selection([article(1, { text: words })]));
		const { user } = await renderReader();
		await user.click(openButton(0));
		const lead = $("story-text").textContent ?? "";
		expect(lead.length).toBeLessThanOrEqual(650);
		expect(`${lead} ${$("remaining-text").textContent}`).toBe(words);
		expect($("more-text").hidden).toBe(false);
	});

	test("tiles keep fetched text literal, skip insecure images, and badge freshness only in related reading", async () => {
		const hostile = "<img src=x onerror=alert(1)>";
		const server = new FakeServer();
		server.serve(
			selection([
				article(1, {
					title: hostile,
					source_name: hostile,
					text: hostile,
					image_url: "http://example.invalid/image.jpg",
				}),
				article(2, {
					text: "",
					image_url: "https://example.invalid/image.jpg",
					fresh: true,
				}),
			]),
		);
		const { user } = await renderReader();
		const [lead, second] = $("story-grid").querySelectorAll("article");
		if (!lead || !second) throw new Error("Two tiles must render.");
		const media = lead.querySelector(".tile-media");
		expect(media?.children).toHaveLength(1);
		expect(media?.children[0]?.className).toBe("tile-placeholder");
		expect(lead.querySelector(".tile-source")?.textContent).toBe(hostile);
		expect(lead.querySelector(".tile-open")?.textContent).toBe(hostile);
		expect(lead.querySelector(".tile-summary")?.textContent).toBe(hostile);
		expect(document.querySelector("img[src='x']")).toBe(null);
		const save = lead.querySelector<HTMLButtonElement>(".tile-save");
		expect(save?.dataset.save).toBe(id(1));
		expect(save?.getAttribute("aria-label")).toBe(`Save: ${hostile}`);
		const image = second.querySelector(".tile-media img");
		expect([
			image?.getAttribute("src"),
			image?.getAttribute("referrerpolicy"),
			image?.getAttribute("loading"),
			image?.getAttribute("alt"),
		]).toEqual([
			"https://example.invalid/image.jpg",
			"no-referrer",
			"lazy",
			"",
		]);
		expect(second.querySelector(".tile-summary")).toBe(null);
		expect($("story-grid").querySelectorAll(".tile-badge")).toHaveLength(0);
		await user.click(openButton(0));
		server.serve(selection([article(30), article(31, { fresh: true })]));
		await user.click($("related-story"));
		await waitFor(() =>
			expect(tileTitles()).toEqual(["Archived story 30", "Archived story 31"]),
		);
		const badges = [...$("story-grid").querySelectorAll(".tile-badge")].map(
			(badge) => [badge.className, badge.textContent],
		);
		expect(badges).toEqual([
			["tile-badge", "From the archive"],
			["tile-badge is-fresh", "Fresh"],
		]);
	});

	test("story dates show the edition time zone, label unverified dates, and mark fresh stories", async () => {
		const server = new FakeServer();
		server.meta = () => response({ ...META, edition_timezone: "Asia/Kolkata" });
		server.serve(
			selection([
				article(1, { date_verified: false }),
				article(2, { date_verified: true, fresh: true }),
			]),
		);
		const { user } = await renderReader();
		expect($("date-note").textContent).toMatch(/shown in India time\./);
		await user.click(openButton(0));
		expect($("story-date").textContent).toBe(
			"Published 2 March 2024 · date unverified",
		);
		expect($("story-stamp").textContent).toBe("From the archive");
		await user.click($("next-story"));
		expect($("story-date").textContent).toBe("Published 2 March 2024");
		expect($("story-stamp").textContent).toBe("Fresh · last 30 days");
		expect($("story-stamp").className).toBe("stamp is-fresh");
	});

	test("related reading asks for six stories around the open one and keeps its own trail", async () => {
		localStorage.setItem(SETTINGS_KEY, JSON.stringify({ professional: true }));
		const server = new FakeServer();
		server.meta = () => response({ ...META, domains: { ai: 3 } });
		server.recommend = (call) =>
			response(
				call.body?.seed_id
					? selection([article(1), article(30, { fresh: true }), article(31)])
					: selection([article(1), article(2)], { exhausted: false }),
			);
		const history = recordHistory();
		const { user } = await renderReader();
		expect(server.lastBody().domains).toEqual(["ai"]);
		await user.click(openButton(0));
		await waitFor(() =>
			expect(tileTitles("related-grid")).toEqual([
				"Archived story 30",
				"Archived story 31",
			]),
		);
		const related = server.lastBody();
		expect([
			related.seed_id,
			related.limit,
			related.window,
			related.domains,
			related.viewed,
		]).toEqual([id(1), 6, undefined, ["ai"], [id(1)]]);
		expect($("related-grid").querySelector(".tile-badge")?.textContent).toBe(
			"Fresh",
		);
		expect($("related-grid").querySelector("h4.tile-title")).not.toBe(null);
		await user.click(openButton(1, "related-grid"));
		expect($("story-title").textContent).toBe("Archived story 31");
		expect([
			$("position-current").textContent,
			$("position-total").textContent,
		]).toEqual(["2", "2"]);
		expect(button("next-story").disabled).toBe(true);
		await user.click($("previous-story"));
		expect($("story-title").textContent).toBe("Archived story 30");
		expect(server.feedCalls()).toHaveLength(1);
		expect(history).toEqual(["push"]);
		server.serve(selection([article(40), article(41)]));
		await user.click($("related-story"));
		expect(dialog("story-dialog").open).toBe(false);
		expect(history).toEqual(["push", "back"]);
		await settled();
		const seeded = server.lastBody();
		expect([seeded.seed_id, seeded.limit, seeded.window]).toEqual([
			id(30),
			25,
			undefined,
		]);
		expect($("selection-label").textContent).toBe("Related reading");
		expect($("selection-note").textContent).toBe(
			"Related to “Archived story 30”",
		);
		expect(tileTitles()).toEqual(["Archived story 40", "Archived story 41"]);
		expect(button("view-fresh").getAttribute("aria-pressed")).toBe("false");
	});
});

describe("choices", () => {
	test("preferences toggle opposing choices, cap each side, offer an update, and drop dislikes on close", async () => {
		localStorage.setItem(
			PROFILE_KEY,
			JSON.stringify({
				liked: identifiers(50, 100),
				disliked: identifiers(50, 200),
				viewed: [],
				onboarded: true,
			}),
		);
		const server = new FakeServer();
		server.serve(selection([article(1), article(2)]));
		const { user } = await renderReader();
		await user.click(openButton(0));
		await user.click($("like-story"));
		let profile = storedProfile();
		expect(profile.liked).toHaveLength(50);
		expect(profile.liked).not.toContain(id(100));
		expect(profile.liked).toContain(id(1));
		expect($("refresh-feed").hidden).toBe(false);
		expect($("like-story").getAttribute("aria-pressed")).toBe("true");
		expect($("reader-status").textContent).toBe(
			"Interest added. Back on the stories, “Update for your new choices” re-ranks them.",
		);
		await user.click($("dislike-story"));
		profile = storedProfile();
		expect(profile.liked).not.toContain(id(1));
		expect(profile.disliked).toContain(id(1));
		expect(profile.disliked).toHaveLength(50);
		expect(profile.disliked).not.toContain(id(200));
		expect($("dislike-story").getAttribute("aria-pressed")).toBe("true");
		expect($("reader-status").textContent).toBe(
			"Marked not interested. It leaves the page when you close this story.",
		);
		await user.click($("dislike-story"));
		expect(storedProfile().disliked).not.toContain(id(1));
		await user.click($("dislike-story"));
		expect(server.feedCalls()).toHaveLength(1);
		expect(tileTitles()).toEqual(["Archived story 1", "Archived story 2"]);
		await user.click($("close-story"));
		expect(tileTitles()).toEqual(["Archived story 2"]);
		expect($("refresh-feed").hidden).toBe(false);
		await user.click($("refresh-feed"));
		await settled();
		expect(server.feedCalls()).toHaveLength(2);
		expect($("action-status").textContent).toBe(
			"Updating the stories for your choices.",
		);
	});

	test("filtered-empty batches exclude viewed/disliked IDs and pause without a refetch loop", async () => {
		localStorage.setItem(
			PROFILE_KEY,
			JSON.stringify({
				liked: [],
				disliked: [id(2)],
				viewed: [id(1)],
				onboarded: false,
			}),
		);
		const server = new FakeServer();
		server.serve(selection([article(1), article(2)], { exhausted: false }));
		await renderReader();
		const body = server.feedCalls()[0]?.body;
		expect(body?.viewed).toEqual([id(1)]);
		expect(body?.disliked).toEqual([id(2)]);
		expect($("feed-feedback").hidden).toBe(false);
		expect($("feedback-title").textContent).toBe("Nothing fresh here yet.");
		expect($("loading-indicator").hidden).toBe(true);
		expect($("story-grid").hidden).toBe(true);
		expect($("load-more").hidden).toBe(true);
		expect($("feedback-explore").hidden).toBe(false);
		expect(storedProfile().viewed).toEqual([id(1)]);
		expect(server.feedCalls()).toHaveLength(1);
	});

	test("an edition is one fixed page: opened stories stay in it and the reader never refetches", async () => {
		localStorage.setItem(
			PROFILE_KEY,
			JSON.stringify({
				liked: [],
				disliked: [],
				viewed: [id(1)],
				onboarded: true,
			}),
		);
		const server = new FakeServer();
		server.meta = () => response({ ...META, edition_date: "2026-11-22" });
		const stories = Array.from({ length: 10 }, (_, index) =>
			article(index + 1),
		);
		server.recommend = (call) =>
			response(
				call.body?.window === "yesterday"
					? selection(stories, {
							exhausted: false,
							window: "yesterday",
							edition_date: "2026-11-23",
						})
					: selection([article(50)]),
			);
		const { user } = await renderReader();
		await user.click($("view-yesterday"));
		await settled();
		expect(server.lastBody()).toMatchObject({
			window: "yesterday",
			limit: 10,
			viewed: [],
		});
		expect(tileTitles()).toHaveLength(10);
		expect($("selection-label").textContent).toBe("Yesterday’s edition");
		expect($("page-date").textContent).toBe("Monday 23 November");
		expect($("load-more").hidden).toBe(true);
		expect($("feed-end").hidden).toBe(false);
		expect($("end-message").textContent).toMatch(
			/yesterday’s edition: 10 stories published on Monday 23 November/,
		);
		await user.click(openButton(0));
		await user.click($("like-story"));
		expect($("refresh-feed").hidden).toBe(true);
		expect($("reader-status").textContent).toMatch(
			/This edition stays as it is/,
		);
		for (let step = 0; step < 9; step += 1) await user.click($("next-story"));
		expect($("story-title").textContent).toBe("Archived story 10");
		expect(button("next-story").disabled).toBe(true);
		expect($("position-total").textContent).toBe("10");
		expect(server.feedCalls()).toHaveLength(2);
		await user.click($("close-story"));
		expect(tileTitles()).toHaveLength(10);
	});

	test("marking every story not interested leaves an explained page with an update, not a blank one", async () => {
		const server = new FakeServer();
		server.serve(selection([article(1), article(2)], { exhausted: false }));
		const { user } = await renderReader();
		await user.click(openButton(0));
		await user.click($("dislike-story"));
		await user.click($("next-story"));
		await user.click($("dislike-story"));
		await user.click($("close-story"));
		expect($("story-grid").querySelectorAll(".tile")).toHaveLength(0);
		expect($("feed-feedback").hidden).toBe(false);
		expect($("feedback-title").textContent).toBe("Nothing left on this page.");
		expect($("refresh-feed").hidden).toBe(false);
		expect($("feedback-explore").hidden).toBe(false);
		expect(server.feedCalls()).toHaveLength(1);
	});
});

describe("saved stories", () => {
	test("saved stories and notes persist across snapshots, stay literal, and are bounded", async () => {
		const server = new FakeServer();
		server.serve(
			selection([
				article(1, { url: "https://example.invalid/one" }),
				article(2),
			]),
		);
		const { user, unmount } = await renderReader();
		const star = () => {
			const found =
				$("story-grid").querySelectorAll<HTMLButtonElement>(".tile-save")[1];
			if (!found) throw new Error("The second tile has a save button.");
			return found;
		};
		expect(star().dataset.save).toBe(id(2));
		await user.click(star());
		expect(savedItems().map((item) => item.id)).toEqual([id(2)]);
		expect([star().textContent, star().getAttribute("aria-pressed")]).toEqual([
			"★",
			"true",
		]);
		expect($("open-saved").textContent).toBe("Saved stories (1)");
		expect($("action-status").textContent).toBe(
			"Saved in this browser. Open the story to add a note.",
		);
		await user.click(star());
		expect([star().textContent, star().getAttribute("aria-pressed")]).toEqual([
			"☆",
			"false",
		]);
		await user.click(openButton(0));
		await user.click($("save-story"));
		expect($("save-story").getAttribute("aria-pressed")).toBe("true");
		expect([$("save-label").textContent, $("save-icon").textContent]).toEqual([
			"Saved",
			"★",
		]);
		expect($("note-editor").hidden).toBe(false);
		fireEvent.change($("story-note"), {
			target: { value: `<b>why</b> ${"x".repeat(2100)}` },
		});
		await user.click($("save-note"));
		const stored = savedItems();
		expect(stored).toHaveLength(1);
		expect(stored[0]?.note).toHaveLength(2000);
		expect(stored[0]?.note.startsWith("<b>why</b>")).toBe(true);
		expect($("note-status").textContent).toBe("Note saved in this browser.");
		unmount();

		// A later snapshot still shows the story and its note, as text.
		const next = new FakeServer();
		next.meta = () => response({ ...META, snapshot_id: "snapshot-b" });
		next.serve(selection([article(3)], { snapshot_id: "snapshot-b" }));
		const later = await renderReader();
		expect($("open-saved").textContent).toBe("Saved stories (1)");
		await later.user.click($("open-saved"));
		expect(dialog("saved-dialog").open).toBe(true);
		const entry = $("saved-list").querySelector<HTMLElement>(".saved-item");
		if (!entry) throw new Error("The saved story is listed.");
		expect(entry.querySelector("a.saved-title")?.getAttribute("href")).toBe(
			"https://example.invalid/one",
		);
		expect(entry.querySelector("a.saved-title")?.getAttribute("rel")).toBe(
			"noopener noreferrer",
		);
		expect(entry.querySelector(".saved-note")?.textContent).toBe(
			stored[0]?.note,
		);
		expect(entry.querySelector("b")).toBe(null);
		await later.user.click(
			within(entry).getByRole("button", { name: "Remove" }),
		);
		expect(savedItems()).toEqual([]);
		expect($("saved-empty").hidden).toBe(false);
		await later.user.click($("close-saved"));
		expect(dialog("saved-dialog").open).toBe(false);
	});

	test("a typed note survives moving to another story or closing the reader without a save click", async () => {
		new FakeServer().serve(selection([article(1), article(2)]));
		const { user } = await renderReader();
		await user.click(openButton(0));
		await user.click($("save-story"));
		await user.type($("story-note"), "typed before swiping");
		expect(savedItems()[0]?.note).toBe("typed before swiping");
		await user.click($("next-story"));
		expect(savedItems()[0]?.note).toBe("typed before swiping");
		expect($("note-editor").hidden).toBe(true);
		await user.click($("previous-story"));
		expect($<HTMLTextAreaElement>("story-note").value).toBe(
			"typed before swiping",
		);
		await user.clear($("story-note"));
		await user.type($("story-note"), "typed before closing");
		fireEvent(
			dialog("story-dialog"),
			new Event("cancel", { cancelable: true }),
		);
		expect(dialog("story-dialog").open).toBe(false);
		expect(savedItems()[0]?.note).toBe("typed before closing");
	});
});

describe("focus, keyboard and history", () => {
	test("browser Back closes the reader in place, and focus returns to the tile that opened it", async () => {
		new FakeServer().serve(selection([article(1), article(2)]));
		const history = recordHistory();
		const { user } = await renderReader();
		const opener = openButton(1);
		expect(opener.dataset.index).toBe("1");
		await user.click(opener);
		expect(document.activeElement).toBe($("story-title"));
		act(() => {
			window.dispatchEvent(new PopStateEvent("popstate"));
		});
		expect(dialog("story-dialog").open).toBe(false);
		expect(document.activeElement).toBe(opener);
		expect(history).toEqual(["push"]);
		await user.click(openButton(0));
		await user.click($("close-story"));
		expect(history).toEqual(["push", "push", "back"]);
		await user.click(openButton(0));
		act(() => {
			window.dispatchEvent(new PopStateEvent("popstate"));
		});
		expect(dialog("story-dialog").open).toBe(true);
		act(() => {
			window.dispatchEvent(new PopStateEvent("popstate"));
		});
		expect(dialog("story-dialog").open).toBe(false);
	});

	test("after not-interested choices, closing focuses the opener's story or the next story kept after it", async () => {
		new FakeServer().serve(
			selection([article(1), article(2), article(3), article(4)]),
		);
		const { user } = await renderReader();
		await user.click(openButton(1));
		await user.click($("next-story"));
		await user.click($("dislike-story"));
		await user.click($("close-story"));
		expect(tileTitles()).toEqual([
			"Archived story 1",
			"Archived story 2",
			"Archived story 4",
		]);
		expect(document.activeElement).toBe(openButton(1));
		expect(document.activeElement?.textContent).toBe("Archived story 2");
		await user.click(openButton(1));
		await user.click($("dislike-story"));
		await user.click($("close-story"));
		expect(tileTitles()).toEqual(["Archived story 1", "Archived story 4"]);
		expect(document.activeElement?.textContent).toBe("Archived story 4");
	});

	test("arrow keys move between stories, except while typing, and Escape returns to the stories", async () => {
		new FakeServer().serve(selection([article(1), article(2), article(3)]));
		const { user } = await renderReader();
		await user.click(openButton(0));
		await user.keyboard("{ArrowRight}");
		expect($("story-title").textContent).toBe("Archived story 2");
		await user.keyboard("{ArrowLeft}");
		expect($("story-title").textContent).toBe("Archived story 1");
		await user.keyboard("{Shift>}{ArrowRight}{/Shift}");
		expect($("story-title").textContent).toBe("Archived story 1");
		await user.click($("save-story"));
		await user.click($("story-note"));
		await user.keyboard("{ArrowRight}");
		expect($("story-title").textContent).toBe("Archived story 1");
		fireEvent(
			dialog("story-dialog"),
			new Event("cancel", { cancelable: true }),
		);
		expect(dialog("story-dialog").open).toBe(false);
		expect(document.activeElement).toBe(openButton(0));
	});

	test("a touch swipe moves between stories, and a mouse drag does not", async () => {
		new FakeServer().serve(selection([article(1), article(2)]));
		const { user } = await renderReader();
		await user.click(openButton(0));
		const card = $("story-card");
		const swipe = (pointerType: string, from: number, to: number) => {
			fireEvent.pointerDown(card, {
				pointerId: 1,
				pointerType,
				isPrimary: true,
				clientX: from,
				clientY: 100,
			});
			fireEvent.pointerUp(card, {
				pointerId: 1,
				pointerType,
				isPrimary: true,
				clientX: to,
				clientY: 104,
			});
		};
		swipe("mouse", 300, 100);
		expect($("story-title").textContent).toBe("Archived story 1");
		swipe("touch", 300, 100);
		await waitFor(() =>
			expect($("story-title").textContent).toBe("Archived story 2"),
		);
		swipe("touch", 100, 300);
		await waitFor(() =>
			expect($("story-title").textContent).toBe("Archived story 1"),
		);
	});
});

describe("theme", () => {
	test("the theme follows the computer until a reader picks one, and the choice is kept", async () => {
		const scheme = stubColourScheme(true);
		new FakeServer().serve(selection([article(1)]));
		const { user, unmount } = await renderReader();
		expect(document.documentElement.dataset.theme).toBeUndefined();
		expect($("theme-toggle").getAttribute("aria-pressed")).toBe("true");
		act(() => scheme.set(false));
		expect($("theme-toggle").getAttribute("aria-pressed")).toBe("false");
		act(() => scheme.set(true));
		await user.click($("theme-toggle"));
		expect(document.documentElement.dataset.theme).toBe("light");
		expect($("theme-toggle").getAttribute("aria-pressed")).toBe("false");
		expect($("action-status").textContent).toBe(
			"Light theme on. Saved in this browser.",
		);
		expect(JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "null")).toEqual({
			professional: false,
			theme: "light",
		});
		await user.click($("theme-toggle"));
		expect(document.documentElement.dataset.theme).toBe("dark");
		unmount();

		// The saved choice applies on the next visit, even on a light computer.
		scheme.set(false);
		new FakeServer().serve(selection([article(1)]));
		await renderReader();
		expect(document.documentElement.dataset.theme).toBe("dark");
		expect($("theme-toggle").getAttribute("aria-pressed")).toBe("true");
	});
});

describe("what the page sends", () => {
	test("reading, choosing and leaving send no reading reports, only the reader's requests (R6)", async () => {
		const sendBeacon = vi.fn(() => true);
		Object.defineProperty(navigator, "sendBeacon", {
			configurable: true,
			value: sendBeacon,
		});
		try {
			const server = new FakeServer();
			server.serve(selection([article(1), article(2)], { exhausted: false }));
			const { user, unmount } = await renderReader();
			await user.click(openButton(0));
			await user.click($("like-story"));
			await user.click($("next-story"));
			await user.click($("close-story"));
			vi.spyOn(document, "visibilityState", "get").mockReturnValue("hidden");
			act(() => {
				document.dispatchEvent(new Event("visibilitychange"));
				window.dispatchEvent(new Event("pagehide"));
			});
			unmount();
			expect(new Set(server.calls.map((call) => call.path))).toEqual(
				new Set([
					"/api/v1/session",
					"/api/v1/recommendations/meta",
					"/api/v1/recommendations",
				]),
			);
			expect(sendBeacon).not.toHaveBeenCalled();
		} finally {
			Reflect.deleteProperty(navigator, "sendBeacon");
		}
	});
});
