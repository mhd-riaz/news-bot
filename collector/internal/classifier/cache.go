package classifier

import (
	"context"
	"log/slog"
	"sync"
	"time"
)

// TopicSource supplies cached reader-facing model topics without a network call.
type TopicSource interface {
	Topics() []Topic
}

// MetadataCache holds the latest valid metadata response for reader rendering.
type MetadataCache struct {
	mu     sync.RWMutex
	topics []Topic
}

// NewMetadataCache returns an empty cache that is safe for concurrent use.
func NewMetadataCache() *MetadataCache { return &MetadataCache{} }

// Refresh replaces the cache only after a complete metadata request succeeds.
func (c *MetadataCache) Refresh(ctx context.Context, client Client) error {
	metadata, err := client.Metadata(ctx)
	if err != nil {
		return err
	}
	c.mu.Lock()
	c.topics = append(c.topics[:0], metadata.Topics...)
	c.mu.Unlock()
	return nil
}

// Topics returns a stable copy of the most recently fetched topic list.
func (c *MetadataCache) Topics() []Topic {
	if c == nil {
		return nil
	}
	c.mu.RLock()
	defer c.mu.RUnlock()
	return append([]Topic(nil), c.topics...)
}

// Run refreshes metadata immediately and then at interval until ctx is cancelled.
func (c *MetadataCache) Run(ctx context.Context, client Client, interval time.Duration, logger *slog.Logger) {
	if logger == nil {
		logger = slog.Default()
	}
	refresh := func() {
		if err := c.Refresh(ctx, client); err != nil && ctx.Err() == nil {
			logger.WarnContext(ctx, "classifier metadata refresh failed", "error", err)
		}
	}
	refresh()
	ticker := time.NewTicker(interval)
	defer ticker.Stop()
	for {
		select {
		case <-ctx.Done():
			return
		case <-ticker.C:
			refresh()
		}
	}
}
