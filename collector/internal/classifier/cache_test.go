package classifier

import (
	"context"
	"log/slog"
	"sync"
	"testing"
	"time"
)

type metadataClient struct{ metadata Metadata }

func (c metadataClient) Classify(context.Context, []Item) ([]Result, error) { return nil, nil }
func (c metadataClient) Metadata(context.Context) (Metadata, error)         { return c.metadata, nil }
func (c metadataClient) BatchSize() int                                     { return 0 }

func TestMetadataCacheRefreshesAndReturnsACopy(t *testing.T) {
	cache := NewMetadataCache()
	if err := cache.Refresh(t.Context(), metadataClient{metadata: Metadata{Topics: []Topic{{ID: "politics", Label: "Politics"}}}}); err != nil {
		t.Fatalf("Refresh: %v", err)
	}
	topics := cache.Topics()
	topics[0].Label = "changed"
	if got := cache.Topics()[0].Label; got != "Politics" {
		t.Errorf("cache was mutated through returned slice: %q", got)
	}
}

// countingClient counts Metadata calls so a test can wait for Run to have
// ticked at least once beyond its initial, synchronous refresh.
type countingClient struct {
	mu       sync.Mutex
	metadata Metadata
	calls    int
}

func (c *countingClient) Classify(context.Context, []Item) ([]Result, error) { return nil, nil }
func (c *countingClient) BatchSize() int                                     { return 0 }

func (c *countingClient) Metadata(context.Context) (Metadata, error) {
	c.mu.Lock()
	defer c.mu.Unlock()
	c.calls++
	return c.metadata, nil
}

func (c *countingClient) count() int {
	c.mu.Lock()
	defer c.mu.Unlock()
	return c.calls
}

func TestMetadataCacheRunRefreshesOnIntervalAndStopsOnCancel(t *testing.T) {
	client := &countingClient{metadata: Metadata{Topics: []Topic{{ID: "politics", Label: "Politics"}}}}
	cache := NewMetadataCache()
	ctx, cancel := context.WithCancel(t.Context())

	done := make(chan struct{})
	go func() {
		defer close(done)
		cache.Run(ctx, client, time.Millisecond, slog.New(slog.DiscardHandler))
	}()

	deadline := time.Now().Add(time.Second)
	for client.count() < 2 && time.Now().Before(deadline) {
		time.Sleep(time.Millisecond)
	}
	if client.count() < 2 {
		t.Fatalf("client refreshed %d times in one second, want at least 2 (initial plus one tick)", client.count())
	}
	if got := cache.Topics(); len(got) != 1 || got[0].ID != "politics" {
		t.Errorf("Topics() = %+v, want the refreshed topic", got)
	}

	cancel()
	select {
	case <-done:
	case <-time.After(time.Second):
		t.Fatal("Run did not return after context cancellation")
	}
}
