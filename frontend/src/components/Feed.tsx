import { METHOD_OPTIONS, METHODS, VIEWS } from "../reader/constants";
import { countFormat, editionDate } from "../reader/format";
import { isEdition, professionalDomains } from "../reader/selectors";
import type { Message, ReaderState } from "../reader/store";
import { useReader } from "./context";
import { Tile } from "./Tile";

// The count key replaces the text node, so a repeated message is read out again.
export function LiveText({ message }: { message: Message }) {
	return <span key={message.count}>{message.text}</span>;
}

function selectionLabel(state: ReaderState): string {
	const personal = state.profile.liked.length || state.profile.disliked.length;
	if (state.seed) return "Related reading";
	if (isEdition(state)) return "Yesterday’s edition";
	if (state.view === "archive") return "From the archive";
	return personal ? "For you" : "Latest news";
}

function viewNote(state: ReaderState, domains: string[]): string {
	const focus =
		state.professional && domains.length
			? ` Professional focus: ${domains.join(", ")} sources only.`
			: "";
	if (state.seed) {
		return `Stories close to the one you chose, from fresh news and the archive, so older background can surface.${focus}`;
	}
	if (state.view === "fresh" && state.profile.liked.length) {
		return `Stories from the last 30 days with a verified publication date, ranked around the stories you like.${focus}`;
	}
	return `${VIEWS[state.view].note}${focus}`;
}

function PageHeader() {
	const { store, state, refs } = useReader();
	const ready = Boolean(state.meta);
	const edition = isEdition(state);
	const group = state.meta?.topics.find((topic) => topic.id === state.topic);
	let pageDate = store.formats.dayFormat.format(new Date());
	if (edition)
		pageDate = state.meta?.edition_date ? editionDate(state.meta) : "Yesterday";
	let selectionNote = "";
	if (state.seed) {
		selectionNote = state.seedTitle
			? `Related to “${state.seedTitle}”`
			: "Using the article in your link as a content seed.";
	} else if (group) {
		selectionNote = `Thread: ${group.label}`;
	}
	const { liked, disliked, onboarded } = state.profile;
	return (
		<header className="page-header">
			<p id="page-date" className="page-date">
				{pageDate}
			</p>
			<h1 id="selection-label" className="page-title">
				{selectionLabel(state)}
			</h1>
			<p id="view-note" className="page-note">
				{viewNote(state, ready ? professionalDomains(state.meta) : [])}
			</p>
			<p id="selection-note" className="selection-note" hidden={!selectionNote}>
				{selectionNote}
			</p>
			<div className="page-meta">
				<p id="profile-summary" className="profile-summary">
					{ready
						? `${liked.length} ${liked.length === 1 ? "like" : "likes"} · ${disliked.length} not interested · local to this snapshot`
						: "Interests are saved in this browser."}
				</p>
				<div className="profile-actions">
					<button
						id="edit-interests"
						ref={refs.editInterests}
						className="text-button"
						type="button"
						disabled={!ready || state.loading}
						hidden={!onboarded}
						onClick={() => store.openTaste()}
					>
						Find more interests
					</button>
					<button
						id="open-reset"
						className="text-button muted-button"
						type="button"
						aria-label="Reset interests and history"
						disabled={!ready || state.loading}
						onClick={() => store.openReset()}
					>
						Reset
					</button>
				</div>
				<p
					id="action-status"
					className="action-status"
					role="status"
					aria-live="polite"
					aria-atomic="true"
				>
					<LiveText message={state.actionStatus} />
				</p>
			</div>
		</header>
	);
}

function topicCount(count: unknown): string {
	return typeof count === "number" && Number.isSafeInteger(count) && count >= 0
		? countFormat.format(count)
		: "";
}

function Toolbar() {
	const { store, state } = useReader();
	const ready = Boolean(state.meta);
	const domains = ready ? professionalDomains(state.meta) : [];
	const { facts } = state;
	return (
		<div className="toolbar">
			<section className="topics" aria-labelledby="topics-heading">
				<h2 id="topics-heading" className="toolbar-label">
					Threads
				</h2>
				<fieldset
					id="topic-list"
					className="topic-list"
					aria-label="Filter stories by content group"
				>
					<button
						id="topic-all"
						className="topic-button"
						type="button"
						data-topic=""
						aria-pressed={state.topic === ""}
						disabled={!ready}
						onClick={() => store.selectTopic("")}
					>
						<span className="topic-label">All stories</span>
						<span id="topic-all-count" className="topic-count">
							{facts.topicAllCount}
						</span>
					</button>
					{facts.topics.map((topic) => {
						const count = topicCount(topic.count);
						return (
							<button
								key={topic.id}
								className="topic-button"
								type="button"
								data-topic={topic.id}
								aria-pressed={topic.id === state.topic}
								disabled={!ready}
								title={
									count ? `${topic.label} · ${count} articles` : topic.label
								}
								onClick={() => store.selectTopic(topic.id)}
							>
								<span className="topic-label">{topic.label}</span>
								{count ? <span className="topic-count">{count}</span> : null}
							</button>
						);
					})}
				</fieldset>
				<p id="topic-status" className="sr-only" role="status">
					{state.topicStatus}
				</p>
			</section>
			<div className="toolbar-controls">
				<button
					id="professional-focus"
					className="switch"
					type="button"
					role="switch"
					aria-checked={state.professional}
					hidden={!domains.length}
					disabled={!ready || !domains.length}
					onClick={() => store.setProfessional(!state.professional)}
				>
					<span className="switch-track" aria-hidden="true" />
					<span className="switch-label">Professional focus</span>
				</button>
				<div className="lens-control">
					<label htmlFor="method">Lens</label>
					<select
						id="method"
						aria-describedby="lens-note"
						disabled={!ready}
						value={state.method}
						onChange={(event) => store.changeMethod(event.target.value)}
					>
						{state.method ? null : <option value="" />}
						{METHOD_OPTIONS.map((method) => (
							<option
								key={method}
								value={method}
								disabled={!facts.methods.includes(method)}
							>
								{METHODS[method].name}
							</option>
						))}
					</select>
				</div>
			</div>
			<p id="lens-note" className="sr-only">
				{state.method
					? METHODS[state.method].note
					: "Loading available content lenses."}
			</p>
		</div>
	);
}

