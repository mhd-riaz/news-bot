import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, test } from "vitest";
import { App } from "../src/App";
import {
	$,
	article,
	FakeServer,
	id,
	renderReader,
	response,
	selection,
} from "./harness";

const SIGNED_OUT = {
	auth_enabled: true,
	signed_in: false,
	reader: null,
	login_url: "/auth/google/login",
};

const SIGNED_IN = {
	auth_enabled: true,
	signed_in: true,
	reader: { email: "reader@example.com", name: "Asha" },
	login_url: "/auth/google/login",
};

describe("sign-in", () => {
	test("with sign-in on and nobody signed in, only the sign-in screen shows", async () => {
		const server = new FakeServer();
		server.session = SIGNED_OUT;
		window.history.replaceState(null, "", `/stories?article=${id(3)}`);
		render(<App />);
		const link = await screen.findByRole("link", {
			name: "Sign in with Google",
		});
		expect(link.getAttribute("href")).toBe(
			`/auth/google/login?next=${encodeURIComponent(`/stories?article=${id(3)}`)}`,
		);
		expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
			"Sign in to read",
		);
		expect(document.title).toBe("Sign in · AFTERLINE");
		expect(screen.queryByRole("alert")).toBe(null);
		expect(server.calls.map((call) => call.path)).toEqual(["/api/v1/session"]);
		expect(server.calls[0]?.init).toMatchObject({ credentials: "same-origin" });
		expect(document.getElementById("reader-panel")).toBe(null);
	});

	test("an email that is not invited is explained, and the error stays out of the return path", async () => {
		const server = new FakeServer();
		server.session = SIGNED_OUT;
		window.history.replaceState(null, "", "/?auth_error=not_invited");
		render(<App />);
		const alert = await screen.findByRole("alert");
		expect(alert.textContent).toMatch(/not on the invite list/);
		expect(
			screen
				.getByRole("link", { name: "Sign in with Google" })
				.getAttribute("href"),
		).toBe("/auth/google/login?next=%2F");
	});

	test("a failed sign-in says so and offers to try again", async () => {
		const server = new FakeServer();
		server.session = {
			...SIGNED_OUT,
			login_url: "/auth/google/login?prompt=select_account",
		};
		window.history.replaceState(null, "", "/stories?auth_error=sign_in_failed");
		render(<App />);
		expect((await screen.findByRole("alert")).textContent).toBe(
			"Sign-in failed. Please try again.",
		);
		expect(
			screen
				.getByRole("link", { name: "Try again with Google" })
				.getAttribute("href"),
		).toBe("/auth/google/login?prompt=select_account&next=%2Fstories");
	});

	test("a sign-in link that leaves the site is replaced by the standard one", async () => {
		const server = new FakeServer();
		server.session = { ...SIGNED_OUT, login_url: "//evil.example/login" };
		render(<App />);
		const link = await screen.findByRole("link", {
			name: "Sign in with Google",
		});
		expect(link.getAttribute("href")).toBe("/auth/google/login?next=%2F");
	});

	test("a signed-in reader sees their name and can sign out", async () => {
		const server = new FakeServer();
		server.session = SIGNED_IN;
		server.serve(selection([article(1)]));
		const { user } = await renderReader();
		expect(screen.getByText("Asha").getAttribute("title")).toBe(
			"reader@example.com",
		);
		await user.click(screen.getByRole("button", { name: "Sign out" }));
		const status = await screen.findByRole("status");
		expect(status.textContent).toBe("You are signed out.");
		const logout = server.calls.find((call) => call.path === "/auth/logout");
		expect(logout?.init).toMatchObject({
			method: "POST",
			credentials: "same-origin",
		});
		expect(logout?.init.body).toBeUndefined();
		expect(document.activeElement).toBe(
			screen.getByRole("heading", { level: 1 }),
		);
		expect(document.getElementById("reader-panel")).toBe(null);
	});

	test("a failed sign-out keeps the reader open and says why", async () => {
		const server = new FakeServer();
		server.session = SIGNED_IN;
		server.serve(selection([article(1)]));
		server.logout = () => response({}, 500);
		const { user } = await renderReader();
		await user.click(screen.getByRole("button", { name: "Sign out" }));
		await waitFor(() =>
			expect($("action-status").textContent).toBe(
				"Sign-out failed (HTTP 500). Please try again.",
			),
		);
		expect(
			screen.getByRole<HTMLButtonElement>("button", { name: "Sign out" })
				.disabled,
		).toBe(false);
	});

	test("without sign-in there are no account controls", async () => {
		new FakeServer().serve(selection([article(1)]));
		await renderReader();
		expect(screen.queryByRole("button", { name: "Sign out" })).toBe(null);
	});

	test("an ended session returns to the sign-in screen", async () => {
		const server = new FakeServer();
		server.session = SIGNED_IN;
		server.meta = () =>
			response(
				{
					error: { code: "sign_in_required", message: "Sign in to continue." },
				},
				401,
			);
		render(<App />);
		const status = await screen.findByRole("status");
		expect(status.textContent).toBe(
			"Your sign-in has ended. Sign in again to keep reading.",
		);
		expect(screen.getByRole("link", { name: "Sign in with Google" })).not.toBe(
			null,
		);
		expect(document.getElementById("reader-panel")).toBe(null);
	});

	test("a failed sign-in check can be tried again", async () => {
		const server = new FakeServer();
		server.sessionAnswer = () => response({}, 503);
		server.serve(selection([article(1)]));
		const user = userEvent.setup();
		render(<App />);
		const alert = await screen.findByRole("alert");
		expect(alert.textContent).toBe(
			"The reader is unavailable right now. Please try again in a moment.",
		);
		expect(screen.getByRole("heading", { level: 1 }).textContent).toBe(
			"The reader is not answering.",
		);
		server.sessionAnswer = () => response(server.session);
		await user.click(screen.getByRole("button", { name: "Try again" }));
		await waitFor(() =>
			expect($("reader-panel").getAttribute("aria-busy")).toBe("false"),
		);
	});
});
