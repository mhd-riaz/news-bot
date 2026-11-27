import { useCallback, useEffect, useRef, useState } from "react";
import {
	ApiError,
	DEFAULT_LOGIN_URL,
	fetchSession,
	type Session,
	signOut,
} from "./api";
import { GateScreen, type SignInNotice, SignInScreen } from "./components/Gate";
import { Reader } from "./components/Reader";
import { errorMessage } from "./reader/normalise";

type Gate =
	| { kind: "checking" }
	| { kind: "error"; message: string }
	| { kind: "sign-in"; notice: SignInNotice; loginUrl: string }
	| { kind: "reader"; session: Session };

// First asks the server who is signed in, then shows the reader or the sign-in screen.
export function App() {
	const [gate, setGate] = useState<Gate>({ kind: "checking" });
	const loginUrl = useRef(DEFAULT_LOGIN_URL);
	const pending = useRef<AbortController | null>(null);

	const check = useCallback(() => {
		pending.current?.abort();
		const controller = new AbortController();
		pending.current = controller;
		fetchSession(controller).then(
			(session) => {
				if (pending.current !== controller) return;
				pending.current = null;
				loginUrl.current = session.loginUrl;
				setGate(
					session.authEnabled && !session.signedIn
						? { kind: "sign-in", notice: null, loginUrl: session.loginUrl }
						: { kind: "reader", session },
				);
			},
			(error: unknown) => {
				if (pending.current !== controller) return;
				pending.current = null;
				setGate(
					error instanceof ApiError && error.signInRequired
						? { kind: "sign-in", notice: null, loginUrl: loginUrl.current }
						: {
								kind: "error",
								message:
									errorMessage(error) ||
									"The sign-in check failed. Please try again.",
							},
				);
			},
		);
	}, []);

	useEffect(() => {
		check();
		return () => {
			pending.current?.abort();
			pending.current = null;
		};
	}, [check]);

	const onSignInRequired = useCallback(() => {
		setGate({ kind: "sign-in", notice: "ended", loginUrl: loginUrl.current });
	}, []);

	const onSignOut = useCallback(async () => {
		await signOut();
		setGate({
			kind: "sign-in",
			notice: "signed-out",
			loginUrl: loginUrl.current,
		});
	}, []);

	switch (gate.kind) {
		case "checking":
			return <GateScreen title="Opening AFTERLINE…" busy />;
		case "error":
			return (
				<GateScreen title="The reader is not answering.">
					<p className="notice" role="alert">
						{gate.message}
					</p>
					<p className="gate-actions">
						<button
							className="pill-button"
							type="button"
							onClick={() => {
								setGate({ kind: "checking" });
								check();
							}}
						>
							Try again
						</button>
					</p>
				</GateScreen>
			);
		case "sign-in":
			return (
				<SignInScreen
					loginUrl={gate.loginUrl}
					authError={
						new URLSearchParams(window.location.search).get("auth_error") ?? ""
					}
					notice={gate.notice}
				/>
			);
		default: {
			const { session } = gate;
			return (
				<Reader
					account={
						session.authEnabled && session.signedIn
							? (session.reader ?? { email: "", name: "" })
							: null
					}
					onSignOut={onSignOut}
					onSignInRequired={onSignInRequired}
				/>
			);
		}
	}
}
