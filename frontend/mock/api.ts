import type { IncomingMessage, ServerResponse } from "node:http";
import type { Connect, Plugin } from "vite";

// A made-up API for trying the app without the Python server. It answers the
// same paths and shapes. Every story here is invented; no real article text.
//
// Change the scenario while it runs, for example:
//   /__mock?auth=on            sign-in required, starts signed out
//   /__mock?invite=deny        Google sign-in returns ?auth_error=not_invited
//   /__mock?invite=fail        Google sign-in returns ?auth_error=sign_in_failed
//   /__mock?auth=off           no sign-in (the default)

type Invite = "allow" | "deny" | "fail";

interface MockState {
	authEnabled: boolean;
	signedIn: boolean;
	invite: Invite;
}

interface Story {
	id: string;
	source_id: string;
	source_name: string;
	domains: string[];
	url: string;
	title: string;
	text: string;
	text_kind: string;
	input_kind: string;
	group: string;
	published_at: string;
	collected_at: string;
	date_kind: string;
	date_verified: boolean;
	fresh: boolean;
	yesterday: boolean;
}

const SNAPSHOT = "mock-snapshot-0001";
const METHODS = ["tfidf", "svd", "neural"];
const ZONE = "Asia/Kolkata";
const DAY = 86_400_000;

const SOURCES = [
	{ name: "Example Systems Weekly", domains: ["software"] },
	{ name: "Sample Data Journal", domains: ["data-science"] },
	{ name: "Placeholder AI Review", domains: ["ai"] },
	{ name: "Demo Tech Desk", domains: ["technology"] },
	{ name: "Mock City Bulletin", domains: [] },
	{ name: "Fictional Science Post", domains: [] },
];

const TOPICS = [
	{ id: "0", label: "models / training / data" },
	{ id: "1", label: "software / releases / tools" },
	{ id: "2", label: "city / transport / weather" },
	{ id: "3", label: "science / space / research" },
];

const SUBJECTS = [
	"A small team",
	"The city council",
	"A research group",
	"An open-source project",
	"A weather office",
	"A data lab",
];
const ACTIONS = [
	"tests a quieter way to",
	"publishes notes on how to",
	"explains why it chose to",
	"asks readers how to",
];
const THINGS = [
	"sort a busy inbox",
	"measure model drift",
	"plan a cheaper bus route",
	"keep old laptops useful",
	"read a noisy chart",
	"ship smaller releases",
];

function storyId(n: number): string {
	return `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
}

// The calendar date in India time, as YYYY-MM-DD.
function indiaDate(time: number): string {
	return new Intl.DateTimeFormat("en-CA", { timeZone: ZONE }).format(time);
}

function makeStories(now: number): { stories: Story[]; editionDate: string } {
	const editionDate = indiaDate(now - DAY);
	// 06:00 India time on the edition date, in UTC.
	const editionStart = Date.parse(`${editionDate}T00:30:00Z`);
	const stories: Story[] = [];
	for (let n = 1; n <= 160; n += 1) {
		const source = SOURCES[n % SOURCES.length] ?? SOURCES[0];
		const topic = TOPICS[(n * 7) % TOPICS.length] ?? TOPICS[0];
		const title = `${SUBJECTS[n % SUBJECTS.length]} ${ACTIONS[n % ACTIONS.length]} ${THINGS[(n * 5) % THINGS.length]} (mock story ${n})`;
		let published: number;
		if (n <= 12) published = editionStart + n * 45 * 60_000;
		else if (n <= 100) published = now - (n - 12) * 7 * 3_600_000;
		else published = now - (40 + n) * DAY;
		const verified = n % 17 !== 0;
		const headlineOnly = n % 11 === 0;
		const sentence = `This is made-up text for mock story ${n}, written only to try the reader. It is not a real article and says nothing true.`;
		const text = headlineOnly
			? ""
			: n % 5 === 0
				? sentence.repeat(9)
				: sentence;
		const age = now - published;
		stories.push({
			id: storyId(n),
			source_id: `mock-source-${n % SOURCES.length}`,
			source_name: source?.name ?? "Mock source",
			domains: source?.domains ?? [],
			url: `https://example.com/mock-story-${n}`,
			title,
			text,
			text_kind: headlineOnly
				? "Headline only"
				: n % 3
					? "Stored summary"
					: "Excerpt",
			input_kind: headlineOnly ? "headline" : "summary",
			group: topic?.id ?? "0",
			published_at: new Date(published).toISOString(),
			collected_at: new Date(published + 3_600_000).toISOString(),
			date_kind: verified ? "Stored publication date" : "Collected",
			date_verified: verified,
			fresh: verified && age <= 30 * DAY,
			yesterday: verified && indiaDate(published) === editionDate,
		});
	}
	return { stories, editionDate };
}

