import { ApiError, requestJSON } from "../api";
import {
	EDITION_SIZE,
	EXPLORE_SIZE,
	FIRST_PAGE,
	HISTORY_LIMIT,
	isMethod,
	METHOD_OPTIONS,
	type Method,
	MORE_PAGE,
	NOTE_LIMIT,
	PREFERENCE_LIMIT,
	PROFILE_PREFIX,
	RELATED_SIZE,
	SAVED_KEY,
	SAVED_LIMIT,
	SETTINGS_KEY,
	TASTE_LIMIT,
	THEMES,
	type Theme,
	UUID,
	VIEWS,
	type View,
} from "./constants";
import {
	countFormat,
	createFormats,
	type DateFormats,
	editionDate,
	storyDateLabel,
	zoneName,
} from "./format";
import {
	dateValue,
	emptyProfile,
	errorMessage,
	isRecord,
	normaliseMetadata,
	normaliseProfile,
	normaliseResponse,
	normaliseSaved,
	ReaderError,
} from "./normalise";
import {
	activeList,
	canNext,
	canPrevious,
	currentArticle,
	isDark,
	isEdition,
	professionalDomains,
} from "./selectors";
import type {
	Article,
	Feedback,
	Meta,
	Profile,
	RecommendationBody,
	SavedItem,
	Selection,
	Topic,
} from "./types";

export type FocusRequest =
	| { kind: "story" }
	| { kind: "edit-interests" }
	| { kind: "panel" }
	| { kind: "after-close"; opener: HTMLElement | null; index: number };

// A live-region message. The count changes on every announcement, so a message
// repeated word for word is still read out.
export interface Message {
	text: string;
	count: number;
}

// Archive facts are written when metadata loads and kept until the next load,
// as the Go reader's page did.
export interface Facts {
	corpusCount: string;
	freshCount: string;
	editionLabel: string;
	editionCount: string;
	publicationRange: string;
	collectionCutoff: string;
	snapshotLabel: string;
	snapshotTitle: string;
	profileNote: string;
	dateNote: string;
	methods: Method[];
	topics: Topic[];
	topicAllCount: string;
}

export interface ReaderState {
	meta: Meta | null;
	profile: Profile;
	storageKey: string;
	persistence: boolean;
	method: Method | "";
	view: View;
	professional: boolean;
	theme: Theme | "";
	systemDark: boolean;
	saved: SavedItem[];
	noteFor: string;
	noteDraft: string;
	noteStatus: string;
	topic: string;
	seed: string;
	seedTitle: string;
	items: Article[];
	exhausted: boolean;
	stale: boolean;
	loading: boolean;
	feedback: Feedback | null;
	retryKind: "meta" | "feed";
	retryReplace: boolean;
	endMessage: string;
	exploreCache: Article[] | null;
	tasteOpen: boolean;
	tasteStatus: "loading" | "error" | "ready";
	tasteError: string;
	tasteItems: Article[];
	selected: string[];
	tasteLoading: boolean;
	tasteReload: boolean;
	readerOpen: boolean;
	open: number;
	readerTrail: Article[] | null;
	related: Article[];
	relatedStatus: string;
	pushedHistory: boolean;
	savedOpen: boolean;
	resetOpen: boolean;
	actionStatus: Message;
	readerStatus: Message;
	readerLive: Message;
	storageWarning: string;
	linkNote: string;
	serviceNote: string;
	topicStatus: string;
	coverage: string;
	facts: Facts;
	focus: FocusRequest | null;
}

export interface ReaderOptions {
	// Called when the server says the session has ended.
	onSignInRequired?: () => void;
}

function initialFacts(): Facts {
	return {
		corpusCount: "—",
		freshCount: "—",
		editionLabel: "Yesterday’s edition",
		editionCount: "—",
		publicationRange: "Waiting for archive information",
		collectionCutoff: "—",
		snapshotLabel: "Connecting to archive",
		snapshotTitle: "",
		profileNote:
			"Profiles are saved only in this browser for this snapshot and included in same-origin recommendation requests.",
		dateNote:
			"Every story belongs to a snapshot taken at a fixed time. Dates are absolute; a date is verified only when the publisher supplied it.",
		methods: METHOD_OPTIONS,
		topics: [],
		topicAllCount: "",
	};
}

function initialState(): ReaderState {
	return {
		meta: null,
		profile: emptyProfile(),
		storageKey: "",
		persistence: true,
		method: "",
		view: "fresh",
		professional: false,
		theme: "",
		systemDark: false,
		saved: [],
		noteFor: "",
		noteDraft: "",
		noteStatus: "",
		topic: "",
		seed: "",
		seedTitle: "",
		items: [],
		exhausted: false,
		stale: false,
		loading: true,
		feedback: {
			kind: "loading",
			title: "Opening the stories.",
			message: "Connecting to the recommendation service.",
		},
		retryKind: "meta",
		retryReplace: true,
		endMessage: "",
		exploreCache: null,
		tasteOpen: false,
		tasteStatus: "loading",
		tasteError: "",
		tasteItems: [],
		selected: [],
		tasteLoading: false,
		tasteReload: false,
		readerOpen: false,
		open: -1,
		readerTrail: null,
		related: [],
		relatedStatus: "",
		pushedHistory: false,
		savedOpen: false,
		resetOpen: false,
		actionStatus: {
			text: "Likes are your choice. Opening a story never adds an interest.",
			count: 0,
		},
		readerStatus: { text: "", count: 0 },
		readerLive: { text: "", count: 0 },
		storageWarning: "",
		linkNote: "",
		serviceNote: "",
		topicStatus: "Loading content groups.",
		coverage: "Coverage counts only the stories you actually open here.",
		facts: initialFacts(),
		focus: null,
	};
}