function FeedFeedback() {
	const { store, state } = useReader();
	const ready = Boolean(state.meta);
	const { feedback } = state;
	let kicker = "A moment of context";
	if (feedback?.kind === "error") kicker = "An honest pause";
	else if (feedback?.kind === "empty") kicker = "A little breathing room";
	return (
		<div
			id="feed-feedback"
			className={
				state.items.length ? "feed-feedback with-story" : "feed-feedback"
			}
			hidden={!feedback}
		>
			<span
				id="loading-indicator"
				className="loading-indicator"
				aria-hidden="true"
				hidden={feedback?.kind !== "loading"}
			/>
			<p id="feedback-kicker" className="eyebrow">
				{kicker}
			</p>
			<h3 id="feedback-title">{feedback?.title}</h3>
			<p id="feedback-message">{feedback?.message}</p>
			<div className="feedback-actions">
				<button
					id="retry-feed"
					className="pill-button"
					type="button"
					hidden={feedback?.kind !== "error"}
					onClick={() => store.retry()}
				>
					{state.retryKind === "meta" ? "Reload archive" : "Try again"}
				</button>
				<button
					id="feedback-explore"
					className="text-button"
					type="button"
					hidden={feedback?.kind !== "empty" || !ready}
					onClick={() => store.exploreAll()}
				>
					Show all stories
				</button>
				<button
					id="feedback-interests"
					className="text-button"
					type="button"
					hidden={feedback?.kind !== "empty" || !ready}
					onClick={() => store.openTaste()}
				>
					Choose interests
				</button>
			</div>
		</div>
	);
}

export function FeedPanel() {
	const { store, state, refs } = useReader();
	const ready = Boolean(state.meta);
	const edition = isEdition(state);
	const { items, feedback } = state;
	const ended =
		items.length > 0 && !state.loading && !feedback && state.exhausted;
	return (
		<section
			id="reader-panel"
			ref={refs.panel}
			className="feed shell"
			aria-labelledby="selection-label"
			aria-busy={state.loading}
			tabIndex={-1}
		>
			<PageHeader />
			<Toolbar />
			<section
				id="onboarding-invite"
				className="onboarding-invite"
				aria-labelledby="invite-heading"
				hidden={!ready || state.profile.onboarded}
			>
				<div>
					<h2 id="invite-heading">Make this your edition.</h2>
					<p>
						Pick 3–5 real stories you would read. Fresh ranks everything else
						around them.
					</p>
				</div>
				<div className="invite-actions">
					<button
						id="start-onboarding"
						className="pill-button"
						type="button"
						disabled={!ready || state.loading}
						onClick={() => store.openTaste()}
					>
						Choose interests
					</button>
					<button
						id="skip-onboarding"
						className="text-button"
						type="button"
						disabled={!ready || state.loading}
						onClick={() => store.skipOnboarding()}
					>
						Skip for now
					</button>
				</div>
			</section>
			<button
				id="refresh-feed"
				className="refresh-pill"
				type="button"
				hidden={!state.stale || state.loading}
				onClick={() => store.refresh()}
			>
				<span aria-hidden="true">↻</span> Update for your new choices
			</button>
			<div
				id="story-grid"
				ref={refs.grid}
				className="story-grid"
				hidden={!items.length}
			>
				{items.map((article, index) => (
					<Tile
						key={article.id}
						article={article}
						index={index}
						list="feed"
						lead={index === 0}
						badge={Boolean(state.seed)}
					/>
				))}
			</div>
			<FeedFeedback />
			<div className="grid-more">
				<button
					id="load-more"
					className="pill-button pill-quiet"
					type="button"
					hidden={
						!items.length ||
						state.loading ||
						Boolean(feedback) ||
						state.exhausted ||
						edition
					}
					onClick={() => store.loadMore()}
				>
					More stories
				</button>
			</div>
			<section
				id="feed-end"
				className="end-note"
				aria-labelledby="end-heading"
				hidden={!ended}
			>
				<p className="eyebrow">A good place to pause</p>
				<h3 id="end-heading">That’s this selection.</h3>
				<p id="end-message">
					{state.endMessage ||
						"That’s everything in this selection for now. Try another thread or lens, add interests, or reset local history to revisit the collection."}
				</p>
				<div className="feedback-actions">
					<button
						id="end-explore"
						className="text-button"
						type="button"
						onClick={() => store.exploreAll()}
					>
						Show all stories
					</button>
					<button
						id="end-interests"
						className="text-button"
						type="button"
						onClick={() => store.openTaste()}
					>
						Choose interests
					</button>
				</div>
			</section>
			<p
				id="service-note"
				className="fine-print service-note"
				hidden={!state.serviceNote}
			>
				{state.serviceNote}
			</p>
			<p
				id="reader-live"
				className="sr-only"
				role="status"
				aria-live="polite"
				aria-atomic="true"
			>
				<LiveText message={state.readerLive} />
			</p>
		</section>
	);
}
