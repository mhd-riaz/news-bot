import { useEffect, useLayoutEffect, useRef, useState } from "react";
import type { Account } from "../api";
import { VIEW_ORDER, VIEWS } from "../reader/constants";
import { errorMessage } from "../reader/normalise";
import { isDark } from "../reader/selectors";
import { ReaderStore } from "../reader/store";
import {
	ReaderContext,
	type ReaderContextValue,
	type ReaderRefs,
	useReader,
} from "./context";
import { ResetDialog, SavedDialog, TasteDialog } from "./Dialogs";
import { FeedPanel } from "./Feed";
import { StoryDialog } from "./StoryDialog";

interface ReaderProps {
	// The signed-in reader, shown only when sign-in is switched on.
	account: Account | null;
	onSignOut: () => Promise<void>;
	onSignInRequired: () => void;
}

function AccountControls({
	account,
	onSignOut,
}: {
	account: Account;
	onSignOut: () => Promise<void>;
}) {
	const { store } = useReader();
	const [busy, setBusy] = useState(false);
	const name = account.name || account.email;
	return (
		<div className="account shell">
			{name ? (
				<p className="account-name">
					Signed in as{" "}
					<span className="account-who" title={account.email || undefined}>
						{name}
					</span>
				</p>
			) : null}
			<button
				id="sign-out"
				className="text-button"
				type="button"
				disabled={busy}
				onClick={() => {
					setBusy(true);
					onSignOut().catch((error: unknown) => {
						setBusy(false);
						store.notify(
							errorMessage(error) || "Sign-out failed. Please try again.",
						);
					});
				}}
			>
				Sign out
			</button>
		</div>
	);
}

function SiteNav() {
	const { store, state } = useReader();
	const ready = Boolean(state.meta);
	return (
		<header className="site-nav">
			<div className="nav-inner shell">
				<a className="wordmark" href="/" aria-label="Afterline home">
					AFTERLINE
					<span className="wordmark-dot" aria-hidden="true" />
				</a>
				<fieldset
					id="view-control"
					className="segmented"
					aria-label="Choose what to read"
				>
					{VIEW_ORDER.map((view) => (
						<button
							key={view}
							id={`view-${view}`}
							className="segment"
							type="button"
							data-view={view}
							aria-pressed={!state.seed && view === state.view}
							disabled={!ready}
							onClick={() => store.changeView(view)}
						>
							{VIEWS[view].label}
						</button>
					))}
				</fieldset>
				<div className="nav-actions">
					<button
						id="open-saved"
						className="nav-button"
						type="button"
						onClick={() => store.openSaved()}
					>
						{`Saved stories (${state.saved.length})`}
					</button>
					<button
						id="theme-toggle"
						className="theme-toggle"
						type="button"
						aria-pressed={isDark(state)}
						onClick={() => store.toggleTheme()}
					>
						<span aria-hidden="true">◐</span>
						<span className="theme-label">Dark theme</span>
					</button>
				</div>
			</div>
		</header>
	);
}

function About() {
	const { state } = useReader();
	const { facts } = state;
	return (
		<section className="about shell" aria-labelledby="page-intro">
			<div className="introduction">
				<p className="eyebrow">The considered edition</p>
				<h2 id="page-intro" className="intro-title">
					Today’s news.
					<br />
					<span>A longer memory.</span>
				</h2>
				<p className="intro-copy">
					Fresh stories first, shaped only by the stories you choose. Related
					reading reaches back into the archive, so today’s news arrives with
					its background.
				</p>
				<p className="intro-footnote">
					No autoplay. No ticking clock. Just something worth a second look.
				</p>
			</div>
			<aside className="archive-notes" aria-labelledby="archive-heading">
				<h2 id="archive-heading" className="toolbar-label">
					The collection
				</h2>
				<dl className="archive-facts">
					<div className="fact fact-lead">
						<dt>Articles in this snapshot</dt>
						<dd id="corpus-count">{facts.corpusCount}</dd>
					</div>
					<div className="fact">
						<dt>Fresh · last 30 days</dt>
						<dd id="fresh-count">{facts.freshCount}</dd>
					</div>
					<div className="fact">
						<dt id="edition-label">{facts.editionLabel}</dt>
						<dd id="edition-count">{facts.editionCount}</dd>
					</div>
					<div className="fact">
						<dt>Stored publication range</dt>
						<dd id="publication-range">{facts.publicationRange}</dd>
					</div>
					<div className="fact">
						<dt>Snapshot taken</dt>
						<dd id="collection-cutoff">{facts.collectionCutoff}</dd>
					</div>
				</dl>
				<p id="corpus-coverage" className="corpus-coverage">
					{state.coverage}
				</p>
				<details className="edition-details">
					<summary>A note on this edition</summary>
					<p id="profile-note">{facts.profileNote}</p>
					<p id="date-note">{facts.dateNote}</p>
					<p>
						Thread buttons are unsupervised content groups, not verified
						editorial categories. A summary or headline is not a substitute for
						the original reporting. External pages may have changed or
						disappeared.
					</p>
				</details>
				<p className="limits-note">
					Local to this snapshot: up to 50 likes, 50 not-interested choices, and
					the last 2,000 opened stories. Saved stories and notes stay in this
					browser across snapshots. No telemetry is sent by this page.
				</p>
			</aside>
		</section>
	);
}