function isTheme(value: unknown): value is Theme {
	return (
		typeof value === "string" && (THEMES as readonly string[]).includes(value)
	);
}

function message(previous: Message, text: string): Message {
	return { text, count: previous.count + 1 };
}

// The reader's state and actions. React components render `getSnapshot()` and
// call these methods; nothing here writes to the page except the theme attribute.
export class ReaderStore {
	state: ReaderState = initialState();
	formats: DateFormats = createFormats("UTC");
	private snapshot: ReaderState = { ...this.state };
	private readonly listeners = new Set<() => void>();
	private readonly options: ReaderOptions;
	private metaVersion = 0;
	private feedVersion = 0;
	private tasteVersion = 0;
	private relatedVersion = 0;
	private ignoredPops = 0;
	private metaController: AbortController | null = null;
	private feedController: AbortController | null = null;
	private tasteController: AbortController | null = null;
	private relatedController: AbortController | null = null;
	private opener: HTMLElement | null = null;
	private darkQuery: MediaQueryList | null = null;
	private started = false;

	constructor(options: ReaderOptions = {}) {
		this.options = options;
	}

	subscribe = (listener: () => void): (() => void) => {
		this.listeners.add(listener);
		return () => {
			this.listeners.delete(listener);
		};
	};

	getSnapshot = (): ReaderState => this.snapshot;

	private emit(): void {
		const meta = this.state.meta;
		if (meta) {
			const viewed = Math.min(this.state.profile.viewed.length, meta.articles);
			const percent = meta.articles ? (viewed / meta.articles) * 100 : 0;
			const coverage =
				percent > 0 && percent < 0.1 ? "<0.1" : percent.toFixed(1);
			this.state.coverage = `${countFormat.format(viewed)} of ${countFormat.format(meta.articles)} articles opened locally · ${coverage}% of the collection. Stories you only scroll past do not count.`;
		}
		this.snapshot = { ...this.state };
		for (const listener of this.listeners) listener();
	}

	// ---- Browser storage -------------------------------------------------

	private warnStorage(text: string): void {
		this.state.storageWarning = text;
	}

	readProfile(): Profile {
		let stored: string | null;
		try {
			stored = window.localStorage.getItem(this.state.storageKey);
		} catch {
			this.state.persistence = false;
			this.warnStorage(
				"Local storage is unavailable. Interests and viewed history will last only in this open tab, not after you leave.",
			);
			return emptyProfile();
		}
		if (!stored) return emptyProfile();
		try {
			return normaliseProfile(JSON.parse(stored));
		} catch {
			this.warnStorage(
				"The saved profile could not be read. Starting with empty interests for this snapshot; new choices will replace that unreadable local profile.",
			);
			return emptyProfile();
		}
	}

	saveProfile(): void {
		if (!this.state.persistence || !this.state.storageKey) return;
		try {
			window.localStorage.setItem(
				this.state.storageKey,
				JSON.stringify(this.state.profile),
			);
		} catch {
			this.state.persistence = false;
			this.warnStorage(
				"Your latest choices could not be saved. Persistence is unavailable; interests and history now last only in this open tab. Older saved choices may return on your next visit.",
			);
		}
	}

	readSettings(): { professional: boolean; theme: Theme | "" } {
		try {
			const value: unknown = JSON.parse(
				window.localStorage.getItem(SETTINGS_KEY) || "{}",
			);
			const settings = isRecord(value) ? value : {};
			return {
				professional: settings.professional === true,
				theme: isTheme(settings.theme) ? settings.theme : "",
			};
		} catch {
			return { professional: false, theme: "" };
		}
	}

	private saveSettings(): void {
		try {
			window.localStorage.setItem(
				SETTINGS_KEY,
				JSON.stringify({
					professional: this.state.professional,
					...(this.state.theme ? { theme: this.state.theme } : {}),
				}),
			);
		} catch {
			// The setting still applies in this tab; storage problems are reported by profile writes.
		}
	}

	readSaved(): SavedItem[] {
		try {
			return normaliseSaved(
				JSON.parse(window.localStorage.getItem(SAVED_KEY) || "[]"),
			);
		} catch {
			this.warnStorage(
				"Saved stories could not be read in this browser. New saves start a fresh list.",
			);
			return [];
		}
	}

	private writeSaved(): boolean {
		try {
			window.localStorage.setItem(SAVED_KEY, JSON.stringify(this.state.saved));
			return true;
		} catch {
			this.warnStorage(
				"Saved stories could not be stored in this browser; they last only in this open tab.",
			);
			return false;
		}
	}

	// ---- Theme -----------------------------------------------------------

	isDark(): boolean {
		return isDark(this.state);
	}

	// Without a saved choice the stylesheet follows the computer's setting.
	applyTheme(): void {
		const root = document.documentElement;
		if (this.state.theme) root.dataset.theme = this.state.theme;
		else root.removeAttribute("data-theme");
	}

	toggleTheme(): void {
		this.state.theme = this.isDark() ? "light" : "dark";
		this.saveSettings();
		this.applyTheme();
		this.announce(
			`${this.state.theme === "dark" ? "Dark" : "Light"} theme on. Saved in this browser.`,
		);
		this.emit();
	}

