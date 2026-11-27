import { type RefObject, useLayoutEffect, useRef } from "react";

// Keeps a native <dialog> open as a modal while `open` is true. Layout effects
// run child-first, so a dialog opens before its parent moves focus into it.
export function useModal(
	open: boolean,
	given?: RefObject<HTMLDialogElement | null>,
): RefObject<HTMLDialogElement | null> {
	const own = useRef<HTMLDialogElement>(null);
	const ref = given ?? own;
	useLayoutEffect(() => {
		const dialog = ref.current;
		if (!dialog) return;
		if (open && !dialog.open) dialog.showModal();
		else if (!open && dialog.open) dialog.close();
	}, [open, ref]);
	return ref;
}
