package classifier

import (
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"io"
	"net/http"
	"net/url"
	"strings"
	"time"
)

const (
	maxRequestBytes  = 2 << 20
	maxResponseBytes = 1 << 20
)

// HTTPClient is a bounded, redirect-free client for the internal classifier.
type HTTPClient struct {
	endpoint  *url.URL
	client    *http.Client
	apiKey    string
	batchSize int
}

// NewHTTPClient validates the service endpoint and configures request limits.
func NewHTTPClient(endpoint string, timeout time.Duration, batchSize int, apiKey string) (*HTTPClient, error) {
	u, err := url.Parse(endpoint)
	if err != nil || u.Scheme == "" || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") {
		return nil, fmt.Errorf("%w: %q", ErrInvalidEndpoint, endpoint)
	}
	if timeout <= 0 || batchSize < 1 {
		return nil, fmt.Errorf("%w: non-positive timeout or batch size", ErrInvalidEndpoint)
	}
	return &HTTPClient{
		endpoint: u,
		client: &http.Client{
			Timeout:       timeout,
			CheckRedirect: func(*http.Request, []*http.Request) error { return http.ErrUseLastResponse },
		},
		apiKey:    apiKey,
		batchSize: batchSize,
	}, nil
}

// Classify sends one valid bounded batch and verifies every returned item.
func (c *HTTPClient) Classify(ctx context.Context, items []Item) ([]Result, error) {
	if len(items) == 0 || len(items) > c.batchSize {
		return nil, fmt.Errorf("%w: batch size %d", ErrBadResponse, len(items))
	}
	for _, item := range items {
		if strings.TrimSpace(item.ID) == "" {
			return nil, fmt.Errorf("%w: empty item id", ErrBadResponse)
		}
	}

	body, err := json.Marshal(struct {
		Items []Item `json:"items"`
	}{Items: items})
	if err != nil {
		return nil, fmt.Errorf("classifier: marshal request: %w", err)
	}
	if len(body) > maxRequestBytes {
		return nil, ErrRequestTooLarge
	}

	var response classifyResponse
	if err := c.request(ctx, http.MethodPost, "/v1/classify", body, &response); err != nil {
		return nil, err
	}
	if strings.TrimSpace(response.ModelVersion) == "" || len(response.Items) != len(items) {
		return nil, fmt.Errorf("%w: missing model version or mismatched item count", ErrBadResponse)
	}

	results := make([]Result, len(items))
	seen := make(map[string]struct{}, len(items))
	for index, result := range response.Items {
		if result.Error != "" || result.ID != items[index].ID || strings.TrimSpace(result.Topic) == "" || result.Confidence < 0 || result.Confidence > 1 {
			return nil, fmt.Errorf("%w: invalid result at index %d", ErrBadResponse, index)
		}
		if _, duplicate := seen[result.ID]; duplicate {
			return nil, fmt.Errorf("%w: duplicate result id %q", ErrBadResponse, result.ID)
		}
		seen[result.ID] = struct{}{}
		if result.Filed && result.Topic == "unsorted" || !result.Filed && result.Topic != "unsorted" {
			return nil, fmt.Errorf("%w: invalid filed/topic combination", ErrBadResponse)
		}
		results[index] = Result{
			ID: result.ID, Topic: result.Topic, Confidence: result.Confidence,
			Filed: result.Filed, ModelVersion: response.ModelVersion,
		}
	}
	return results, nil
}

// BatchSize reports the batch limit this client was configured with.
func (c *HTTPClient) BatchSize() int { return c.batchSize }

// Metadata returns the current model version and canonical reader topics.
func (c *HTTPClient) Metadata(ctx context.Context) (Metadata, error) {
	var response metadataResponse
	if err := c.request(ctx, http.MethodGet, "/v1/meta", nil, &response); err != nil {
		return Metadata{}, err
	}
	if strings.TrimSpace(response.ModelVersion) == "" || response.Cut < 0 || response.Cut > 1 {
		return Metadata{}, fmt.Errorf("%w: invalid metadata", ErrBadResponse)
	}
	metadata := Metadata{ModelVersion: response.ModelVersion, Cut: response.Cut, Topics: make([]Topic, len(response.Topics))}
	seen := make(map[string]struct{}, len(response.Topics))
	for index, topic := range response.Topics {
		if strings.TrimSpace(topic.ID) == "" || strings.TrimSpace(topic.Label) == "" {
			return Metadata{}, fmt.Errorf("%w: blank topic", ErrBadResponse)
		}
		if _, duplicate := seen[topic.ID]; duplicate {
			return Metadata{}, fmt.Errorf("%w: duplicate topic %q", ErrBadResponse, topic.ID)
		}
		seen[topic.ID] = struct{}{}
		metadata.Topics[index] = Topic{ID: topic.ID, Label: topic.Label}
	}
	return metadata, nil
}

func (c *HTTPClient) request(ctx context.Context, method, path string, body []byte, target any) error {
	u := c.endpoint.ResolveReference(&url.URL{Path: path})
	request, err := http.NewRequestWithContext(ctx, method, u.String(), bytes.NewReader(body))
	if err != nil {
		return fmt.Errorf("classifier: create request: %w", err)
	}
	request.Header.Set("Accept", "application/json")
	if body != nil {
		request.Header.Set("Content-Type", "application/json")
	}
	if c.apiKey != "" {
		request.Header.Set("X-Classifier-Key", c.apiKey)
	}

	response, err := c.client.Do(request)
	if err != nil {
		return fmt.Errorf("%w: %v", ErrService, err)
	}
	defer response.Body.Close()
	if response.StatusCode == http.StatusUnauthorized || response.StatusCode == http.StatusForbidden {
		return fmt.Errorf("%w: status %d", ErrUnauthenticated, response.StatusCode)
	}
	if response.StatusCode < http.StatusOK || response.StatusCode >= http.StatusMultipleChoices {
		return fmt.Errorf("%w: status %d", ErrService, response.StatusCode)
	}
	if !strings.HasPrefix(response.Header.Get("Content-Type"), "application/json") {
		return fmt.Errorf("%w: content type %q", ErrBadResponse, response.Header.Get("Content-Type"))
	}

	limited := io.LimitReader(response.Body, maxResponseBytes+1)
	data, err := io.ReadAll(limited)
	if err != nil {
		return fmt.Errorf("classifier: read response: %w", err)
	}
	if len(data) > maxResponseBytes {
		return ErrResponseTooLarge
	}
	if err := json.Unmarshal(data, target); err != nil {
		return fmt.Errorf("%w: %v", ErrBadResponse, err)
	}
	return nil
}

type classifyResponse struct {
	ModelVersion string           `json:"model_version"`
	Items        []classifyResult `json:"items"`
}

type classifyResult struct {
	ID         string  `json:"id"`
	Topic      string  `json:"topic"`
	Confidence float64 `json:"confidence"`
	Filed      bool    `json:"filed"`
	Error      string  `json:"error"`
}

type metadataResponse struct {
	ModelVersion string  `json:"model_version"`
	Cut          float64 `json:"cut"`
	Topics       []struct {
		ID    string `json:"id"`
		Label string `json:"label"`
	} `json:"topics"`
}