	private onDarkChange = (): void => {
		this.state.systemDark = Boolean(this.darkQuery?.matches);
		this.applyTheme();
		this.emit();
	};

	// ---- Saved stories and notes ----------------------------------------

	savedItem(id: string): SavedItem | null {
		return this.state.saved.find((item) => item.id === id) ?? null;
	}

	toggleSaved(article: Article | null = this.currentArticle()): void {
		if (!article) return;
		const reading = this.currentArticle()?.id === article.id;
		if (this.savedItem(article.id)) {
			this.state.saved = this.state.saved.filter(
				(item) => item.id !== article.id,
			);
			this.announce("Removed from saved stories.");
		} else {
			this.state.saved = [
				...this.state.saved,
				{
					id: article.id,
					title: article.title,
					source_name: article.source_name,
					url: article.url,
					published_at:
						typeof article.published_at === "string"
							? article.published_at
							: "",
					note: "",
					saved_at: new Date().toISOString(),
				},
			].slice(-SAVED_LIMIT);
			this.announce(
				reading
					? "Saved in this browser. Add a note below if you like."
					: "Saved in this browser. Open the story to add a note.",
			);
		}
		this.writeSaved();
		// A related tile can be saved while another story is open; that story's note box stays untouched.
		if (reading) {
			this.state.noteDraft = this.savedItem(article.id)?.note || "";
			this.state.noteStatus = "";
		}
		this.emit();
	}

	removeSaved(id: string): void {
		this.state.saved = this.state.saved.filter((item) => item.id !== id);
		this.writeSaved();
		this.emit();
	}

	// The note box belongs to the story it was filled for, even after navigation has moved on.
	private persistNote(): boolean | null {
		const item = this.state.noteFor ? this.savedItem(this.state.noteFor) : null;
		if (!item) return null;
		const note = String(this.state.noteDraft).slice(0, NOTE_LIMIT);
		if (item.note === note) return true;
		this.state.saved = this.state.saved.map((entry) =>
			entry.id === item.id ? { ...entry, note } : entry,
		);
		return this.writeSaved();
	}

	// Persist quietly while typing, so a swipe, reload or closed tab cannot lose a note.
	inputNote(value: string): void {
		this.state.noteDraft = value;
		this.persistNote();
		this.emit();
	}

	saveNote(): void {
		const saved = this.persistNote();
		if (saved === null) return;
		this.state.noteStatus = saved
			? "Note saved in this browser."
			: "Note kept for this tab only.";
		this.announce("Note saved.");
		this.emit();
	}

	// ---- Archive information --------------------------------------------

	setTimeZone(zone: string): void {
		try {
			this.formats = createFormats(zone);
		} catch {
			// An unknown zone keeps the previous formats rather than breaking the page.
		}
	}

	zoneName(): string {
		return zoneName(this.formats.timeZone);
	}

	editionDate(): string {
		return editionDate(this.state.meta);
	}

	professionalDomains(): string[] {
		return professionalDomains(this.state.meta);
	}

	private buildTopics(meta: Meta): void {
		this.state.facts = {
			...this.state.facts,
			topics: meta.topics,
			topicAllCount: countFormat.format(meta.articles),
		};
		this.state.topicStatus = `${meta.topics.length} content groups available. These are unsupervised clusters.`;
	}

	private renderMetadata(meta: Meta): void {
		if (typeof meta.edition_timezone === "string" && meta.edition_timezone) {
			this.setTimeZone(meta.edition_timezone);
		}
		const { shortDate, dateTime } = this.formats;
		const windows = isRecord(meta.windows) ? meta.windows : {};
		const count = (value: unknown) =>
			typeof value === "number" && Number.isSafeInteger(value)
				? countFormat.format(value)
				: "";
		const range = Array.isArray(meta.publication_range)
			? meta.publication_range.map(dateValue)
			: [];
		const [from, to] = range;
		const cutoff = dateValue(meta.collected_before);
		const yesterday = count(windows.yesterday);
		this.state.facts = {
			...this.state.facts,
			corpusCount: countFormat.format(meta.articles),
			freshCount: count(windows.fresh) || "Not supplied",
			editionLabel: `Yesterday’s edition · ${this.editionDate()}`,
			editionCount: yesterday
				? `${yesterday} stories published that day`
				: "Not supplied",
			publicationRange:
				range.length === 2 && from && to
					? `${shortDate.format(from)} — ${shortDate.format(to)}`
					: "Publication range not supplied",
			collectionCutoff: cutoff
				? `${dateTime.format(cutoff)} (${this.zoneName()})`
				: "Cutoff not supplied",
			snapshotLabel: `Snapshot ${meta.snapshot_id.slice(0, 12)}`,
			snapshotTitle: meta.snapshot_id,
			profileNote: `Profiles are saved only in this browser and included in same-origin recommendation requests. Article content and explicit interests only; no account or historical-user learning.${typeof meta.profile_note === "string" ? ` ${meta.profile_note}` : ""}`,
			dateNote: `A snapshot taken at a fixed time, not a live feed. Dates are absolute and shown in ${this.zoneName()}.${typeof meta.date_note === "string" ? ` ${meta.date_note}` : " Collection dates are labelled when publication dates are unavailable."}`,
			methods: meta.methods,
		};
	}

	// ---- Requests -------------------------------------------------------

