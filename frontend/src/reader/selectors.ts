import { DOMAIN_TAG } from "./constants";
import { isRecord } from "./normalise";
import type { Article, Feedback, Meta } from "./types";

// Pure reads of reader state, shared by the store and the components.

interface ListState {
	readerOpen: boolean;
	readerTrail: Article[] | null;
	items: Article[];
	open: number;
	view: string;
	seed: string;
	exhausted: boolean;
	loading: boolean;
	feedback: Feedback | null;
}

export function activeList(state: ListState): Article[] {
	return state.readerTrail || state.items;
}

export function currentArticle(state: ListState): Article | null {
	return state.readerOpen ? (activeList(state)[state.open] ?? null) : null;
}

export function isEdition(state: Pick<ListState, "view" | "seed">): boolean {
	return state.view === "yesterday" && !state.seed;
}

export function canPrevious(state: ListState): boolean {
	return Boolean(currentArticle(state)) && state.open > 0;
}

export function canNext(state: ListState): boolean {
	if (!currentArticle(state)) return false;
	if (state.open < activeList(state).length - 1) return true;
	// Only the main feed grows from the reader; a related trail and a daily edition are fixed lists.
	return (
		!state.readerTrail &&
		!isEdition(state) &&
		!state.exhausted &&
		!state.loading &&
		state.feedback?.kind !== "error"
	);
}

export function isDark(state: { theme: string; systemDark: boolean }): boolean {
	return state.theme ? state.theme === "dark" : state.systemDark;
}

export function professionalDomains(meta: Meta | null): string[] {
	const domains = isRecord(meta?.domains) ? Object.keys(meta.domains) : [];
	return domains.filter((tag) => DOMAIN_TAG.test(tag)).slice(0, 8);
}
