import { ZONE_NAMES } from "./constants";
import { articleDate, dateValue } from "./normalise";
import type { Article, Meta } from "./types";

export const countFormat = new Intl.NumberFormat("en-GB");

const editionFormat = new Intl.DateTimeFormat("en-GB", {
	weekday: "long",
	day: "numeric",
	month: "long",
	timeZone: "UTC",
});

export interface DateFormats {
	timeZone: string;
	fullDate: Intl.DateTimeFormat;
	shortDate: Intl.DateTimeFormat;
	dateTime: Intl.DateTimeFormat;
	dayFormat: Intl.DateTimeFormat;
}

// Throws for an unknown time zone, so the caller can keep its previous formats.
export function createFormats(timeZone: string): DateFormats {
	const format = (options: Intl.DateTimeFormatOptions) =>
		new Intl.DateTimeFormat("en-GB", { ...options, timeZone });
	return {
		timeZone,
		fullDate: format({ day: "numeric", month: "long", year: "numeric" }),
		shortDate: format({ day: "numeric", month: "short", year: "numeric" }),
		dateTime: format({
			day: "numeric",
			month: "long",
			year: "numeric",
			hour: "2-digit",
			minute: "2-digit",
		}),
		dayFormat: format({ weekday: "long", day: "numeric", month: "long" }),
	};
}

export function zoneName(timeZone: string): string {
	return Object.hasOwn(ZONE_NAMES, timeZone)
		? (ZONE_NAMES[timeZone] ?? timeZone)
		: timeZone;
}

export function editionDate(meta: Meta | null): string {
	const value =
		typeof meta?.edition_date === "string"
			? dateValue(`${meta.edition_date}T00:00:00Z`)
			: null;
	return value ? editionFormat.format(value) : "yesterday";
}

// A stable colour per publisher for the placeholder behind a missing picture.
export function hue(text: string): number {
	let value = 0;
	for (const character of String(text)) {
		value = (value * 31 + (character.codePointAt(0) ?? 0)) % 360;
	}
	return value;
}

export function clip(text: string, limit: number): string {
	if (text.length <= limit) return text;
	const boundary = text.lastIndexOf(" ", limit);
	return `${text.slice(0, boundary > limit * 0.6 ? boundary : limit).trimEnd()}…`;
}

export function shortDateLabel(article: Article, formats: DateFormats): string {
	const { date, label } = articleDate(article);
	const when = date
		? `${label === "Collected" ? "Collected " : ""}${formats.shortDate.format(date)}`
		: "Date unavailable";
	return `${when}${article.date_verified === false ? " · date unverified" : ""}`;
}

export function storyDateLabel(article: Article, formats: DateFormats): string {
	const { date, label } = articleDate(article);
	const unverified =
		article.date_verified === false ? " · date unverified" : "";
	return date
		? `${label} ${formats.fullDate.format(date)}${unverified}`
		: "Stored date unavailable";
}

export const HEADLINE_ONLY_TEXT =
	"Only the headline is stored for this story. Open the original for more context; the external page may have changed.";

// Long stored text opens with about 650 characters; the rest sits behind "Continue".
export function splitStoryText(article: Article): {
	lead: string;
	rest: string;
	more: boolean;
} {
	const text =
		article.text_kind === "Headline only" ? HEADLINE_ONLY_TEXT : article.text;
	let split = text.length;
	if (text.length > 760) {
		const boundary = text.lastIndexOf(" ", 650);
		split = boundary > 400 ? boundary : 650;
	}
	return {
		lead: text.slice(0, split).trim(),
		rest: text.slice(split).trim(),
		more: split !== text.length,
	};
}