	private async request(
		path: string,
		controller: AbortController,
		body?: RecommendationBody,
	): Promise<unknown> {
		try {
			return await requestJSON(path, controller, body);
		} catch (error) {
			if (error instanceof ApiError && error.signInRequired) {
				this.options.onSignInRequired?.();
			}
			throw error;
		}
	}

	private stopFeed(): void {
		this.feedVersion += 1;
		this.feedController?.abort();
		this.feedController = null;
		this.state.loading = false;
	}

	private stopTaste(): void {
		this.tasteVersion += 1;
		this.tasteController?.abort();
		this.tasteController = null;
		this.state.tasteLoading = false;
	}

	private stopRelated(): void {
		this.relatedVersion += 1;
		this.relatedController?.abort();
		this.relatedController = null;
	}

	isEdition(): boolean {
		return isEdition(this.state);
	}

	bodyFor(explore = false): RecommendationBody {
		const { state } = this;
		// A daily edition is a fixed selection: opening a story must not remove it on the next visit.
		const edition = state.view === "yesterday" && (explore || !state.seed);
		// Stories already on the page are left out of the next page without being marked viewed.
		const shown = explore ? [] : state.items.map((item) => item.id);
		let limit = FIRST_PAGE;
		if (explore) limit = EXPLORE_SIZE;
		else if (edition) limit = EDITION_SIZE;
		else if (shown.length) limit = MORE_PAGE;
		const body: RecommendationBody = {
			liked: explore ? [] : state.profile.liked.slice(-PREFERENCE_LIMIT),
			disliked: state.profile.disliked.slice(-PREFERENCE_LIMIT),
			viewed: edition
				? []
				: [...new Set([...state.profile.viewed, ...shown])].slice(
						-HISTORY_LIMIT,
					),
			method: state.method,
			limit,
		};
		// Related reading spans fresh and archived stories, so older background can surface (C7, R23).
		if (!explore && state.seed) body.seed_id = state.seed;
		else if (Object.hasOwn(VIEWS, state.view)) body.window = state.view;
		if (!explore && state.topic) body.topic = state.topic;
		const domains = state.professional ? this.professionalDomains() : [];
		if (domains.length) body.domains = domains;
		return body;
	}

	relatedBody(article: Article): RecommendationBody {
		const { state } = this;
		const body: RecommendationBody = {
			liked: state.profile.liked.slice(-PREFERENCE_LIMIT),
			disliked: state.profile.disliked.slice(-PREFERENCE_LIMIT),
			viewed: state.profile.viewed.slice(-HISTORY_LIMIT),
			method: state.method,
			limit: RELATED_SIZE,
			seed_id: article.id,
		};
		const domains = state.professional ? this.professionalDomains() : [];
		if (domains.length) body.domains = domains;
		return body;
	}

	// ---- The reading view -----------------------------------------------

	activeList(): Article[] {
		return activeList(this.state);
	}

	currentArticle(): Article | null {
		return currentArticle(this.state);
	}

	findArticle(id: string): Article | null {
		return (
			[this.state.items, this.state.related, this.state.readerTrail || []]
				.flat()
				.find((item) => item.id === id) ?? null
		);
	}

	canPrevious(): boolean {
		return canPrevious(this.state);
	}

	canNext(): boolean {
		return canNext(this.state);
	}

	// An announcement from outside the store, such as a failed sign-out.
	notify(text: string): void {
		this.announce(text);
		this.emit();
	}

	announce(text: string): void {
		this.state.actionStatus = message(this.state.actionStatus, text);
		this.state.readerStatus = message(
			this.state.readerStatus,
			this.state.readerOpen ? text : "",
		);
	}

	private setReaderStatus(text: string): void {
		this.state.readerStatus = message(this.state.readerStatus, text);
	}

	private setReaderLive(text: string): void {
		this.state.readerLive = message(this.state.readerLive, text);
	}

	private renderStory(article: Article): void {
		this.persistNote();
		this.state.noteFor = article.id;
		this.state.noteDraft = this.savedItem(article.id)?.note || "";
		this.state.noteStatus = "";
	}

	showStory(index: number): void {
		const article = this.activeList()[index];
		if (!article) return;
		this.state.open = index;
		this.state.profile = {
			...this.state.profile,
			viewed: [
				...this.state.profile.viewed.filter((id) => id !== article.id),
				article.id,
			].slice(-HISTORY_LIMIT),
		};
		this.saveProfile();
		this.renderStory(article);
		this.setReaderStatus("");
		this.state.focus = { kind: "story" };
		this.setReaderLive(
			`Story ${index + 1}: ${article.title}. ${storyDateLabel(article, this.formats)}.`,
		);
		this.emit();
		void this.loadRelated(article);
	}

	openStory(
		list: "feed" | "related",
		index: number,
		opener: HTMLElement | null = null,
	): void {
		const source = list === "related" ? this.state.related : this.state.items;
		if (!this.state.meta || !source[index]) return;
		// A related story opens a trail of its own, so Next stays within that related list.
		this.state.readerTrail = list === "related" ? source.slice() : null;
		if (!this.state.readerOpen) {
			this.state.readerOpen = true;
			this.opener = opener;
			try {
				window.history.pushState({ afterlineStory: true }, "");
				this.state.pushedHistory = true;
			} catch {
				this.state.pushedHistory = false;
			}
		}
		this.showStory(index);
	}

