package mongodb

import (
	"strings"
	"testing"
	"time"
)

func TestMongoConnectionIdlePolicyUsesNativeDriverOption(t *testing.T) {
	t.Parallel()
	for _, sample := range []struct {
		name string
		uri  string
		idle time.Duration
		want time.Duration
	}{
		{"default", "mongodb://example.invalid", 0, 0},
		{"preserve URI", "mongodb://example.invalid/?maxIdleTimeMS=45000", 0, 45 * time.Second},
		{"configured", "mongodb://example.invalid", time.Minute, time.Minute},
		{"override URI", "mongodb://example.invalid/?maxIdleTimeMS=45000", time.Minute, time.Minute},
	} {
		t.Run(sample.name, func(t *testing.T) {
			t.Parallel()
			options := clientOptions(Settings{
				URI: sample.uri, MaxConnIdleTime: sample.idle, MaxPoolSize: 50,
			})
			if err := options.Validate(); err != nil {
				t.Fatal(err)
			}
			if options.MaxConnIdleTime == nil {
				if sample.want != 0 {
					t.Fatalf("idle option unset, want %s", sample.want)
				}
			} else if *options.MaxConnIdleTime != sample.want {
				t.Fatalf("idle option = %s, want %s", *options.MaxConnIdleTime, sample.want)
			}
		})
	}
}

func TestMongoConnectRejectsNegativeIdleLimitBeforeConnecting(t *testing.T) {
	t.Parallel()
	_, err := Connect(Settings{URI: "mongodb://example.invalid", Database: "news", MaxConnIdleTime: -time.Second})
	if err == nil || !strings.Contains(err.Error(), "idle time") {
		t.Fatalf("negative idle limit accepted: %v", err)
	}
}
