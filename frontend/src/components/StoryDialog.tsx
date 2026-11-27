import { useEffect, useRef, useState } from "react";
import { INPUT_KINDS, METHODS, NOTE_LIMIT } from "../reader/constants";
import { splitStoryText, storyDateLabel } from "../reader/format";
import { articleDate } from "../reader/normalise";
import {
	activeList,
	canNext,
	canPrevious,
	currentArticle,
	isEdition,
} from "../reader/selectors";
import type { Article } from "../reader/types";
import { useReader } from "./context";
import { LiveText } from "./Feed";
import { useModal } from "./modal";
import { Tile } from "./Tile";

function StoryCover({ article }: { article: Article }) {
	const [status, setStatus] = useState<"loading" | "shown" | "hidden">(
		article.image_url ? "loading" : "hidden",
	);
	return (
		<figure
			id="story-cover"
			className={
				status === "loading" ? "reading-figure is-loading" : "reading-figure"
			}
			hidden={status === "hidden"}
		>
			{article.image_url ? (
				<img
					id="story-image"
					className="story-image"
					alt=""
					referrerPolicy="no-referrer"
					decoding="async"
					src={article.image_url}
					hidden={status !== "shown"}
					onLoad={(event) => {
						const image = event.currentTarget;
						setStatus(
							image.naturalWidth < 320 || image.naturalHeight < 160
								? "hidden"
								: "shown",
						);
					}}
					onError={() => setStatus("hidden")}
				/>
			) : null}
			<figcaption id="story-caption" className="figure-caption">
				{status === "shown"
					? `Image: ${article.source_name || "the original publisher"}`
					: ""}
			</figcaption>
		</figure>
	);
}

const TEXT_FIELDS =
	"input, textarea, select, [contenteditable]:not([contenteditable='false']), [role='textbox']";

function NoteEditor({ hidden }: { hidden: boolean }) {
	const { store, state } = useReader();
	const note = useRef<HTMLTextAreaElement>(null);
	// The Go reader saved on the textarea's native change event (leaving the box after an edit).
	useEffect(() => {
		const element = note.current;
		if (!element) return;
		const save = () => store.saveNote();
		element.addEventListener("change", save);
		return () => element.removeEventListener("change", save);
	}, [store]);
	return (
		<div id="note-editor" className="note-editor" hidden={hidden}>
			<label htmlFor="story-note">Your note on this saved story</label>
			<textarea
				id="story-note"
				ref={note}
				rows={3}
				maxLength={NOTE_LIMIT}
				placeholder="Why it matters, what to follow up…"
				value={state.noteDraft}
				onChange={(event) => store.inputNote(event.target.value)}
			/>
			<div className="note-actions">
				<button
					id="save-note"
					className="text-button"
					type="button"
					onClick={() => store.saveNote()}
				>
					Save note
				</button>
				<span id="note-status" className="fine-print" role="status">
					{state.noteStatus}
				</span>
			</div>
		</div>
	);
}

