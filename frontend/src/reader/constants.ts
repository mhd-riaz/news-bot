export const UUID =
	/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

export type Method = "neural" | "tfidf" | "svd";

export const METHODS: Record<Method, { name: string; note: string }> = {
	neural: {
		name: "Neural",
		note: "Neural · similarity in a learned article-content space, not a model of you.",
	},
	tfidf: {
		name: "TF–IDF",
		note: "TF–IDF · similarities in weighted words. A more literal lens on article content.",
	},
	svd: {
		name: "SVD",
		note: "SVD · similarities in a reduced content space. Another view of the same archive.",
	},
};

// The lens menu keeps the Go reader's order.
export const METHOD_OPTIONS: Method[] = ["tfidf", "neural", "svd"];

export function isMethod(value: unknown): value is Method {
	return typeof value === "string" && Object.hasOwn(METHODS, value);
}

// Preferences and viewed IDs belong to a browser-local profile keyed by snapshot.
export const PREFERENCE_LIMIT = 50;
export const HISTORY_LIMIT = 2000;
// A lead story and eight rows of three, then whole rows; the service caps one request at 30.
export const FIRST_PAGE = 25;
export const MORE_PAGE = 24;
export const MAX_BATCH = 30;
export const EXPLORE_SIZE = 24;
export const EDITION_SIZE = 10;
export const RELATED_SIZE = 6;
export const TASTE_LIMIT = 5;
// Saved stories and notes are browser-only for the demo (owner decision D18); C8 moves them to the account.
export const SAVED_KEY = "afterline:saved";
export const SETTINGS_KEY = "afterline:settings";
export const PROFILE_PREFIX = "afterline:profile:";
export const SAVED_LIMIT = 200;
export const NOTE_LIMIT = 2000;
export const DOMAIN_TAG = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;
export const REQUEST_TIMEOUT_MS = 25000;

export type Theme = "light" | "dark";
export const THEMES: readonly Theme[] = ["light", "dark"];

export type View = "fresh" | "yesterday" | "archive";

export const VIEWS: Record<View, { label: string; note: string }> = {
	fresh: {
		label: "Fresh",
		note: "Stories from the last 30 days with a verified publication date. Newest first until you add interests.",
	},
	yesterday: {
		label: "Yesterday",
		note: "Up to 10 stories published yesterday, one per story, ranked by your interests.",
	},
	archive: {
		label: "Archive",
		note: "Older stories, plus stories whose publication date could not be verified.",
	},
};

export const VIEW_ORDER: View[] = ["fresh", "yesterday", "archive"];

export const ZONE_NAMES: Record<string, string> = {
	"Asia/Kolkata": "India time",
	UTC: "UTC",
};

export const INPUT_KINDS = {
	body: "article body",
	summary: "stored summary",
	headline: "headline only",
} as const;

export type InputKind = keyof typeof INPUT_KINDS;

export const TEXT_KINDS = [
	"Stored summary",
	"Excerpt",
	"Headline only",
] as const;

export type TextKind = (typeof TEXT_KINDS)[number];
