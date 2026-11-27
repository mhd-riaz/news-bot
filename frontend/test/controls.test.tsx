import { screen, waitFor, within } from "@testing-library/react";
import { describe, expect, test } from "vitest";
import { SAVED_KEY, SETTINGS_KEY } from "../src/reader/constants";
import {
	$,
	article,
	FakeServer,
	id,
	META,
	PROFILE_KEY,
	renderReader,
	response,
	selection,
	settled,
	storedProfile,
	tileTitles,
} from "./harness";

const checkboxes = () =>
	within($("taste-list")).getAllByRole<HTMLInputElement>("checkbox");

describe("choosing interests", () => {
	test("chosen stories become likes, at most five, and open a new selection", async () => {
		const server = new FakeServer();
		const offered = [1, 2, 3, 4, 5, 6].map((number) => article(number));
		server.serve(selection(offered, { exhausted: false }));
		const { user } = await renderReader();
		expect($("onboarding-invite").hidden).toBe(false);
		expect($("edit-interests").hidden).toBe(true);
		await user.click($("start-onboarding"));
		expect($<HTMLDialogElement>("taste-dialog").open).toBe(true);
		// The first page is offered again without another request.
		expect(server.feedCalls()).toHaveLength(1);
		expect(checkboxes()).toHaveLength(6);
		expect($("taste-submit").textContent).toBe("Explore without selecting ↗");
		const [one, two, three, four, five, six] = checkboxes();
		if (!one || !two || !three || !four || !five || !six)
			throw new Error("Six choices.");
		await user.click(one);
		await user.click(two);
		expect($("taste-count").textContent).toBe("2 / 5 selected");
		expect($("taste-submit").textContent).toBe("Add 2 interests ↗");
		for (const box of [three, four, five]) await user.click(box);
		expect($("taste-count").textContent).toBe("5 / 5 selected");
		expect(six.disabled).toBe(true);
		expect($("taste-hint").textContent).toMatch(/^Five selected/);
		await user.click(five);
		expect(six.disabled).toBe(false);
		server.serve(selection([article(7)]));
		await user.click($("taste-submit"));
		expect($<HTMLDialogElement>("taste-dialog").open).toBe(false);
		await settled();
		const liked = [id(1), id(2), id(3), id(4)];
		expect(storedProfile()).toMatchObject({ liked, onboarded: true });
		expect(server.lastBody().liked).toEqual(liked);
		expect($("action-status").textContent).toBe(
			"4 interests added. Opening a new selection using your choices.",
		);
		expect(document.activeElement).toBe($("reader-panel"));
		expect($("onboarding-invite").hidden).toBe(true);
		expect($("edit-interests").hidden).toBe(false);
		expect($("selection-label").textContent).toBe("For you");
		expect($("view-note").textContent).toBe(
			"Stories from the last 30 days with a verified publication date, ranked around the stories you like.",
		);
	});

	test("skipping adds nothing and moves focus to Find more interests", async () => {
		new FakeServer().serve(selection([article(1)]));
		const { user } = await renderReader();
		await user.click($("skip-onboarding"));
		expect($("onboarding-invite").hidden).toBe(true);
		expect(document.activeElement).toBe($("edit-interests"));
		expect($("action-status").textContent).toBe(
			"No new interests added. You can choose them any time; opening a story never adds one.",
		);
		expect(storedProfile()).toMatchObject({ liked: [], onboarded: true });
	});

	test("the picker asks for stories when none are cached, and a failure can be retried", async () => {
		localStorage.setItem(
			PROFILE_KEY,
			JSON.stringify({
				liked: [id(9)],
				disliked: [],
				viewed: [],
				onboarded: true,
			}),
		);
		const server = new FakeServer();
		server.serve(selection([article(1)]));
		const { user } = await renderReader();
		server.serve(
			{
				error: {
					code: "unavailable",
					message: "Recommendations are unavailable.",
				},
			},
			503,
		);
		await user.click($("edit-interests"));
		await waitFor(() => expect($("taste-error").hidden).toBe(false));
		expect($("taste-error-message").textContent).toBe(
			"Recommendations are unavailable.",
		);
		expect($("taste-retry").textContent).toBe("Retry Explore");
		expect($<HTMLButtonElement>("taste-submit").disabled).toBe(true);
		expect(server.lastBody()).toMatchObject({
			liked: [],
			limit: 24,
			window: "fresh",
		});
		server.serve(selection([article(2), article(3)]));
		await user.click($("taste-retry"));
		await waitFor(() => expect(checkboxes()).toHaveLength(2));
		expect($("taste-loading").hidden).toBe(true);
		expect($("taste-empty").hidden).toBe(true);
		await user.click($("close-taste"));
		expect($<HTMLDialogElement>("taste-dialog").open).toBe(false);
	});
});

