import {
	createContext,
	type RefObject,
	useContext,
	useSyncExternalStore,
} from "react";
import type { ReaderState, ReaderStore } from "../reader/store";

// Elements the store asks to focus after a change, as the Go reader's page did.
export interface ReaderRefs {
	panel: RefObject<HTMLElement | null>;
	grid: RefObject<HTMLDivElement | null>;
	editInterests: RefObject<HTMLButtonElement | null>;
	storyDialog: RefObject<HTMLDialogElement | null>;
	storyTitle: RefObject<HTMLHeadingElement | null>;
}

export interface ReaderContextValue {
	store: ReaderStore;
	refs: ReaderRefs;
}

export const ReaderContext = createContext<ReaderContextValue | null>(null);

export function useReader(): ReaderContextValue & { state: ReaderState } {
	const context = useContext(ReaderContext);
	if (!context) throw new Error("useReader must be used inside <Reader>.");
	const state = useSyncExternalStore(
		context.store.subscribe,
		context.store.getSnapshot,
	);
	return { ...context, state };
}
