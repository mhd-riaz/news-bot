import { REQUEST_TIMEOUT_MS } from "./reader/constants";
import { isRecord } from "./reader/normalise";

// Every request is same-origin JSON. The browser's own Origin and Sec-Fetch-Site
// headers are the server's CSRF check, so no token is sent.

export class ApiError extends Error {
	readonly status: number;
	readonly code: string;

	constructor(message: string, status: number, code: string) {
		super(message);
		this.name = "ApiError";
		this.status = status;
		this.code = code;
	}

	get signInRequired(): boolean {
		return this.status === 401 && this.code === "sign_in_required";
	}
}

interface Messages {
	unreadable: string;
	unavailable: string;
	failed: (status: number) => string;
	timeout: string;
	offline: string;
}

// The Go reader's wording, kept so readers see the same messages.
const RECOMMENDATION_MESSAGES: Messages = {
	unreadable:
		"The recommendation service did not return readable JSON. Please retry.",
	unavailable:
		"The recommendation service is unavailable. No replacement or sample stories are shown.",
	failed: (status) =>
		`The archive request failed (HTTP ${status}). Please retry.`,
	timeout:
		"The archive took too long to respond. Please retry when the recommendation service is ready.",
	offline:
		"Could not reach the recommendation service. Check your connection, then retry.",
};

const SESSION_MESSAGES: Messages = {
	unreadable:
		"The sign-in check did not return readable JSON. Please try again.",
	unavailable:
		"The reader is unavailable right now. Please try again in a moment.",
	failed: (status) =>
		`The sign-in check failed (HTTP ${status}). Please try again.`,
	timeout: "The sign-in check took too long. Please try again.",
	offline: "Could not reach the reader. Check your connection, then try again.",
};

export async function requestJSON(
	path: string,
	controller: AbortController,
	body?: unknown,
	messages: Messages = RECOMMENDATION_MESSAGES,
): Promise<unknown> {
	let timedOut = false;
	const timeout = window.setTimeout(() => {
		timedOut = true;
		controller.abort();
	}, REQUEST_TIMEOUT_MS);
	try {
		const response = await fetch(path, {
			method: body ? "POST" : "GET",
			headers: body
				? { Accept: "application/json", "Content-Type": "application/json" }
				: { Accept: "application/json" },
			credentials: "same-origin",
			cache: "no-store",
			signal: controller.signal,
			...(body ? { body: JSON.stringify(body) } : {}),
		});
		let value: unknown;
		try {
			value = await response.json();
		} catch {
			throw new Error(messages.unreadable);
		}
		if (!response.ok) {
			const error = isRecord(value) && isRecord(value.error) ? value.error : {};
			const message = typeof error.message === "string" ? error.message : "";
			throw new ApiError(
				message ||
					(response.status === 503
						? messages.unavailable
						: messages.failed(response.status)),
				response.status,
				typeof error.code === "string" ? error.code : "",
			);
		}
		return value;
	} catch (error) {
		if (timedOut) throw new Error(messages.timeout);
		if (error instanceof TypeError) throw new Error(messages.offline);
		throw error;
	} finally {
		window.clearTimeout(timeout);
	}
}

export interface Account {
	email: string;
	name: string;
}

export interface Session {
	authEnabled: boolean;
	signedIn: boolean;
	reader: Account | null;
	loginUrl: string;
}

export const DEFAULT_LOGIN_URL = "/auth/login";

// Only a path on this site may be used as the sign-in link.
export function localPath(value: unknown): string {
	return typeof value === "string" && /^\/(?![/\\])/.test(value) ? value : "";
}

export function normaliseSession(value: unknown): Session {
	if (
		!isRecord(value) ||
		typeof value.auth_enabled !== "boolean" ||
		typeof value.signed_in !== "boolean"
	) {
		throw new Error(
			"The sign-in check returned an unreadable answer. Please try again.",
		);
	}
	const reader = isRecord(value.reader) ? value.reader : null;
	return {
		authEnabled: value.auth_enabled,
		signedIn: value.signed_in,
		reader: reader
			? {
					email: typeof reader.email === "string" ? reader.email : "",
					name: typeof reader.name === "string" ? reader.name : "",
				}
			: null,
		loginUrl: localPath(value.login_url) || DEFAULT_LOGIN_URL,
	};
}

export async function fetchSession(
	controller: AbortController,
): Promise<Session> {
	return normaliseSession(
		await requestJSON(
			"/api/v1/session",
			controller,
			undefined,
			SESSION_MESSAGES,
		),
	);
}

export async function signOut(): Promise<void> {
	let response: Response;
	try {
		response = await fetch("/auth/logout", {
			method: "POST",
			headers: { Accept: "application/json" },
			credentials: "same-origin",
			cache: "no-store",
		});
	} catch {
		throw new Error(
			"Could not reach the reader to sign out. Check your connection, then try again.",
		);
	}
	// 401 means the session had already ended, which is what signing out wants.
	if (!response.ok && response.status !== 401) {
		throw new Error(
			`Sign-out failed (HTTP ${response.status}). Please try again.`,
		);
	}
}

// The sign-in link brings the reader back to this page, without the old error.
export function signInHref(loginUrl: string, location: Location): string {
	const url = new URL(
		localPath(loginUrl) || DEFAULT_LOGIN_URL,
		location.origin,
	);
	const params = new URLSearchParams(location.search);
	params.delete("auth_error");
	const query = params.toString();
	url.searchParams.set(
		"next",
		`${location.pathname}${query ? `?${query}` : ""}`,
	);
	return `${url.pathname}${url.search}`;
}