function send(
	res: ServerResponse,
	status: number,
	body?: unknown,
	headers: Record<string, string> = {},
): void {
	res.statusCode = status;
	for (const [name, value] of Object.entries(headers))
		res.setHeader(name, value);
	if (body === undefined) {
		res.end();
		return;
	}
	res.setHeader("Content-Type", "application/json; charset=utf-8");
	res.setHeader("Cache-Control", "no-store");
	res.end(JSON.stringify(body));
}

function fail(
	res: ServerResponse,
	status: number,
	code: string,
	message: string,
): void {
	send(res, status, { error: { code, message } });
}

async function readJSON(req: IncomingMessage): Promise<unknown> {
	let size = 0;
	const chunks: Buffer[] = [];
	for await (const chunk of req) {
		const buffer = Buffer.isBuffer(chunk) ? chunk : Buffer.from(String(chunk));
		size += buffer.length;
		if (size > 128 * 1024) throw new Error("body too large");
		chunks.push(buffer);
	}
	return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function isRecord(value: unknown): value is Record<string, unknown> {
	return typeof value === "object" && value !== null;
}

function strings(value: unknown): string[] {
	return Array.isArray(value)
		? value.filter((item): item is string => typeof item === "string")
		: [];
}

// The browser's own headers say whether a request came from this site.
function sameSite(req: IncomingMessage): boolean {
	const site = req.headers["sec-fetch-site"];
	return site === undefined || site === "same-origin";
}

function storyResponse(story: Story, score: number, reason: string) {
	return {
		id: story.id,
		source_id: story.source_id,
		source_name: story.source_name,
		url: story.url,
		title: story.title,
		language: "en",
		country: "",
		published_at: story.published_at,
		collected_at: story.collected_at,
		score,
		reason,
		text: story.text,
		text_kind: story.text_kind,
		input_kind: story.input_kind,
		group: story.group,
		date_kind: story.date_kind,
		date_verified: story.date_verified,
		fresh: story.fresh,
	};
}

// Each lens orders the same stories differently, so switching is visible.
function lensOrder(method: string, story: Story): number {
	const n = Number.parseInt(story.id.slice(-12), 16);
	if (method === "svd") return (n * 37) % 101;
	if (method === "neural") return (n * 53) % 97;
	return -Date.parse(story.published_at);
}

function recommend(
	body: Record<string, unknown>,
	stories: Story[],
	editionDate: string,
): { status: number; payload: unknown } {
	const method =
		typeof body.method === "string" && body.method ? body.method : "tfidf";
	const limit = typeof body.limit === "number" ? body.limit : 25;
	if (!METHODS.includes(method) || limit < 0 || limit > 30) {
		return {
			status: 400,
			payload: {
				error: {
					code: "invalid_input",
					message:
						"Choose valid interests, a known method and at most 30 results.",
				},
			},
		};
	}
	const liked = strings(body.liked);
	const excluded = new Set([
		...strings(body.viewed),
		...strings(body.disliked),
	]);
	const domains = strings(body.domains);
	const seedId = typeof body.seed_id === "string" ? body.seed_id : "";
	const window = typeof body.window === "string" ? body.window : "";
	const topic = typeof body.topic === "string" ? body.topic : "";
	const seed = seedId
		? stories.find((story) => story.id === seedId)
		: undefined;
	if (seedId && !seed) {
		return {
			status: 404,
			payload: {
				error: {
					code: "not_found",
					message:
						"An interest or article is outside this indexed archive. Reset your interests.",
				},
			},
		};
	}
	const likedTopics = new Set(
		stories
			.filter((story) => liked.includes(story.id))
			.map((story) => story.group),
	);
	let pool = stories.filter(
		(story) => !excluded.has(story.id) && story.id !== seedId,
	);
	// Related reading ignores the window, so older background can surface.
	if (!seed) {
		if (window === "fresh") pool = pool.filter((story) => story.fresh);
		else if (window === "yesterday")
			pool = pool.filter((story) => story.yesterday);
		else if (window === "archive") pool = pool.filter((story) => !story.fresh);
	}
	if (topic) pool = pool.filter((story) => story.group === topic);
	if (domains.length) {
		pool = pool.filter((story) =>
			story.domains.some((tag) => domains.includes(tag)),
		);
	}
	const closeness = (story: Story) => {
		if (seed) return story.group === seed.group ? 0 : 1;
		return likedTopics.has(story.group) ? 0 : 1;
	};
	pool.sort(
		(a, b) =>
			closeness(a) - closeness(b) ||
			lensOrder(method, a) - lensOrder(method, b),
	);
	const page = pool.slice(0, limit);
	let why = "Newest first, because no interests were chosen.";
	if (seed) why = "Mock ranking: shares a thread with the story you opened.";
	else if (liked.length)
		why = "Mock ranking: shares a thread with stories you like.";
	return {
		status: 200,
		payload: {
			items: page.map((story, index) =>
				storyResponse(story, Math.max(0, 0.92 - index * 0.013), why),
			),
			method,
			snapshot_id: SNAPSHOT,
			exhausted: pool.length <= limit,
			unavailable_ids: [],
			ignored_viewed_ids: 0,
			window: seed ? "" : window,
			...(window === "yesterday" && !seed ? { edition_date: editionDate } : {}),
		},
	};
}

function metadata(stories: Story[], editionDate: string, now: number) {
	const times = stories.map((story) => Date.parse(story.published_at));
	const count = (test: (story: Story) => boolean) =>
		stories.filter(test).length;
	const domains: Record<string, number> = {};
	for (const story of stories) {
		for (const tag of story.domains) domains[tag] = (domains[tag] ?? 0) + 1;
	}
	return {
		snapshot_id: SNAPSHOT,
		articles: stories.length,
		publication_range: [
			new Date(Math.min(...times)).toISOString(),
			new Date(Math.max(...times)).toISOString(),
		],
		collected_before: new Date(now).toISOString(),
		methods: METHODS,
		default_method: "tfidf",
		topics: TOPICS.map((topic) => ({
			...topic,
			keywords: topic.label.split(" / "),
			count: count((story) => story.group === topic.id),
			representatives: [],
		})),
		profile_note: "This is a made-up snapshot for trying the app.",
		date_note: "Dates are made up, counted back from when the mock started.",
		windows: {
			fresh: count((story) => story.fresh),
			yesterday: count((story) => story.yesterday),
			archive: count((story) => !story.fresh),
		},
		fresh_days: 30,
		edition_date: editionDate,
		edition_timezone: ZONE,
		domains,
	};
}

export function mockApi(): Plugin {
	const now = Date.now();
	const { stories, editionDate } = makeStories(now);
	const state: MockState = {
		authEnabled: process.env.MOCK_AUTH === "1",
		signedIn: false,
		invite: "allow",
	};

	const handle = async (
		req: IncomingMessage,
		res: ServerResponse,
	): Promise<boolean> => {
		const url = new URL(req.url ?? "/", "http://mock.invalid");
		const path = url.pathname;
		const locked = state.authEnabled && !state.signedIn;

		if (path === "/__mock") {
			const auth = url.searchParams.get("auth");
			if (auth === "on" || auth === "off") {
				state.authEnabled = auth === "on";
				state.signedIn = false;
			}
			const invite = url.searchParams.get("invite");
			if (invite === "allow" || invite === "deny" || invite === "fail")
				state.invite = invite;
			send(res, 200, state);
			return true;
		}
		if (path === "/health/live" || path === "/health/ready") {
			send(res, 200, { status: "ok" });
			return true;
		}
		if (path === "/api/v1/session" && req.method === "GET") {
			send(res, 200, {
				auth_enabled: state.authEnabled,
				signed_in: state.authEnabled && state.signedIn,
				reader:
					state.authEnabled && state.signedIn
						? { email: "reader@example.com", name: "Mock Reader" }
						: null,
				login_url: "/auth/login",
			});
			return true;
		}
		if (path === "/auth/login" && req.method === "GET") {
			if (state.invite !== "allow") {
				const code = state.invite === "deny" ? "not_invited" : "sign_in_failed";
				send(res, 302, undefined, { Location: `/?auth_error=${code}` });
				return true;
			}
			state.signedIn = true;
			const next = url.searchParams.get("next") ?? "/";
			const location = /^\/(?![/\\])/.test(next) ? next : "/";
			send(res, 302, undefined, { Location: location });
			return true;
		}
		if (path === "/auth/logout" && req.method === "POST") {
			if (!sameSite(req)) {
				fail(res, 403, "forbidden", "Cross-site requests are not accepted.");
				return true;
			}
			state.signedIn = false;
			send(res, 204);
			return true;
		}
		if (path.startsWith("/api/") && locked) {
			fail(res, 401, "sign_in_required", "Sign in to continue.");
			return true;
		}
		if (path === "/api/v1/recommendations/meta" && req.method === "GET") {
			send(res, 200, metadata(stories, editionDate, now));
			return true;
		}
		if (path === "/api/v1/recommendations" && req.method === "POST") {
			let body: unknown;
			try {
				body = await readJSON(req);
			} catch {
				fail(res, 400, "invalid_input", "The request was not valid JSON.");
				return true;
			}
			const result = recommend(
				isRecord(body) ? body : {},
				stories,
				editionDate,
			);
			// A short pause, so loading states can be seen.
			setTimeout(() => send(res, result.status, result.payload), 250);
			return true;
		}
		if (path.startsWith("/api/")) {
			fail(res, 404, "not_found", "The mock API has no such route.");
			return true;
		}
		return false;
	};

	const middleware: Connect.NextHandleFunction = (req, res, next) => {
		handle(req, res).then(
			(handled) => {
				if (!handled) next();
			},
			(error: unknown) => next(error),
		);
	};

	return {
		name: "afterline-mock-api",
		configureServer(server) {
			server.middlewares.use(middleware);
		},
		configurePreviewServer(server) {
			server.middlewares.use(middleware);
		},
	};
}
