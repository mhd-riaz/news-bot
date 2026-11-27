import { type ReactNode, useEffect, useRef } from "react";
import { signInHref } from "../api";

interface GateProps {
	title: string;
	children?: ReactNode;
	busy?: boolean;
	// Move focus to the title when this screen replaces the reader.
	focusTitle?: boolean;
}

export function GateScreen({
	title,
	children,
	busy = false,
	focusTitle = false,
}: GateProps) {
	const heading = useRef<HTMLHeadingElement>(null);
	useEffect(() => {
		if (focusTitle) heading.current?.focus();
	}, [focusTitle]);
	return (
		<main className="gate" aria-busy={busy}>
			<div className="gate-card">
				<p className="wordmark gate-wordmark">
					AFTERLINE
					<span className="wordmark-dot" aria-hidden="true" />
				</p>
				<h1 ref={heading} className="gate-title" tabIndex={-1}>
					{title}
				</h1>
				{children}
			</div>
		</main>
	);
}

export type SignInNotice = "signed-out" | "ended" | null;

const NOT_INVITED =
	"That Google account’s email address is not on the invite list. Ask the owner to invite it, or sign in with a different Google account.";
const SIGN_IN_FAILED = "Sign-in failed. Please try again.";

export function SignInScreen({
	loginUrl,
	authError,
	notice,
}: {
	loginUrl: string;
	authError: string;
	notice: SignInNotice;
}) {
	useEffect(() => {
		document.title = "Sign in · AFTERLINE";
	}, []);
	// Any other error code from the server is treated as a failed sign-in.
	let problem = "";
	if (authError === "not_invited") problem = NOT_INVITED;
	else if (authError) problem = SIGN_IN_FAILED;
	return (
		<GateScreen title="Sign in to read" focusTitle={notice !== null}>
			<p className="gate-copy">
				AFTERLINE is a private news reader for invited readers. Sign in with the
				Google account that was invited.
			</p>
			{notice === "signed-out" ? (
				<p className="notice" role="status">
					You are signed out.
				</p>
			) : null}
			{notice === "ended" ? (
				<p className="notice" role="status">
					Your sign-in has ended. Sign in again to keep reading.
				</p>
			) : null}
			{problem ? (
				<p className="notice gate-problem" role="alert">
					{problem}
				</p>
			) : null}
			<p className="gate-actions">
				<a className="pill-button" href={signInHref(loginUrl, window.location)}>
					{problem === SIGN_IN_FAILED
						? "Try again with Google"
						: "Sign in with Google"}
				</a>
			</p>
		</GateScreen>
	);
}
