import { TASTE_LIMIT } from "../reader/constants";
import { articleDate, dateValue } from "../reader/normalise";
import type { Article, SavedItem } from "../reader/types";
import { useReader } from "./context";
import { useModal } from "./modal";
import { CoverImage, hueStyle } from "./Tile";

function TasteChoice({
	item,
	checked,
	full,
}: {
	item: Article;
	checked: boolean;
	full: boolean;
}) {
	const { store } = useReader();
	const { date, label } = articleDate(item);
	const when = date
		? `${label.toLowerCase()} ${store.formats.shortDate.format(date)}`
		: "Stored date unavailable";
	return (
		<label className="taste-choice">
			<input
				type="checkbox"
				name="interest"
				value={item.id}
				checked={checked}
				disabled={full && !checked}
				onChange={(event) => store.toggleTaste(item.id, event.target.checked)}
			/>
			<span className="taste-thumb" aria-hidden="true" style={hueStyle(item)}>
				{item.image_url ? <CoverImage src={item.image_url} /> : null}
			</span>
			<span>
				<span className="taste-title">{item.title}</span>
				<span className="taste-meta">{`${item.source_name || "Unlisted source"} · ${when}`}</span>
			</span>
		</label>
	);
}

export function TasteDialog() {
	const { store, state } = useReader();
	const ref = useModal(state.tasteOpen);
	const count = state.selected.length;
	const ready = state.tasteStatus === "ready";
	return (
		<dialog
			id="taste-dialog"
			ref={ref}
			className="taste-dialog"
			aria-labelledby="taste-heading"
			aria-describedby="taste-description"
			onClose={() => {
				if (store.state.tasteOpen) store.closeTaste();
			}}
		>
			<form
				id="taste-form"
				onSubmit={(event) => {
					event.preventDefault();
					store.submitTaste();
				}}
			>
				<div className="dialog-heading">
					<p className="eyebrow">Your edition, your choices</p>
					<button
						id="close-taste"
						className="close-button"
						type="button"
						aria-label="Close interest selection"
						onClick={() => store.closeTaste()}
					>
						×
					</button>
				</div>
				<h2 id="taste-heading">What catches your eye?</h2>
				<p id="taste-description" className="dialog-copy">
					Choose 3–5 real stories to add to your interests. Fewer is fine; you
					can skip. Existing interests are kept. Choices are saved in this
					browser for this snapshot and included in recommendation requests.
				</p>
				<div className="taste-toolbar">
					<span>Up to 24 stories</span>
					<output id="taste-count" aria-live="polite">
						{`${count} / ${TASTE_LIMIT} selected`}
					</output>
				</div>
				<p
					id="taste-loading"
					className="taste-loading"
					role="status"
					hidden={state.tasteStatus !== "loading"}
				>
					Loading real stories…
				</p>
				<div
					id="taste-error"
					className="notice"
					role="alert"
					hidden={state.tasteStatus !== "error"}
				>
					<p id="taste-error-message">{state.tasteError}</p>
					<button
						id="taste-retry"
						className="text-button"
						type="button"
						onClick={() => store.retryTaste()}
					>
						{state.tasteReload ? "Reload archive" : "Retry Explore"}
					</button>
				</div>
				<p
					id="taste-empty"
					className="notice"
					hidden={!ready || state.tasteItems.length > 0}
				>
					No unseen stories were available. You can skip, choose another lens,
					or reset your local history to revisit the collection.
				</p>
				<fieldset
					id="taste-options"
					className="taste-options"
					disabled={!ready}
				>
					<legend className="sr-only">
						Choose up to five stories as interests
					</legend>
					<div id="taste-list" className="taste-list">
						{state.tasteItems.map((item) => (
							<TasteChoice
								key={item.id}
								item={item}
								checked={state.selected.includes(item.id)}
								full={count >= TASTE_LIMIT}
							/>
						))}
					</div>
				</fieldset>
				<p id="taste-hint" className="fine-print">
					{count === TASTE_LIMIT
						? "Five selected. Uncheck one to choose a different story. Offered articles are not marked viewed."
						: "Three to five is a useful start; fewer is fine. Only selected articles become interests, not viewed history."}
				</p>
				<div className="dialog-footer">
					<button
						id="taste-skip"
						className="text-button"
						type="button"
						onClick={() => store.skipOnboarding()}
					>
						Skip for now
					</button>
					<button
						id="taste-submit"
						className="pill-button"
						type="submit"
						disabled={!ready}
					>
						{count
							? `Add ${count} ${count === 1 ? "interest" : "interests"} ↗`
							: "Explore without selecting ↗"}
					</button>
				</div>
			</form>
		</dialog>
	);
}

