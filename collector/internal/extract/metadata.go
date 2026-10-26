package extract

import (
	"net/url"
	"strings"
	"time"

	"golang.org/x/net/html"
)

func metadataFromHTML(page []byte, base *url.URL) Result {
	tokenizer := html.NewTokenizer(strings.NewReader(string(page)))
	var articleDate *time.Time
	var openGraphImage, twitterImage string

	for {
		kind := tokenizer.Next()
		if kind == html.ErrorToken {
			break
		}
		if kind != html.StartTagToken {
			continue
		}
		name, _ := tokenizer.TagName()
		if !strings.EqualFold(string(name), "meta") {
			continue
		}
		attributes := make(map[string]string)
		for key, value, more := tokenizer.TagAttr(); ; key, value, more = tokenizer.TagAttr() {
			attributes[strings.ToLower(string(key))] = strings.TrimSpace(string(value))
			if !more {
				break
			}
		}

		property := strings.ToLower(attributes["property"])
		if property == "" {
			property = strings.ToLower(attributes["name"])
		}
		content := attributes["content"]
		switch property {
		case "article:published_time":
			if articleDate == nil {
				articleDate = parsePageDate(content)
			}
		case "og:image":
			if openGraphImage == "" {
				openGraphImage = content
			}
		case "twitter:image":
			if twitterImage == "" {
				twitterImage = content
			}
		}
	}

	image := resolvePageImage(openGraphImage, base)
	if image == "" {
		image = resolvePageImage(twitterImage, base)
	}
	return Result{
		PublishedAt: articleDate,
		ImageURL:    image,
	}
}

func parsePageDate(value string) *time.Time {
	value = strings.TrimSpace(value)
	for _, layout := range []string{
		time.RFC3339Nano,
		time.RFC3339,
	} {
		parsed, err := time.Parse(layout, value)
		if err == nil {
			parsed = parsed.UTC()
			return &parsed
		}
	}
	return nil
}

func resolvePageImage(value string, base *url.URL) string {
	if strings.TrimSpace(value) == "" {
		return ""
	}
	image, err := url.Parse(strings.TrimSpace(value))
	if err != nil {
		return ""
	}
	if base != nil {
		image = base.ResolveReference(image)
	}
	if (image.Scheme != "http" && image.Scheme != "https") || image.Host == "" {
		return ""
	}
	image.Fragment = ""
	image.RawFragment = ""
	return image.String()
}
