import {
	HISTORY_LIMIT,
	INPUT_KINDS,
	type InputKind,
	isMethod,
	MAX_BATCH,
	NOTE_LIMIT,
	PREFERENCE_LIMIT,
	SAVED_LIMIT,
	TEXT_KINDS,
	type TextKind,
	UUID,
} from "./constants";
import type {
	Article,
	Meta,
	Profile,
	SavedItem,
	Selection,
	Topic,
} from "./types";

// An error the reader can recover from by reloading archive information.
export class ReaderError extends Error {
	readonly reloadMetadata: boolean;

	constructor(message: string, options: { reloadMetadata?: boolean } = {}) {
		super(message);
		this.name = "ReaderError";
		this.reloadMetadata = options.reloadMetadata === true;
	}
}

export function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

export function errorMessage(error: unknown): string {
	return error instanceof Error ? error.message : "";
}

export function emptyProfile(): Profile {
	return { liked: [], disliked: [], viewed: [], onboarded: false };
}

export function ids(value: unknown, limit: number): string[] {
	return Array.isArray(value)
		? [
				...new Set(
					value
						.filter(
							(id): id is string => typeof id === "string" && UUID.test(id),
						)
						.map((id) => id.toLowerCase()),
				),
			].slice(-limit)
		: [];
}

export function normaliseProfile(value: unknown): Profile {
	const profile = isRecord(value) ? value : {};
	const disliked = ids(profile.disliked, PREFERENCE_LIMIT);
	return {
		liked: ids(profile.liked, PREFERENCE_LIMIT).filter(
			(id) => !disliked.includes(id),
		),
		disliked,
		viewed: ids(profile.viewed, HISTORY_LIMIT),
		onboarded: profile.onboarded === true,
	};
}

export function safeURL(value: unknown, image = false): string {
	if (typeof value !== "string" || !value.trim()) return "";
	try {
		const url = new URL(value.trim());
		if (url.username || url.password) return "";
		const allowed = image
			? url.protocol === "https:"
			: ["http:", "https:"].includes(url.protocol);
		return allowed ? url.href : "";
	} catch {
		return "";
	}
}

export function dateValue(value: unknown): Date | null {
	if (typeof value !== "string" || !value.trim()) return null;
	const date = new Date(value);
	return Number.isNaN(date.getTime()) ? null : date;
}

export function articleDate(
	item: Pick<Article, "date_kind" | "published_at" | "collected_at">,
): { date: Date | null; label: "Published" | "Collected" } {
	const publication =
		item.date_kind !== "Collected" ? dateValue(item.published_at) : null;
	const date = publication || dateValue(item.collected_at);
	return { date, label: publication ? "Published" : "Collected" };
}

export function normaliseMetadata(value: unknown): Meta {
	if (
		!isRecord(value) ||
		typeof value.snapshot_id !== "string" ||
		!value.snapshot_id.trim() ||
		typeof value.articles !== "number" ||
		!Number.isSafeInteger(value.articles) ||
		value.articles < 0 ||
		!Array.isArray(value.methods)
	) {
		throw new Error(
			"Archive information was incomplete. Please retry the connection.",
		);
	}
	const methods = [...new Set(value.methods.filter(isMethod))];
	const first = methods[0];
	if (!first) {
		throw new Error(
			"No supported recommendation lens is available for this archive.",
		);
	}
	const defaultMethod =
		value.default_method === undefined ? first : value.default_method;
	if (!isMethod(defaultMethod) || !methods.includes(defaultMethod)) {
		throw new Error("The archive supplied an unsupported default lens.");
	}
	const seen = new Set<string>();
	const topics: Topic[] = [];
	for (const topic of Array.isArray(value.topics) ? value.topics : []) {
		if (
			!isRecord(topic) ||
			typeof topic.id !== "string" ||
			!topic.id ||
			typeof topic.label !== "string" ||
			seen.has(topic.id)
		) {
			continue;
		}
		seen.add(topic.id);
		topics.push({ id: topic.id, label: topic.label, count: topic.count });
	}
	return {
		snapshot_id: value.snapshot_id,
		articles: value.articles,
		methods,
		default_method: defaultMethod,
		topics,
		windows: value.windows,
		domains: value.domains,
		edition_date: value.edition_date,
		edition_timezone: value.edition_timezone,
		publication_range: value.publication_range,
		collected_before: value.collected_before,
		profile_note: value.profile_note,
		date_note: value.date_note,
	};
}