describe("other controls", () => {
	test("reset clears interests and history for this snapshot, not saved stories", async () => {
		localStorage.setItem(
			PROFILE_KEY,
			JSON.stringify({
				liked: [id(9)],
				disliked: [id(8)],
				viewed: [id(7)],
				onboarded: true,
			}),
		);
		localStorage.setItem(
			SAVED_KEY,
			JSON.stringify([{ id: id(5), title: "Kept" }]),
		);
		const server = new FakeServer();
		server.serve(selection([article(1)]));
		const { user } = await renderReader();
		expect($("profile-summary").textContent).toBe(
			"1 like · 1 not interested · local to this snapshot",
		);
		expect($("corpus-coverage").textContent).toBe(
			"1 of 5,000 articles opened locally · <0.1% of the collection. Stories you only scroll past do not count.",
		);
		await user.click($("open-reset"));
		expect($<HTMLDialogElement>("reset-dialog").open).toBe(true);
		await user.click($("cancel-reset"));
		expect($<HTMLDialogElement>("reset-dialog").open).toBe(false);
		await user.click($("open-reset"));
		await user.click(screen.getByRole("button", { name: "Reset & explore" }));
		await settled();
		expect(storedProfile()).toEqual({
			liked: [],
			disliked: [],
			viewed: [],
			onboarded: false,
		});
		expect(server.lastBody()).toMatchObject({
			liked: [],
			disliked: [],
			viewed: [],
		});
		expect($("action-status").textContent).toBe(
			"Interests and viewed history cleared for this snapshot. Newly opened stories start a fresh history.",
		);
		expect($("open-saved").textContent).toBe("Saved stories (1)");
		expect(document.activeElement).toBe($("reader-panel"));
	});

	test("professional focus appears with domain tags, sends them, and is remembered", async () => {
		const server = new FakeServer();
		server.meta = () =>
			response({ ...META, domains: { ai: 3, "data-science": 2 } });
		server.serve(selection([article(1)]));
		const { user } = await renderReader();
		const focus = $("professional-focus");
		expect(focus.hidden).toBe(false);
		expect(focus.getAttribute("role")).toBe("switch");
		expect(focus.getAttribute("aria-checked")).toBe("false");
		expect("domains" in server.lastBody()).toBe(false);
		await user.click(focus);
		await settled();
		expect(focus.getAttribute("aria-checked")).toBe("true");
		expect(server.lastBody().domains).toEqual(["ai", "data-science"]);
		expect($("view-note").textContent).toMatch(
			/Professional focus: ai, data-science sources only\.$/,
		);
		expect(JSON.parse(localStorage.getItem(SETTINGS_KEY) ?? "null")).toEqual({
			professional: true,
		});
	});

	test("without domain tags the professional switch stays hidden", async () => {
		new FakeServer().serve(selection([article(1)]));
		await renderReader();
		expect($("professional-focus").hidden).toBe(true);
	});

	test("the server's default lens is used first, and another lens reloads the stories", async () => {
		const server = new FakeServer();
		server.meta = () =>
			response({ ...META, methods: ["tfidf", "svd"], default_method: "tfidf" });
		server.recommend = (call) =>
			response(selection([article(1)], { method: call.body?.method }));
		const { user } = await renderReader();
		const lens = $<HTMLSelectElement>("method");
		expect(lens.value).toBe("tfidf");
		expect(server.lastBody().method).toBe("tfidf");
		expect($("lens-note").textContent).toBe(
			"TF–IDF · similarities in weighted words. A more literal lens on article content.",
		);
		expect(
			[...lens.options].map((option) => [option.value, option.disabled]),
		).toEqual([
			["tfidf", false],
			["neural", true],
			["svd", false],
		]);
		await user.selectOptions(lens, "svd");
		await settled();
		expect(server.lastBody().method).toBe("svd");
		expect($("lens-note").textContent).toMatch(/^SVD ·/);
	});

	test("a thread button narrows the stories and names the thread", async () => {
		const server = new FakeServer();
		server.meta = () =>
			response({
				...META,
				topics: [
					{ id: "0", label: "space / research", count: 1200 },
					{ id: "1", label: "markets" },
				],
			});
		server.serve(selection([article(1)]));
		const { user } = await renderReader();
		expect($("topic-all-count").textContent).toBe("5,000");
		expect($("topic-status").textContent).toBe(
			"2 content groups available. These are unsupervised clusters.",
		);
		const space = screen.getByRole("button", { name: /space \/ research/ });
		expect(space.getAttribute("title")).toBe(
			"space / research · 1,200 articles",
		);
		await user.click(space);
		await settled();
		expect(server.lastBody().topic).toBe("0");
		expect(space.getAttribute("aria-pressed")).toBe("true");
		expect($("topic-all").getAttribute("aria-pressed")).toBe("false");
		expect($("selection-note").textContent).toBe("Thread: space / research");
		await user.click($("view-archive"));
		await settled();
		expect(server.lastBody()).toMatchObject({ window: "archive", topic: "0" });
		expect($("selection-label").textContent).toBe("From the archive");
	});

	test("an article link opens related reading around that story; a bad link explains itself", async () => {
		window.history.replaceState(null, "", `/?article=${id(9).toUpperCase()}`);
		const server = new FakeServer();
		server.serve(selection([article(1)]));
		const first = await renderReader();
		expect(server.lastBody()).toMatchObject({ seed_id: id(9), limit: 25 });
		expect("window" in server.lastBody()).toBe(false);
		expect($("selection-label").textContent).toBe("Related reading");
		expect($("selection-note").textContent).toBe(
			"Using the article in your link as a content seed.",
		);
		expect(tileTitles()).toEqual(["Archived story 1"]);
		first.unmount();
		window.history.replaceState(null, "", "/?article=not-an-id");
		await renderReader();
		expect($("link-note").hidden).toBe(false);
		expect($("link-note").textContent).toBe(
			"That article link is not a valid archive ID. Exploring the collection instead.",
		);
		expect(server.lastBody().window).toBe("fresh");
	});
});
