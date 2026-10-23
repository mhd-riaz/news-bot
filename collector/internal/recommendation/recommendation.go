// Package recommendation joins read-only content rankings to original MongoDB articles.
package recommendation

import (
	"bytes"
	"context"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"strings"
	"time"

	"github.com/riaz/newscollector/internal/domain"
)

var (
	ErrUnavailable = errors.New("recommendation service unavailable")
	ErrInvalid     = errors.New("invalid recommendation request")
	ErrNotIndexed  = errors.New("article outside indexed archive")
)

type Request struct {
	SeedID   string   `json:"seed_id,omitempty"`
	Liked    []string `json:"liked,omitempty"`
	Disliked []string `json:"disliked,omitempty"`
	Viewed   []string `json:"viewed,omitempty"`
	Topic    string   `json:"topic,omitempty"`
	Method   string   `json:"method,omitempty"`
	Limit    int      `json:"limit,omitempty"`
}

type Topic struct {
	ID              string   `json:"id"`
	Label           string   `json:"label"`
	Keywords        []string `json:"keywords"`
	Count           int      `json:"count"`
	Representatives []string `json:"representatives"`
}

type Metadata struct {
	SnapshotID       string   `json:"snapshot_id"`
	Articles         int      `json:"articles"`
	PublicationRange []string `json:"publication_range"`
	CollectedBefore  string   `json:"collected_before"`
	Methods          []string `json:"methods"`
	Topics           []Topic  `json:"topics"`
	ProfileNote      string   `json:"profile_note"`
	DateNote         string   `json:"date_note"`
}

type Hit struct {
	ID        string  `json:"id"`
	Score     float64 `json:"score"`
	Reason    string  `json:"reason"`
	Text      string  `json:"text"`
	TextKind  string  `json:"text_kind"`
	InputKind string  `json:"input_kind"`
	Topic     string  `json:"topic"`
}

type Page struct {
	Items            []Hit  `json:"items"`
	Method           string `json:"method"`
	SnapshotID       string `json:"snapshot_id"`
	Exhausted        bool   `json:"exhausted"`
	IgnoredViewedIDs int    `json:"ignored_viewed_ids"`
}

type Articles interface {
	GetByIDs(context.Context, []string) ([]domain.Article, error)
}

type Item struct {
	Hit
	Article domain.Article
}

type Result struct {
	Page
	Articles       []Item
	UnavailableIDs []string
}

type Service struct {
	endpoint string
	key      string
	client   *http.Client
	articles Articles
}

func New(endpoint, key string, articles Articles) (*Service, error) {
	u, err := url.Parse(endpoint)
	if err != nil || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") ||
		u.User != nil || u.RawQuery != "" || u.Fragment != "" {
		return nil, errors.New("recommender endpoint must be an http(s) URL without credentials or query")
	}
	if articles == nil {
		return nil, errors.New("recommendation articles must not be nil")
	}
	return &Service{
		endpoint: strings.TrimRight(endpoint, "/"), key: key, articles: articles,
		client: &http.Client{
			Timeout:       5 * time.Second,
			CheckRedirect: func(_ *http.Request, _ []*http.Request) error { return http.ErrUseLastResponse },
		},
	}, nil
}