function Page({
	account,
	onSignOut,
}: Pick<ReaderProps, "account" | "onSignOut">) {
	const { state, refs } = useReader();
	// The store names what to focus; this runs after the page shows the change.
	useLayoutEffect(() => {
		const request = state.focus;
		if (!request) return;
		if (request.kind === "story") {
			if (refs.storyDialog.current) refs.storyDialog.current.scrollTop = 0;
			refs.storyTitle.current?.focus({ preventScroll: true });
		} else if (request.kind === "edit-interests") {
			refs.editInterests.current?.focus({ preventScroll: true });
		} else if (request.kind === "panel") {
			refs.panel.current?.focus({ preventScroll: true });
		} else {
			const tile =
				request.index >= 0
					? refs.grid.current?.querySelectorAll<HTMLElement>(
							`button[data-index="${request.index}"]`,
						)[0]
					: undefined;
			if (request.opener?.isConnected)
				request.opener.focus({ preventScroll: true });
			else if (tile) tile.focus();
			else refs.panel.current?.focus({ preventScroll: true });
		}
	}, [state.focus, refs]);

	return (
		<>
			<a className="skip-link" href="#main">
				Skip to the stories
			</a>
			<SiteNav />
			{account ? (
				<AccountControls account={account} onSignOut={onSignOut} />
			) : null}
			<div className="shell">
				<p
					id="storage-warning"
					className="notice"
					role="status"
					hidden={!state.storageWarning}
				>
					{state.storageWarning}
				</p>
				<p
					id="link-note"
					className="notice"
					role="status"
					hidden={!state.linkNote}
				>
					{state.linkNote}
				</p>
			</div>
			<main id="main" tabIndex={-1}>
				<FeedPanel />
				<About />
			</main>
			<footer className="footer shell">
				<p>
					AFTERLINE <span aria-hidden="true">/</span> A little distance. A
					different perspective.
				</p>
				<div>
					<span
						id="snapshot-label"
						title={state.facts.snapshotTitle || undefined}
					>
						{state.facts.snapshotLabel}
					</span>
				</div>
			</footer>
			<StoryDialog />
			<TasteDialog />
			<SavedDialog />
			<ResetDialog />
		</>
	);
}

export function Reader({ account, onSignOut, onSignInRequired }: ReaderProps) {
	const [store] = useState(() => new ReaderStore({ onSignInRequired }));
	const panel = useRef<HTMLElement>(null);
	const grid = useRef<HTMLDivElement>(null);
	const editInterests = useRef<HTMLButtonElement>(null);
	const storyDialog = useRef<HTMLDialogElement>(null);
	const storyTitle = useRef<HTMLHeadingElement>(null);
	const [refs] = useState<ReaderRefs>(() => ({
		panel,
		grid,
		editInterests,
		storyDialog,
		storyTitle,
	}));
	const [context] = useState<ReaderContextValue>(() => ({
		store,
		refs,
	}));

	useEffect(() => {
		document.title = "Afterline · AFTERLINE";
		store.start();
		return () => store.dispose();
	}, [store]);

	return (
		<ReaderContext value={context}>
			<Page account={account} onSignOut={onSignOut} />
		</ReaderContext>
	);
}