	closeStory(): void {
		if (!this.state.readerOpen) return;
		const pushed = this.state.pushedHistory;
		this.finishClose();
		if (pushed) {
			// Drop the story's history entry so Back leaves the page next time; its popstate is ignored.
			this.ignoredPops += 1;
			window.history.back();
		}
	}

	private finishClose(): void {
		if (!this.state.readerOpen) return;
		this.persistNote();
		this.state.noteFor = "";
		this.stopRelated();
		this.state.readerOpen = false;
		this.state.pushedHistory = false;
		this.state.readerTrail = null;
		this.state.open = -1;
		this.state.related = [];
		const opener = this.opener;
		this.opener = null;
		let focusIndex = -1;
		let rebuilt = false;
		// Not-interested stories leave the page once the reader is closed; a daily edition stays fixed.
		if (!this.isEdition()) {
			const disliked = new Set(this.state.profile.disliked);
			const kept = this.state.items.filter((item) => !disliked.has(item.id));
			if (kept.length !== this.state.items.length) {
				// The Go reader rebuilt the grid here, so focus moved to the opener's story
				// tile, or the next story kept after it, never to the old button.
				rebuilt = true;
				const openerIndex =
					opener?.dataset.open === "feed" ? Number(opener.dataset.index) : -1;
				if (openerIndex >= 0 && kept.length) {
					focusIndex = Math.min(
						this.state.items
							.slice(0, openerIndex)
							.filter((item) => !disliked.has(item.id)).length,
						kept.length - 1,
					);
				}
				this.state.items = kept;
				if (!kept.length && !this.state.loading) {
					this.state.feedback = {
						kind: "empty",
						title: "Nothing left on this page.",
						message: this.state.stale
							? "Every story here is marked not interested. Update the page for your new choices, or try another thread or view."
							: "Every story here is marked not interested. Show all stories, or try another thread or view.",
					};
				}
			}
		}
		this.state.focus = {
			kind: "after-close",
			opener: rebuilt ? null : opener,
			index: focusIndex,
		};
		this.emit();
	}

	onPopState = (): void => {
		if (this.ignoredPops > 0) {
			this.ignoredPops -= 1;
			return;
		}
		if (!this.state.readerOpen) return;
		this.state.pushedHistory = false;
		this.finishClose();
	};

	async loadRelated(article: Article): Promise<void> {
		const meta = this.state.meta;
		if (!meta) return;
		this.stopRelated();
		const version = this.relatedVersion;
		const controller = new AbortController();
		this.relatedController = controller;
		this.state.related = [];
		this.state.relatedStatus = "Finding related reading…";
		this.emit();
		const body = this.relatedBody(article);
		try {
			const raw = await this.request(
				"/api/v1/recommendations",
				controller,
				body,
			);
			if (version !== this.relatedVersion) return;
			const response = normaliseResponse(raw, meta.snapshot_id, body.method);
			const disliked = new Set(this.state.profile.disliked);
			this.state.related = response.items
				.filter((item) => item.id !== article.id && !disliked.has(item.id))
				.slice(0, RELATED_SIZE);
			this.state.relatedStatus = this.state.related.length
				? ""
				: "No related stories were found for this one. Another lens may find some.";
			this.emit();
		} catch (error) {
			if (version !== this.relatedVersion) return;
			this.state.relatedStatus = `Related reading is unavailable. ${errorMessage(error) || "Please try again."}`;
			this.emit();
		} finally {
			if (version === this.relatedVersion) this.relatedController = null;
		}
	}

	async nextStory(): Promise<void> {
		if (!this.canNext()) return;
		if (this.state.open < this.activeList().length - 1) {
			this.showStory(this.state.open + 1);
			return;
		}
		const before = this.state.items.length;
		const position = this.state.open;
		this.setReaderStatus("Loading more stories…");
		this.emit();
		await this.loadFeed(false);
		if (
			!this.state.readerOpen ||
			this.state.readerTrail ||
			this.state.open !== position
		)
			return;
		if (this.state.items.length > before) {
			this.showStory(before);
			return;
		}
		this.setReaderStatus(
			this.state.feedback?.kind === "error"
				? this.state.feedback.message
				: "That’s everything in this selection.",
		);
		this.emit();
	}

	previousStory(): void {
		if (this.canPrevious()) this.showStory(this.state.open - 1);
	}

	changePreference(kind: "liked" | "disliked"): void {
		const article = this.currentArticle();
		if (!article) return;
		const opposite = kind === "liked" ? "disliked" : "liked";
		const profile = this.state.profile;
		const hadPreference = profile[kind].includes(article.id);
		let chosen = profile[kind].filter((id) => id !== article.id);
		if (!hadPreference)
			chosen = [...chosen, article.id].slice(-PREFERENCE_LIMIT);
		const next = { ...profile };
		next[kind] = chosen;
		next[opposite] = profile[opposite].filter((id) => id !== article.id);
		this.state.profile = next;
		// A daily edition is one fixed page: choices shape the Fresh feed and the next edition, not this one.
		const edition = this.isEdition();
		if (!edition && !this.state.seed) this.state.stale = true;
		this.saveProfile();
		let done = "Choice removed.";
		if (!hadPreference)
			done = kind === "liked" ? "Interest added." : "Marked not interested.";
		let text = `${done} Back on the stories, “Update for your new choices” re-ranks them.`;
		if (edition) {
			text = `${done} This edition stays as it is; your choice shapes the Fresh feed and the next edition.`;
		} else if (!hadPreference && kind === "disliked") {
			text = `${done} It leaves the page when you close this story.`;
		} else if (this.state.seed) {
			text = `${done} It shapes your next selection.`;
		}
		this.announce(text);
		this.emit();
	}

