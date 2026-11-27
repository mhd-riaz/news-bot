import type { InputKind, Method, TextKind } from "./constants";

export interface Profile {
	liked: string[];
	disliked: string[];
	viewed: string[];
	onboarded: boolean;
}

export interface Topic {
	id: string;
	label: string;
	count: unknown;
}

// Fields the reader only displays stay `unknown` until the code that shows them checks them.
export interface Meta {
	snapshot_id: string;
	articles: number;
	methods: Method[];
	default_method: Method;
	topics: Topic[];
	windows: unknown;
	domains: unknown;
	edition_date: unknown;
	edition_timezone: unknown;
	publication_range: unknown;
	collected_before: unknown;
	profile_note: unknown;
	date_note: unknown;
}

export interface Article {
	id: string;
	title: string;
	source_name: string;
	url: string;
	image_url: string;
	published_at: unknown;
	collected_at: unknown;
	date_kind: unknown;
	score: number | null;
	reason: string;
	text: string;
	text_kind: TextKind;
	input_kind: InputKind;
	group: string;
	date_verified: boolean | null;
	fresh: boolean;
}

export interface Selection {
	items: Article[];
	exhausted: unknown;
	unavailable_ids: unknown;
	ignored_viewed_ids: unknown;
	edition_date: unknown;
	window: unknown;
}

export interface SavedItem {
	id: string;
	title: string;
	source_name: string;
	url: string;
	published_at: string;
	note: string;
	saved_at: string;
}

export interface Feedback {
	kind: "loading" | "error" | "empty";
	title: string;
	message: string;
}

export interface RecommendationBody {
	liked: string[];
	disliked: string[];
	viewed: string[];
	method: Method | "";
	limit: number;
	seed_id?: string;
	window?: string;
	topic?: string;
	domains?: string[];
}
