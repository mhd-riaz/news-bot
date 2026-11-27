import { describe, expect, test } from "vitest";
import {
	articleDate,
	emptyProfile,
	ids,
	normaliseArticle,
	normaliseMetadata,
	normaliseProfile,
	normaliseResponse,
	normaliseSaved,
	ReaderError,
	safeURL,
} from "../src/reader/normalise";
import { article, id, identifiers, selection } from "./harness";

describe("browser-stored values", () => {
	test("profile sanitization enforces limits, UUID uniqueness, and opposing choices", () => {
		const profile = normaliseProfile({
			liked: identifiers(60),
			disliked: [...identifiers(59, 100), id(60)],
			viewed: identifiers(2050),
			onboarded: "true",
		});
		expect(profile.liked).toHaveLength(49);
		expect(profile.liked[0]).toBe(id(11));
		expect(profile.liked).not.toContain(id(60));
		expect(profile.disliked).toHaveLength(50);
		expect(profile.viewed).toHaveLength(2000);
		expect(profile.viewed[0]).toBe(id(51));
		expect(profile.viewed.at(-1)).toBe(id(2050));
		expect(profile.onboarded).toBe(false);
		expect(
			ids([id(0xabcdef).toUpperCase(), id(0xabcdef), "invalid", null], 50),
		).toEqual([id(0xabcdef)]);
		expect(normaliseProfile(null)).toEqual(emptyProfile());
	});

	test("saved stories are deduplicated, bounded, and keep only safe links", () => {
		const cleaned = normaliseSaved([
			{ id: id(5), title: "  Kept  ", url: "javascript:alert(1)", note: 7 },
			{ id: id(5).toUpperCase(), title: "Duplicate" },
			{ id: "not-a-uuid" },
			null,
		]);
		expect(cleaned.map((item) => [item.title, item.url, item.note])).toEqual([
			["Kept", "", ""],
		]);
		expect(
			normaliseSaved(identifiers(250).map((value) => ({ id: value }))),
		).toHaveLength(200);
		expect(
			normaliseSaved([{ id: id(1), note: "x".repeat(2100) }])[0]?.note,
		).toHaveLength(2000);
	});
});

describe("links and dates", () => {
	test("external links allow only HTTP(S), images only HTTPS, without credentials", () => {
		for (const value of [
			null,
			"",
			"/relative",
			"//example.invalid",
			"javascript:alert(1)",
			"data:text/html,unsafe",
			"file:///etc/passwd",
			"https://name:password@example.invalid",
		]) {
			expect(safeURL(value), String(value)).toBe("");
			expect(safeURL(value, true), String(value)).toBe("");
		}
		expect(safeURL("http://example.invalid/article")).toBe(
			"http://example.invalid/article",
		);
		expect(safeURL("http://example.invalid/image", true)).toBe("");
		expect(safeURL(" https://example.invalid/image ", true)).toBe(
			"https://example.invalid/image",
		);
	});

	test("a publication date is used unless the story is labelled as collected", () => {
		expect(articleDate(article(3)).label).toBe("Published");
		const collected = articleDate(article(4, { date_kind: "Collected" }));
		expect([collected.label, collected.date?.toISOString()]).toEqual([
			"Collected",
			"2024-03-02T00:30:00.000Z",
		]);
		expect(
			articleDate(article(5, { published_at: "invalid", collected_at: "" }))
				.date,
		).toBe(null);
	});
});

describe("server answers", () => {
	test("metadata rejects invalid counts or missing lenses and deduplicates real groups", () => {
		for (const articles of [-1, 1.5, "3"]) {
			expect(() =>
				normaliseMetadata({ snapshot_id: "a", articles, methods: ["neural"] }),
			).toThrow(/incomplete/);
		}
		expect(() => normaliseMetadata(null)).toThrow(/incomplete/);
		expect(() =>
			normaliseMetadata({
				snapshot_id: "a",
				articles: 0,
				methods: ["unknown", "__proto__"],
			}),
		).toThrow(/No supported/);
		const meta = normaliseMetadata({
			snapshot_id: "a",
			articles: 0,
			methods: ["tfidf", "unknown", "tfidf", "svd"],
			topics: [
				{ id: "0", label: "space / research / science" },
				{ id: "0", label: "duplicate" },
				null,
			],
		});
		expect(meta.methods).toEqual(["tfidf", "svd"]);
		expect(meta.topics).toHaveLength(1);
		expect(meta.topics[0]?.label).toBe("space / research / science");
	});

	test("metadata selects the evaluated baseline default and rejects an unsupported default", () => {
		const metadata = {
			snapshot_id: "snapshot-a",
			articles: 20,
			methods: ["tfidf", "svd", "neural"],
			default_method: "tfidf",
			topics: [],
		};
		expect(normaliseMetadata(metadata).default_method).toBe("tfidf");
		expect(
			normaliseMetadata({ ...metadata, default_method: undefined })
				.default_method,
		).toBe("tfidf");
		expect(() =>
			normaliseMetadata({ ...metadata, default_method: "unsupported" }),
		).toThrow(/unsupported default/);
	});

	test("responses enforce the snapshot, requested lens, valid IDs, and a bounded batch", () => {
		expect(() => normaliseResponse({}, "snapshot-a", "neural")).toThrow(
			/unreadable/,
		);
		let changed: unknown;
		try {
			normaliseResponse(
				selection([], { snapshot_id: "b" }),
				"snapshot-a",
				"neural",
			);
		} catch (error) {
			changed = error;
		}
		expect(changed).toBeInstanceOf(ReaderError);
		expect((changed as ReaderError).reloadMetadata).toBe(true);
		expect(() =>
			normaliseResponse(
				selection([], { method: "svd" }),
				"snapshot-a",
				"neural",
			),
		).toThrow(/different lens/);
		expect(() =>
			normaliseResponse(selection([{ id: "invalid" }]), "snapshot-a", "neural"),
		).toThrow(/No valid/);
		const deduplicated = normaliseResponse(
			selection([article(1), article(1), { id: "invalid" }, article(2)]),
			"snapshot-a",
			"neural",
		);
		expect(deduplicated.items.map((item) => item.id)).toEqual([id(1), id(2)]);
		const many = identifiers(40).map((_, index) => article(index + 1));
		expect(
			normaliseResponse(selection(many), "snapshot-a", "neural").items,
		).toHaveLength(30);
	});

	test("articles keep text literal and fall back to safe defaults", () => {
		const hostile = "<img src=x onerror=alert(1)>";
		const item = normaliseArticle(
			article(1, {
				title: hostile,
				url: "javascript:alert(1)",
				image_url: "http://example.invalid/image",
				score: Number.POSITIVE_INFINITY,
				text: "",
				text_kind: "Stored summary",
				input_kind: "something else",
			}),
		);
		expect(item).toMatchObject({
			title: hostile,
			url: "",
			image_url: "",
			score: null,
			text_kind: "Headline only",
			input_kind: "headline",
		});
		expect(
			normaliseArticle({ id: id(2).toUpperCase(), title: " " }),
		).toMatchObject({
			id: id(2),
			title: "Untitled archived article",
		});
	});
});