function isTextKind(value: unknown): value is TextKind {
	return (
		typeof value === "string" &&
		(TEXT_KINDS as readonly string[]).includes(value)
	);
}

function isInputKind(value: unknown): value is InputKind {
	return typeof value === "string" && Object.hasOwn(INPUT_KINDS, value);
}

export function normaliseArticle(value: unknown): Article | null {
	if (!isRecord(value) || typeof value.id !== "string" || !UUID.test(value.id))
		return null;
	const text = typeof value.text === "string" ? value.text.trim() : "";
	return {
		id: value.id.toLowerCase(),
		title:
			typeof value.title === "string" && value.title.trim()
				? value.title.trim()
				: "Untitled archived article",
		source_name: typeof value.source_name === "string" ? value.source_name : "",
		url: safeURL(value.url),
		image_url: safeURL(value.image_url, true),
		published_at: value.published_at,
		collected_at: value.collected_at,
		date_kind: value.date_kind,
		score:
			typeof value.score === "number" && Number.isFinite(value.score)
				? value.score
				: null,
		reason: typeof value.reason === "string" ? value.reason : "",
		text,
		text_kind:
			text && isTextKind(value.text_kind) ? value.text_kind : "Headline only",
		input_kind: isInputKind(value.input_kind) ? value.input_kind : "headline",
		group: typeof value.group === "string" ? value.group : "",
		date_verified:
			typeof value.date_verified === "boolean" ? value.date_verified : null,
		fresh: value.fresh === true,
	};
}

export function normaliseResponse(
	value: unknown,
	snapshot: string,
	method: string,
): Selection {
	if (!isRecord(value) || !Array.isArray(value.items)) {
		throw new Error(
			"The archive returned an unreadable selection. Please retry.",
		);
	}
	if (value.snapshot_id !== snapshot) {
		throw new ReaderError(
			"The archive snapshot changed. Reload archive information to use the matching local profile.",
			{ reloadMetadata: true },
		);
	}
	if (value.method !== method) {
		throw new Error(
			"The archive returned a different lens than requested. Please retry.",
		);
	}
	const seen = new Set<string>();
	const items: Article[] = [];
	for (const raw of value.items.slice(0, MAX_BATCH)) {
		const item = normaliseArticle(raw);
		if (!item || seen.has(item.id)) continue;
		seen.add(item.id);
		items.push(item);
	}
	if (value.items.length && !items.length) {
		throw new Error("No valid archived articles were returned. Please retry.");
	}
	return {
		items,
		exhausted: value.exhausted,
		unavailable_ids: value.unavailable_ids,
		ignored_viewed_ids: value.ignored_viewed_ids,
		edition_date: value.edition_date,
		window: value.window,
	};
}

export function normaliseSaved(value: unknown): SavedItem[] {
	const seen = new Set<string>();
	const items: SavedItem[] = [];
	for (const item of Array.isArray(value) ? value : []) {
		if (
			!isRecord(item) ||
			typeof item.id !== "string" ||
			!UUID.test(item.id) ||
			seen.has(item.id.toLowerCase())
		) {
			continue;
		}
		seen.add(item.id.toLowerCase());
		items.push({
			id: item.id.toLowerCase(),
			title:
				typeof item.title === "string" && item.title.trim()
					? item.title.trim().slice(0, 500)
					: "Untitled story",
			source_name:
				typeof item.source_name === "string"
					? item.source_name.slice(0, 200)
					: "",
			url: safeURL(item.url),
			published_at:
				typeof item.published_at === "string" ? item.published_at : "",
			note: typeof item.note === "string" ? item.note.slice(0, NOTE_LIMIT) : "",
			saved_at: typeof item.saved_at === "string" ? item.saved_at : "",
		});
	}
	return items.slice(-SAVED_LIMIT);
}
