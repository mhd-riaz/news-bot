package app

import (
	"log/slog"

	driver "go.mongodb.org/mongo-driver/v2/mongo"

	"github.com/riaz/newscollector/internal/config"
	"github.com/riaz/newscollector/internal/extract"
	"github.com/riaz/newscollector/internal/httpclient"
	"github.com/riaz/newscollector/internal/ratelimit"
	mongorepo "github.com/riaz/newscollector/internal/repository/mongo"
	"github.com/riaz/newscollector/internal/robots"
	"github.com/riaz/newscollector/internal/service"
)

// NewEnrichmentService wires an enrichment service against db.
//
// It builds its own HTTP client and rate limiter rather than sharing the
// collector's: collection paces itself through each source's own
// fetch_interval, typically many minutes apart, while enrichment paces itself
// against the same host every few seconds. The two policies are different
// enough that unifying them would mean bending one to fit the other for no
// present benefit — but they do reach the same hosts, so if that combined
// load ever needs a single ceiling, this is where the two would be joined.
func NewEnrichmentService(cfg *config.Config, db *driver.Database, clock service.Clock, logger *slog.Logger) *service.EnrichmentService {
	client := httpclient.New(httpclient.Config{
		Timeout:              cfg.Scraper.RequestTimeout,
		MaxResponseBytes:     cfg.Scraper.MaxResponseBytes,
		UserAgent:            cfg.Scraper.UserAgent,
		AllowPrivateNetworks: cfg.Scraper.AllowPrivateNetworks,
	})

	limiter := ratelimit.New(ratelimit.Config{
		MinInterval:      cfg.Scraper.PerHostDelay,
		FailureThreshold: cfg.Scraper.CircuitFailureThreshold,
		OpenFor:          cfg.Scraper.CircuitOpenFor,
	})

	robotsChecker := robots.New(client, robots.Config{
		Agent: robotsAgent(cfg.Scraper.UserAgent),
		TTL:   cfg.Scraper.RobotsCacheTTL,
	})

	return service.NewEnrichmentService(service.EnrichmentDeps{
		Articles:      mongorepo.NewArticleRepository(db),
		Robots:        robotsChecker,
		Limiter:       limiter,
		Fetcher:       client,
		Extractor:     extract.New(cfg.Scraper.MinContentWords),
		MaxAttempts:   cfg.Scraper.MaxAttempts,
		RetryBase:     cfg.Scraper.RetryBase,
		MaxArticleAge: cfg.Scraper.MaxArticleAge,
		ClaimTTL:      cfg.Scraper.ClaimTTL,
		Clock:         clock,
		Logger:        logger,
	})
}

// robotsAgent extracts the bare product token robots.txt groups are matched
// against, from a full User-Agent string such as
// "news-collector/1.0 (+https://...)". robots.txt is keyed on the product
// name alone, so passing the full header here would silently match nothing
// but a publisher's wildcard group.
func robotsAgent(userAgent string) string {
	for i, r := range userAgent {
		if r == '/' || r == ' ' {
			return userAgent[:i]
		}
	}
	return userAgent
}