	private scrollToFeed(): void {
		if (!(window.scrollY > 0) || typeof window.scrollTo !== "function") return;
		const still =
			typeof window.matchMedia === "function" &&
			window.matchMedia("(prefers-reduced-motion: reduce)").matches;
		window.scrollTo({ top: 0, behavior: still ? "auto" : "smooth" });
	}

	showRelatedFeed(): void {
		const article = this.currentArticle();
		if (!article) return;
		this.state.seed = article.id;
		this.state.seedTitle = article.title;
		this.state.topic = "";
		this.opener = null;
		this.closeStory();
		void this.loadFeed(true);
	}

	exploreAll(): void {
		if (!this.state.meta) return;
		this.state.topic = "";
		this.state.seed = "";
		this.state.seedTitle = "";
		void this.loadFeed(true);
	}

	skipOnboarding(): void {
		this.state.profile = { ...this.state.profile, onboarded: true };
		this.saveProfile();
		if (this.state.tasteOpen) this.closeTaste();
		this.state.focus = { kind: "edit-interests" };
		this.announce(
			"No new interests added. You can choose them any time; opening a story never adds one.",
		);
		this.emit();
	}

	// ---- The feed -------------------------------------------------------

	private renderServiceNote(response: Selection): void {
		const notes: string[] = [];
		const unavailable = response.unavailable_ids;
		if (Array.isArray(unavailable) && unavailable.length) {
			notes.push(
				`${unavailable.length} saved or seed article references were not found in this snapshot.`,
			);
		}
		const ignored = response.ignored_viewed_ids;
		if (
			typeof ignored === "number" &&
			Number.isSafeInteger(ignored) &&
			ignored > 0
		) {
			notes.push(
				`${ignored} viewed references were ignored by the service; local coverage may differ.`,
			);
		}
		this.state.serviceNote = notes.join(" ");
	}

	private emptyFeedback(edition: boolean): { title: string; message: string } {
		if (edition) {
			return {
				title: "No edition for this selection.",
				message: `No stories with a verified date from ${this.editionDate()} (${this.zoneName()}) match this selection. Try Fresh, another thread, or switch off Professional focus.`,
			};
		}
		if (!this.state.seed && this.state.view === "fresh") {
			return {
				title: "Nothing fresh here yet.",
				message:
					"No unseen stories from the last 30 days match this selection. Try the archive, another thread, or switch off Professional focus.",
			};
		}
		return {
			title: "Room for a different thread.",
			message:
				"No unseen articles were returned for this selection. Try another thread or lens, choose interests, or reset your local history to revisit archived stories.",
		};
	}

	async loadFeed(replace = false): Promise<void> {
		const meta = this.state.meta;
		if (!meta) return;
		this.stopFeed();
		const version = this.feedVersion;
		const controller = new AbortController();
		this.feedController = controller;
		if (replace) {
			// The like/dislike hint points at the update button; once the stories reload it no longer applies.
			if (this.state.stale)
				this.announce("Updating the stories for your choices.");
			this.state.items = [];
			this.state.exhausted = false;
			this.state.stale = false;
			this.scrollToFeed();
		}
		this.state.loading = true;
		this.state.endMessage = "";
		this.state.retryKind = "feed";
		this.state.retryReplace = replace;
		this.state.feedback = replace
			? {
					kind: "loading",
					title: "Finding your stories.",
					message:
						"Using article content and your explicit choices. Stories you have opened are left out.",
				}
			: {
					kind: "loading",
					title: "Finding more stories.",
					message:
						"Stories already on this page and stories you have opened are left out.",
				};
		this.state.serviceNote = "";
		this.emit();
		const body = this.bodyFor();
		try {
			const raw = await this.request(
				"/api/v1/recommendations",
				controller,
				body,
			);
			if (version !== this.feedVersion) return;
			const response = normaliseResponse(raw, meta.snapshot_id, body.method);
			const edition = body.window === "yesterday" && !body.seed_id;
			if (
				edition &&
				typeof response.edition_date === "string" &&
				this.state.meta
			) {
				this.state.meta = {
					...this.state.meta,
					edition_date: response.edition_date,
				};
			}
			const { state } = this;
			const excluded = new Set([
				...(edition ? [] : state.profile.viewed),
				...state.profile.disliked,
				...state.items.map((item) => item.id),
			]);
			if (state.seed) excluded.add(state.seed);
			const items = response.items.filter((item) => !excluded.has(item.id));
			if (
				!state.seed &&
				!state.topic &&
				!state.profile.liked.length &&
				!state.exploreCache
			) {
				state.exploreCache = items.slice(0, EXPLORE_SIZE);
			}
			const start = state.items.length;
			state.items = [...state.items, ...items];
			// A filtered-empty batch pauses for a human choice instead of refetching in a loop; an edition is one fixed page.
			state.exhausted = edition || response.exhausted === true || !items.length;
			state.feedback = null;
			this.renderServiceNote(response);
			const stories = items.length === 1 ? "story" : "stories";
			if (items.length) {
				if (edition) {
					state.endMessage = `That’s yesterday’s edition: ${items.length} ${stories} published on ${this.editionDate()} (${this.zoneName()}).${items.length < EDITION_SIZE ? ` Only ${items.length} matched this selection.` : ""} Switch to Fresh for today’s news.`;
				}
				this.setReaderLive(
					`${items.length} ${start ? "more " : ""}${stories} loaded.`,
				);
			} else if (!state.items.length) {
				state.feedback = { kind: "empty", ...this.emptyFeedback(edition) };
				this.setReaderLive(
					"No unseen stories were returned for this selection.",
				);
			} else {
				state.endMessage =
					"No more unseen stories were returned. Try another thread or lens, or reset local history to revisit the collection.";
				this.setReaderLive("No more unseen stories in this selection.");
			}
		} catch (error) {
			if (version !== this.feedVersion) return;
			if (error instanceof ReaderError && error.reloadMetadata) {
				this.state.retryKind = "meta";
			}
			const text =
				errorMessage(error) || "Could not load recommendations. Please retry.";
			this.state.feedback = {
				kind: "error",
				title: "The archive needs a moment.",
				message: text,
			};
			this.setReaderLive(`Recommendations unavailable. ${text}`);
		} finally {
			if (version === this.feedVersion) {
				this.state.loading = false;
				this.feedController = null;
				this.emit();
			}
		}
	}

