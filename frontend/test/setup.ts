import { cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, vi } from "vitest";

// React checks this flag to know it runs inside tests that wrap updates in act().
Object.assign(globalThis, { IS_REACT_ACT_ENVIRONMENT: true });

// jsdom has no modal dialogs. This stand-in covers what the app uses; like a
// browser, it fires "close" as a separate task.
if (typeof HTMLDialogElement.prototype.showModal !== "function") {
	HTMLDialogElement.prototype.showModal = function showModal(
		this: HTMLDialogElement,
	) {
		if (this.open) {
			throw new DOMException(
				"The dialog is already open.",
				"InvalidStateError",
			);
		}
		this.setAttribute("open", "");
	};
	HTMLDialogElement.prototype.close = function close(this: HTMLDialogElement) {
		if (!this.open) return;
		this.removeAttribute("open");
		setTimeout(() => this.dispatchEvent(new Event("close")), 0);
	};
}

let consoleError: ReturnType<typeof vi.spyOn>;

beforeEach(() => {
	// React reports missing act() wrappers and bad markup through console.error.
	consoleError = vi.spyOn(console, "error");
});

afterEach(() => {
	cleanup();
	localStorage.clear();
	document.documentElement.removeAttribute("data-theme");
	window.history.replaceState(null, "", "/");
	expect(consoleError).not.toHaveBeenCalled();
});