func (s *Service) call(ctx context.Context, path string, input, output any) error {
	method := http.MethodGet
	var body io.Reader
	if input != nil {
		payload, err := json.Marshal(input)
		if err != nil {
			return fmt.Errorf("%w: encode request: %v", ErrInvalid, err)
		}
		method, body = http.MethodPost, bytes.NewReader(payload)
	}
	request, err := http.NewRequestWithContext(ctx, method, s.endpoint+path, body)
	if err != nil {
		return fmt.Errorf("%w: create request", ErrUnavailable)
	}
	request.Header.Set("Content-Type", "application/json")
	if s.key != "" {
		request.Header.Set("X-Recommender-Key", s.key)
	}
	response, err := s.client.Do(request)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrUnavailable, err)
	}
	defer response.Body.Close()
	switch response.StatusCode {
	case http.StatusOK:
	case http.StatusBadRequest:
		return ErrInvalid
	case http.StatusNotFound:
		return ErrNotIndexed
	default:
		return fmt.Errorf("%w: downstream status %d", ErrUnavailable, response.StatusCode)
	}
	decoder := json.NewDecoder(io.LimitReader(response.Body, (1<<20)+1))
	if err := decoder.Decode(output); err != nil {
		return fmt.Errorf("%w: invalid response: %v", ErrUnavailable, err)
	}
	if err := decoder.Decode(&struct{}{}); !errors.Is(err, io.EOF) {
		return fmt.Errorf("%w: trailing response data", ErrUnavailable)
	}
	return nil
}

func (s *Service) Metadata(ctx context.Context) (Metadata, error) {
	var metadata Metadata
	if err := s.call(ctx, "/v1/meta", nil, &metadata); err != nil {
		return Metadata{}, err
	}
	if metadata.SnapshotID == "" || metadata.Articles < 1 || len(metadata.Topics) == 0 {
		return Metadata{}, fmt.Errorf("%w: incomplete metadata", ErrUnavailable)
	}
	return metadata, nil
}

func (s *Service) Recommend(ctx context.Context, request Request) (Result, error) {
	if err := request.Validate(); err != nil {
		return Result{}, err
	}
	var page Page
	if err := s.call(ctx, "/v1/recommend", request, &page); err != nil {
		return Result{}, err
	}
	if len(page.Items) > 30 || page.SnapshotID == "" {
		return Result{}, fmt.Errorf("%w: invalid ranking response", ErrUnavailable)
	}
	ids := make([]string, 0, len(page.Items))
	seen := make(map[string]bool, len(page.Items))
	for _, hit := range page.Items {
		if domain.ValidateID(hit.ID) != nil || seen[hit.ID] || math.IsNaN(hit.Score) ||
			math.IsInf(hit.Score, 0) || len(hit.Text) > 12_000 {
			return Result{}, fmt.Errorf("%w: invalid ranking item", ErrUnavailable)
		}
		seen[hit.ID] = true
		ids = append(ids, hit.ID)
	}
	result := Result{Page: page, Articles: []Item{}, UnavailableIDs: []string{}}
	if len(ids) == 0 {
		return result, nil
	}
	articles, err := s.articles.GetByIDs(ctx, ids)
	if err != nil {
		return Result{}, fmt.Errorf("%w: hydrate articles: %v", ErrUnavailable, err)
	}
	byID := make(map[string]domain.Article, len(articles))
	for _, article := range articles {
		byID[article.ID] = article
	}
	for _, hit := range page.Items {
		article, ok := byID[hit.ID]
		if !ok {
			result.UnavailableIDs = append(result.UnavailableIDs, hit.ID)
			continue
		}
		result.Articles = append(result.Articles, Item{Hit: hit, Article: article})
	}
	if len(result.Articles) == 0 {
		return Result{}, fmt.Errorf("%w: no indexed articles remain in the selected database", ErrUnavailable)
	}
	return result, nil
}

func (r Request) Validate() error {
	if r.Limit < 0 || r.Limit > 30 || len(r.Liked) > 50 || len(r.Disliked) > 50 || len(r.Viewed) > 2000 {
		return ErrInvalid
	}
	if r.Method != "" && r.Method != "tfidf" && r.Method != "svd" && r.Method != "neural" {
		return ErrInvalid
	}
	if len(r.Topic) > 2 {
		return ErrInvalid
	}
	ids := append(append(append([]string{}, r.Liked...), r.Disliked...), r.Viewed...)
	if r.SeedID != "" {
		ids = append(ids, r.SeedID)
	}
	for _, id := range ids {
		if err := domain.ValidateID(id); err != nil {
			return ErrInvalid
		}
	}
	return nil
}