	async loadMetadata(): Promise<void> {
		this.metaVersion += 1;
		const version = this.metaVersion;
		this.metaController?.abort();
		this.stopFeed();
		this.stopTaste();
		this.state.tasteOpen = false;
		const controller = new AbortController();
		this.metaController = controller;
		this.state.meta = null;
		this.state.items = [];
		this.state.exhausted = false;
		this.state.stale = false;
		this.state.exploreCache = null;
		this.state.loading = true;
		this.state.retryKind = "meta";
		this.state.feedback = {
			kind: "loading",
			title: "Opening the stories.",
			message:
				"Loading the snapshot, its dates, and its content groups. No sample stories are used.",
		};
		this.emit();
		try {
			const raw = await this.request(
				"/api/v1/recommendations/meta",
				controller,
			);
			if (version !== this.metaVersion) return;
			const meta = normaliseMetadata(raw);
			this.state.meta = meta;
			if (
				!isMethod(this.state.method) ||
				!meta.methods.includes(this.state.method)
			) {
				this.state.method = meta.default_method;
			}
			if (!meta.topics.some((topic) => topic.id === this.state.topic)) {
				this.state.topic = "";
			}
			const storageKey = `${PROFILE_PREFIX}${meta.snapshot_id}`;
			if (storageKey !== this.state.storageKey) {
				this.state.storageKey = storageKey;
				this.state.profile = this.readProfile();
			}
			this.buildTopics(meta);
			this.renderMetadata(meta);
			await this.loadFeed(true);
		} catch (error) {
			if (version !== this.metaVersion) return;
			this.state.loading = false;
			const text =
				errorMessage(error) ||
				"Archive information is unavailable. Please retry.";
			this.state.feedback = {
				kind: "error",
				title: "No archive connection.",
				message: text,
			};
			this.state.topicStatus =
				"Archive topics are unavailable until the recommendation service connects.";
			this.setReaderLive(text);
			this.emit();
		} finally {
			if (version === this.metaVersion) this.metaController = null;
		}
	}

	loadMore(): void {
		void this.loadFeed(false);
	}

	refresh(): void {
		void this.loadFeed(true);
	}

	retry(): void {
		if (this.state.retryKind === "meta") void this.loadMetadata();
		else void this.loadFeed(this.state.retryReplace);
	}

	changeView(view: View): void {
		if (
			!this.state.meta ||
			!Object.hasOwn(VIEWS, view) ||
			(view === this.state.view && !this.state.seed)
		)
			return;
		this.state.view = view;
		this.state.seed = "";
		this.state.seedTitle = "";
		this.state.exploreCache = null;
		void this.loadFeed(true);
	}

	selectTopic(topic: string): void {
		if (!this.state.meta) return;
		this.state.topic = topic;
		this.state.seed = "";
		this.state.seedTitle = "";
		void this.loadFeed(true);
	}

	changeMethod(value: string): void {
		if (!isMethod(value) || !this.state.meta?.methods.includes(value)) return;
		this.state.method = value;
		void this.loadFeed(true);
	}

	setProfessional(professional: boolean): void {
		if (!this.state.meta) return;
		this.state.professional = professional;
		this.saveSettings();
		this.state.exploreCache = null;
		void this.loadFeed(true);
	}

	// ---- Choosing interests ---------------------------------------------

	private renderTaste(items: Article[]): void {
		this.state.tasteItems = items;
		this.state.tasteReload = false;
		this.state.tasteStatus = "ready";
		this.state.tasteError = "";
	}