function SavedEntry({ item }: { item: SavedItem }) {
	const { store } = useReader();
	const date = dateValue(item.published_at);
	const meta = `${item.source_name || "Unlisted source"}${date ? ` · ${store.formats.shortDate.format(date)}` : ""}`;
	return (
		<li className="saved-item">
			{item.url ? (
				<a
					className="saved-title"
					href={item.url}
					target="_blank"
					rel="noopener noreferrer"
					referrerPolicy="no-referrer"
				>
					{item.title}
				</a>
			) : (
				<p className="saved-title">{item.title}</p>
			)}
			<p className="saved-meta">{meta}</p>
			<p className={item.note ? "saved-note" : "saved-note empty"}>
				{item.note || "No note yet."}
			</p>
			<button
				className="text-button muted-button"
				type="button"
				data-remove={item.id}
				onClick={() => store.removeSaved(item.id)}
			>
				Remove
			</button>
		</li>
	);
}

export function SavedDialog() {
	const { store, state } = useReader();
	const ref = useModal(state.savedOpen);
	return (
		<dialog
			id="saved-dialog"
			ref={ref}
			className="saved-dialog"
			aria-labelledby="saved-heading"
			aria-describedby="saved-description"
			onClose={() => {
				if (store.state.savedOpen) store.closeSaved();
			}}
		>
			<div className="dialog-heading">
				<p className="eyebrow">Saved for deeper study</p>
				<button
					id="close-saved"
					className="close-button"
					type="button"
					aria-label="Close saved stories"
					onClick={() => store.closeSaved()}
				>
					×
				</button>
			</div>
			<h2 id="saved-heading">Saved stories</h2>
			<p id="saved-description" className="dialog-copy">
				Saved in this browser only, with your notes. They stay when the stories
				are refreshed; clearing browser data removes them.
			</p>
			<p id="saved-empty" className="notice" hidden={state.saved.length > 0}>
				Nothing saved yet. Use ☆ on any story, or Save in the reader, then add a
				note.
			</p>
			<ol id="saved-list" className="saved-list">
				{[...state.saved].reverse().map((item) => (
					<SavedEntry key={item.id} item={item} />
				))}
			</ol>
		</dialog>
	);
}

export function ResetDialog() {
	const { store, state } = useReader();
	const ref = useModal(state.resetOpen);
	return (
		<dialog
			id="reset-dialog"
			ref={ref}
			className="reset-dialog"
			aria-labelledby="reset-heading"
			aria-describedby="reset-description"
			onClose={() => {
				if (store.state.resetOpen) store.closeReset();
			}}
		>
			<form
				id="reset-form"
				onSubmit={(event) => {
					event.preventDefault();
					store.reset();
				}}
			>
				<p className="eyebrow">A fresh edition</p>
				<h2 id="reset-heading">Start again?</h2>
				<p id="reset-description" className="dialog-copy">
					Clear interests and opened-story history for this snapshot in this
					browser. This does not change the archive or your saved stories.
				</p>
				<div className="dialog-footer">
					<button
						id="cancel-reset"
						className="text-button"
						type="button"
						onClick={() => store.closeReset()}
					>
						Keep my edition
					</button>
					<button className="pill-button" type="submit">
						Reset &amp; explore
					</button>
				</div>
			</form>
		</dialog>
	);
}