export function StoryDialog() {
	const { store, state, refs } = useReader();
	useModal(state.readerOpen, refs.storyDialog);
	const article = currentArticle(state);
	const total = activeList(state).length;
	const more = !state.readerTrail && !isEdition(state) && !state.exhausted;
	const position = article ? state.open + 1 : 0;
	const saved = Boolean(
		article && state.saved.some((item) => item.id === article.id),
	);
	const liked = Boolean(article && state.profile.liked.includes(article.id));
	const disliked = Boolean(
		article && state.profile.disliked.includes(article.id),
	);
	const date = article ? articleDate(article).date : null;
	const text = article
		? splitStoryText(article)
		: { lead: "", rest: "", more: false };
	const lens = state.method ? METHODS[state.method].name : "";
	// Each story starts with its "Continue" and "Why this story?" sections closed.
	const storyKey = article?.id ?? "none";

	useEffect(() => {
		const onKeyDown = (event: KeyboardEvent) => {
			const target = event.target;
			if (
				!store.state.readerOpen ||
				event.defaultPrevented ||
				event.repeat ||
				event.altKey ||
				event.ctrlKey ||
				event.metaKey ||
				event.shiftKey ||
				(target instanceof Element && target.closest(TEXT_FIELDS)) ||
				window.getSelection()?.toString()
			) {
				return;
			}
			if (event.key === "ArrowRight" && store.canNext()) {
				event.preventDefault();
				void store.nextStory();
			} else if (event.key === "ArrowLeft" && store.canPrevious()) {
				event.preventDefault();
				store.previousStory();
			}
		};
		document.addEventListener("keydown", onKeyDown);
		return () => document.removeEventListener("keydown", onKeyDown);
	}, [store]);

	// A horizontal touch swipe moves between stories, as in the Go reader.
	const swipe = useRef<{
		id: number;
		x: number;
		y: number;
		time: number;
	} | null>(null);

	return (
		<dialog
			id="story-dialog"
			ref={refs.storyDialog}
			className="story-dialog"
			aria-labelledby="story-title"
			onCancel={(event) => {
				event.preventDefault();
				store.closeStory();
			}}
			onClose={() => {
				if (store.state.readerOpen) store.closeStory();
			}}
		>
			<div className="reading-bar">
				<button
					id="close-story"
					className="reading-back"
					type="button"
					onClick={() => store.closeStory()}
				>
					<span aria-hidden="true">←</span> All stories
				</button>
				<nav
					id="story-navigation"
					className="reading-nav"
					aria-label="Story navigation"
				>
					<p className="reading-position">
						<span id="position-current">{position}</span>{" "}
						<span className="position-divider">of</span>{" "}
						<span id="position-total">{`${total}${more && total ? "+" : ""}`}</span>
					</p>
					<button
						id="previous-story"
						className="round-button"
						type="button"
						aria-label="Previous story"
						disabled={!canPrevious(state)}
						onClick={() => store.previousStory()}
					>
						<span aria-hidden="true">←</span>
					</button>
					<button
						id="next-story"
						className="round-button"
						type="button"
						aria-label="Next story"
						disabled={!canNext(state)}
						onClick={() => void store.nextStory()}
					>
						<span aria-hidden="true">→</span>
					</button>
				</nav>
				<progress
					id="story-progress"
					className="reading-progress"
					value={position}
					max={Math.max(1, total)}
					aria-label="Position within the loaded stories"
					aria-valuetext={`Story ${position} of ${total}${more ? "; more may be available" : ""}`}
				/>
			</div>
			<article
				id="story-card"
				className="reading"
				aria-labelledby="story-title"
				onPointerDown={(event) => {
					const target = event.target;
					if (
						event.pointerType !== "touch" ||
						event.isPrimary === false ||
						(target instanceof Element &&
							target.closest("a, button, input, textarea, summary, details"))
					) {
						swipe.current = null;
						return;
					}
					swipe.current = {
						id: event.pointerId,
						x: event.clientX,
						y: event.clientY,
						time: event.timeStamp,
					};
				}}
				onPointerMove={(event) => {
					const start = swipe.current;
					if (
						start &&
						event.pointerId === start.id &&
						Math.abs(event.clientY - start.y) > 22
					) {
						swipe.current = null;
					}
				}}
				onPointerCancel={() => {
					swipe.current = null;
				}}
				onPointerUp={(event) => {
					const start = swipe.current;
					swipe.current = null;
					if (
						!start ||
						start.id !== event.pointerId ||
						!store.state.readerOpen ||
						window.getSelection()?.toString()
					) {
						return;
					}
					const dx = event.clientX - start.x;
					const dy = event.clientY - start.y;
					if (
						Math.abs(dx) < 70 ||
						Math.abs(dx) < Math.abs(dy) * 1.7 ||
						event.timeStamp - start.time > 900
					) {
						return;
					}
					if (dx < 0) void store.nextStory();
					else store.previousStory();
				}}
			>
				<header className="reading-header">
					<p className="reading-kicker">
						<span
							id="story-stamp"
							className={article?.fresh ? "stamp is-fresh" : "stamp"}
						>
							{article?.fresh ? "Fresh · last 30 days" : "From the archive"}
						</span>
						<span id="story-source" className="reading-source">
							{article ? article.source_name || "Unlisted source" : ""}
						</span>
					</p>
					<h2
						id="story-title"
						ref={refs.storyTitle}
						className="reading-title"
						tabIndex={-1}
					>
						{article?.title}
					</h2>
					<p className="reading-meta">
						<time
							id="story-date"
							dateTime={date ? date.toISOString() : undefined}
						>
							{article ? storyDateLabel(article, store.formats) : ""}
						</time>
						<span aria-hidden="true"> · </span>
						<span id="story-text-kind">{article?.text_kind}</span>
					</p>
				</header>
				{article ? <StoryCover key={article.id} article={article} /> : null}
				<div className="reading-body">
					<p id="story-text" className="reading-text">
						{text.lead}
					</p>
					<details
						key={`more-${storyKey}`}
						id="more-text"
						className="more-text"
						hidden={!text.more}
					>
						<summary>Continue the stored text</summary>
						<p id="remaining-text" className="reading-text">
							{text.rest}
						</p>
					</details>
					<p className="reading-cta">
						<a
							id="read-original"
							className="pill-button"
							target="_blank"
							rel="noopener noreferrer"
							referrerPolicy="no-referrer"
							href={article?.url || undefined}
							hidden={!article?.url}
						>
							<span id="read-original-label">
								{article?.source_name
									? `Read the full story at ${article.source_name}`
									: "Read the full story"}
							</span>{" "}
							<span aria-hidden="true">↗</span>
							<span className="sr-only"> (opens in a new tab)</span>
						</a>
						<span
							id="original-unavailable"
							className="fine-print"
							hidden={Boolean(article?.url)}
						>
							Original link unavailable
						</span>
					</p>
					<fieldset
						className="preference-actions"
						aria-label="Your interest in this story"
					>
						<button
							id="like-story"
							className="preference-button"
							type="button"
							aria-pressed={liked}
							disabled={!article}
							onClick={() => store.changePreference("liked")}
						>
							<span aria-hidden="true">＋</span> More like this
						</button>
						<button
							id="dislike-story"
							className="preference-button"
							type="button"
							aria-pressed={disliked}
							disabled={!article}
							onClick={() => store.changePreference("disliked")}
						>
							<span aria-hidden="true">−</span> Not interested
						</button>
						<button
							id="save-story"
							className="preference-button"
							type="button"
							aria-pressed={saved}
							disabled={!article}
							onClick={() => store.toggleSaved()}
						>
							<span id="save-icon" aria-hidden="true">
								{saved ? "★" : "☆"}
							</span>{" "}
							<span id="save-label" className="button-label">
								{saved ? "Saved" : "Save"}
							</span>
						</button>
					</fieldset>
					<NoteEditor hidden={!saved} />
					<p
						id="reader-status"
						className="reader-status"
						role="status"
						aria-live="polite"
						aria-atomic="true"
					>
						<LiveText message={state.readerStatus} />
					</p>
					<details
						key={`match-${storyKey}`}
						id="match-details"
						className="match-details"
					>
						<summary>Why this story?</summary>
						<p id="story-reason">
							{article?.reason ||
								"Selected using article content and the interests you explicitly choose, not a historical user profile."}
						</p>
						<p id="story-score" className="fine-print">
							{article && article.score !== null
								? `${lens} match score: ${article.score.toFixed(3)}. Scores are lens-specific, not confidence ratings or a measure of reporting quality.`
								: `${lens} content lens. No match score was supplied.`}
						</p>
						<p id="story-input" className="fine-print">
							{article
								? `Model input: ${INPUT_KINDS[article.input_kind]}. Displayed text: ${article.text_kind.toLowerCase()}.`
								: ""}
						</p>
					</details>
				</div>
				<section className="reading-related" aria-labelledby="related-heading">
					<div className="related-head">
						<div>
							<h3 id="related-heading">Related reading</h3>
							<p className="related-note">
								Today’s coverage and older background, from fresh and archived
								stories.
							</p>
						</div>
						<button
							id="related-story"
							className="text-button"
							type="button"
							disabled={!article}
							onClick={() => store.showRelatedFeed()}
						>
							See all related stories <span aria-hidden="true">→</span>
						</button>
					</div>
					<div id="related-grid" className="story-grid related-grid">
						{state.related.map((item, index) => (
							<Tile
								key={item.id}
								article={item}
								index={index}
								list="related"
								badge
								level={4}
							/>
						))}
					</div>
					<p id="related-status" className="fine-print related-status">
						{state.relatedStatus}
					</p>
				</section>
				<p id="navigation-hint" className="navigation-hint">
					<span className="swipe-hint">Swipe, or </span>use <kbd>←</kbd>{" "}
					<kbd>→</kbd> to move between stories, and <kbd>Esc</kbd> to return to
					all stories.
				</p>
			</article>
		</dialog>
	);
}
