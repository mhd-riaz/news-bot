import { type CSSProperties, useState } from "react";
import { clip, hue, shortDateLabel } from "../reader/format";
import type { Article } from "../reader/types";
import { useReader } from "./context";

export function hueStyle(article: Article): CSSProperties {
	// React sets custom properties through the CSSOM, which the strict CSP allows.
	return {
		"--tile-hue": String(hue(article.source_name || article.id)),
	} as CSSProperties;
}

// Logos and tracking pixels look like broken pictures; the coloured placeholder reads better.
export function CoverImage({
	src,
	className,
}: {
	src: string;
	className?: string;
}) {
	const [status, setStatus] = useState<"loading" | "loaded" | "removed">(
		"loading",
	);
	if (status === "removed") return null;
	const classes = [className, status === "loaded" ? "is-loaded" : ""]
		.filter(Boolean)
		.join(" ");
	return (
		<img
			className={classes || undefined}
			alt=""
			loading="lazy"
			decoding="async"
			referrerPolicy="no-referrer"
			src={src}
			onLoad={(event) => {
				const image = event.currentTarget;
				setStatus(
					image.naturalWidth < 240 || image.naturalHeight < 120
						? "removed"
						: "loaded",
				);
			}}
			onError={() => setStatus("removed")}
		/>
	);
}

interface TileProps {
	article: Article;
	index: number;
	list: "feed" | "related";
	lead?: boolean;
	badge?: boolean;
	level?: 2 | 4;
}

export function Tile({
	article,
	index,
	list,
	lead = false,
	badge = false,
	level = 2,
}: TileProps) {
	const { store, state } = useReader();
	const saved = state.saved.some((item) => item.id === article.id);
	const group = state.facts.topics.find(
		(topic) => topic.id === article.group,
	)?.label;
	const Heading = level === 4 ? "h4" : "h2";
	return (
		<article className={lead ? "tile tile-lead" : "tile"}>
			<div className="tile-media" style={hueStyle(article)}>
				<div className="tile-placeholder" aria-hidden="true">
					<span className="tile-placeholder-source">
						{article.source_name || "AFTERLINE"}
					</span>
					<span className="tile-placeholder-topic">
						{group || "From the collection"}
					</span>
				</div>
				{article.image_url ? (
					<CoverImage src={article.image_url} className="tile-image" />
				) : null}
				{badge ? (
					<span
						className={article.fresh ? "tile-badge is-fresh" : "tile-badge"}
					>
						{article.fresh ? "Fresh" : "From the archive"}
					</span>
				) : null}
			</div>
			<div className="tile-body">
				<p className="tile-meta">
					<span className="tile-source">
						{article.source_name || "Unlisted source"}
					</span>
					<span className="tile-date">
						{shortDateLabel(article, store.formats)}
					</span>
				</p>
				<Heading className="tile-title">
					<button
						type="button"
						className="tile-open"
						data-open={list}
						data-index={index}
						onClick={(event) =>
							store.openStory(list, index, event.currentTarget)
						}
					>
						{article.title}
					</button>
				</Heading>
				{article.text_kind !== "Headline only" && article.text ? (
					<p className="tile-summary">{clip(article.text, lead ? 420 : 240)}</p>
				) : null}
			</div>
			<button
				type="button"
				className="tile-save"
				data-save={article.id}
				title={saved ? "Saved · select to remove" : "Save for later"}
				aria-pressed={saved}
				aria-label={`Save: ${article.title}`}
				onClick={() => {
					const found = store.findArticle(article.id);
					if (found) store.toggleSaved(found);
				}}
			>
				{saved ? "★" : "☆"}
			</button>
		</article>
	);
}