	async loadExplore(): Promise<void> {
		const meta = this.state.meta;
		if (!meta) return;
		this.stopTaste();
		const version = this.tasteVersion;
		const controller = new AbortController();
		this.tasteController = controller;
		this.state.tasteLoading = true;
		this.state.tasteReload = false;
		this.state.selected = [];
		this.state.tasteItems = [];
		this.state.tasteStatus = "loading";
		this.state.tasteError = "";
		this.emit();
		const body = this.bodyFor(true);
		try {
			const raw = await this.request(
				"/api/v1/recommendations",
				controller,
				body,
			);
			if (version !== this.tasteVersion || !this.state.tasteOpen) return;
			const response = normaliseResponse(raw, meta.snapshot_id, body.method);
			const excluded = new Set([
				...this.state.profile.viewed,
				...this.state.profile.disliked,
			]);
			this.state.exploreCache = response.items.filter(
				(item) => !excluded.has(item.id),
			);
			this.renderTaste(this.state.exploreCache);
		} catch (error) {
			if (version !== this.tasteVersion || !this.state.tasteOpen) return;
			this.state.tasteStatus = "error";
			this.state.tasteError =
				errorMessage(error) ||
				"Could not load Explore. Retry, or skip for now.";
			this.state.tasteReload =
				error instanceof ReaderError && error.reloadMetadata;
		} finally {
			if (version === this.tasteVersion) {
				this.state.tasteLoading = false;
				this.tasteController = null;
				this.emit();
			}
		}
	}

	openTaste(): void {
		if (!this.state.meta || this.state.loading || this.state.tasteOpen) return;
		this.state.selected = [];
		this.state.tasteOpen = true;
		const disliked = this.state.profile.disliked;
		const cached = this.state.exploreCache?.filter(
			(item) => !disliked.includes(item.id),
		);
		if (cached?.length) {
			this.renderTaste(cached);
			this.emit();
		} else {
			void this.loadExplore();
		}
	}

	closeTaste(): void {
		this.stopTaste();
		this.state.tasteOpen = false;
		this.emit();
	}

	retryTaste(): void {
		if (this.state.tasteReload) {
			this.closeTaste();
			void this.loadMetadata();
		} else {
			void this.loadExplore();
		}
	}

	toggleTaste(id: string, checked: boolean): void {
		if (!this.state.tasteItems.some((item) => item.id === id)) return;
		if (checked && this.state.selected.length < TASTE_LIMIT) {
			if (!this.state.selected.includes(id)) {
				this.state.selected = [...this.state.selected, id];
			}
		} else {
			this.state.selected = this.state.selected.filter((value) => value !== id);
		}
		this.emit();
	}

	submitTaste(): void {
		if (this.state.tasteLoading || this.state.tasteStatus !== "ready") return;
		const selected = this.state.selected
			.filter((id) => this.state.tasteItems.some((item) => item.id === id))
			.slice(0, TASTE_LIMIT);
		const profile = this.state.profile;
		this.state.profile = {
			...profile,
			liked: [
				...profile.liked.filter((id) => !selected.includes(id)),
				...selected,
			].slice(-PREFERENCE_LIMIT),
			disliked: profile.disliked.filter((id) => !selected.includes(id)),
			onboarded: true,
		};
		this.saveProfile();
		this.closeTaste();
		if (selected.length) {
			this.announce(
				`${selected.length} ${selected.length === 1 ? "interest" : "interests"} added. Opening a new selection using your choices.`,
			);
			this.exploreAll();
			this.state.focus = { kind: "panel" };
		} else {
			this.state.focus = { kind: "edit-interests" };
			this.announce(
				"Exploring without new interests. You can add them any time.",
			);
		}
		this.emit();
	}

	// ---- Saved stories and reset dialogs --------------------------------

	openSaved(): void {
		if (this.state.savedOpen) return;
		this.state.savedOpen = true;
		this.emit();
	}

	closeSaved(): void {
		this.state.savedOpen = false;
		this.emit();
	}

	openReset(): void {
		if (!this.state.meta || this.state.loading) return;
		this.state.resetOpen = true;
		this.emit();
	}

	closeReset(): void {
		this.state.resetOpen = false;
		this.emit();
	}

	reset(): void {
		this.stopFeed();
		this.stopTaste();
		this.state.profile = emptyProfile();
		this.state.exploreCache = null;
		this.saveProfile();
		this.state.resetOpen = false;
		this.announce(
			"Interests and viewed history cleared for this snapshot. Newly opened stories start a fresh history.",
		);
		this.exploreAll();
		this.state.focus = { kind: "panel" };
		this.emit();
	}

	// ---- Start and stop -------------------------------------------------

	start(): void {
		if (this.started) return;
		this.started = true;
		const settings = this.readSettings();
		this.state.saved = this.readSaved();
		this.state.professional = settings.professional;
		this.state.theme = settings.theme;
		this.darkQuery =
			typeof window.matchMedia === "function"
				? window.matchMedia("(prefers-color-scheme: dark)")
				: null;
		this.state.systemDark = Boolean(this.darkQuery?.matches);
		this.applyTheme();
		this.darkQuery?.addEventListener?.("change", this.onDarkChange);
		const article = new URL(window.location.href).searchParams.get("article");
		if (article && UUID.test(article)) this.state.seed = article.toLowerCase();
		else if (article) {
			this.state.linkNote =
				"That article link is not a valid archive ID. Exploring the collection instead.";
		}
		window.addEventListener("popstate", this.onPopState);
		// Closing the reader steps Back in history; restoring that entry's old scroll position would undo scrollToFeed.
		if ("scrollRestoration" in window.history) {
			window.history.scrollRestoration = "manual";
		}
		void this.loadMetadata();
	}

	dispose(): void {
		if (!this.started) return;
		this.started = false;
		this.metaVersion += 1;
		this.metaController?.abort();
		this.metaController = null;
		this.stopFeed();
		this.stopTaste();
		this.stopRelated();
		this.darkQuery?.removeEventListener?.("change", this.onDarkChange);
		window.removeEventListener("popstate", this.onPopState);
	}
}
