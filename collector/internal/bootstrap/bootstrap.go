// Package bootstrap reconciles a database with the files that describe it: the
// schema the code expects, and the source list in the seed file. The API runs
// it before it serves, so a deployment can never come up against an unmigrated
// database or a source list older than the image it is running.
package bootstrap

import (
	"bytes"
	"context"
	"errors"
	"fmt"
	"io"
	"log/slog"
	"net/http"
	"net/url"
	"os"
	"strings"
	"time"

	"go.mongodb.org/mongo-driver/v2/mongo"
	"gopkg.in/yaml.v3"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/mongodb"
)

// maxSourcesFileBytes caps the seed file. It is operator-supplied, but a runaway
// file should fail fast rather than be read into memory in full.
const maxSourcesFileBytes = 4 << 20

// sourcesFetchTimeout bounds reading a remote seed list.
const sourcesFetchTimeout = 30 * time.Second

// sourcesClient fetches a remote seed list. It is a variable so a test can
// point it at a server holding a self-signed certificate.
var sourcesClient = http.DefaultClient

// SourceEnsurer applies one source, keyed on its feed URL, and reports whether
// it had to create it. It is the only thing this package needs from the source
// service, so a test can supply it without a database.
type SourceEnsurer interface {
	Ensure(ctx context.Context, in domain.SourceInput) (*domain.Source, bool, error)
}

// Options selects what Run reconciles.
type Options struct {
	// Database is migrated when Migrate is set. Nil skips the migration.
	Database *mongo.Database

	// Migrate ensures the collections and indexes the code expects.
	Migrate bool

	// SourcesPath is the seed list to apply: a filesystem path, or an https URL
	// so the feed list can live outside the image and be picked up on a restart
	// instead of a rebuild. Empty skips the source sync, which is what a
	// deployment that manages sources only through the API wants.
	SourcesPath string

	// Sources applies the seed file. Nil skips the source sync.
	Sources SourceEnsurer

	Logger *slog.Logger
}

// Run applies everything Options selects. It is idempotent: a second run
// creates nothing and resets nothing, so it is safe on every start.
func Run(ctx context.Context, opts Options) error {
	logger := orDiscard(opts.Logger)

	if opts.Migrate && opts.Database != nil {
		if err := Migrate(ctx, opts.Database, logger); err != nil {
			return fmt.Errorf("migrate: %w", err)
		}
	}

	if opts.SourcesPath == "" || opts.Sources == nil {
		return nil
	}

	// Parsing and validating the whole file before the first write stops a typo
	// halfway down it from leaving the database half-applied.
	inputs, err := LoadSources(ctx, opts.SourcesPath)
	if err != nil {
		// A remote list that cannot be read leaves the stored sources in place,
		// which is degraded rather than broken, and a publisher of it being down
		// is not a reason to stop collecting. A local one is an operator mistake
		// worth failing on.
		if isRemote(opts.SourcesPath) {
			logger.Error("source sync skipped; the stored source list is unchanged",
				"sources_path", redactRef(opts.SourcesPath), "error", err)
			return nil
		}
		return err
	}
	if err := SyncSources(ctx, opts.Sources, inputs, logger); err != nil {
		return fmt.Errorf("sync sources from %q: %w", redactRef(opts.SourcesPath), err)
	}
	return nil
}

// Migrate creates the application's collections and indexes.
func Migrate(ctx context.Context, db *mongo.Database, logger *slog.Logger) error {
	logger = orDiscard(logger)

	created, err := mongodb.EnsureCollections(ctx, db)
	if err != nil {
		return err
	}
	logger.Info("collections ensured", "created", created, "total", len(mongodb.Collections()))

	// Superseded indexes go before the new ones: MongoDB refuses to recreate an
	// existing name with different keys.
	dropped, err := mongodb.DropObsoleteIndexes(ctx, db)
	if err != nil {
		return err
	}
	for collection, names := range dropped {
		logger.Info("obsolete indexes dropped", "collection", collection, "indexes", names)
	}

	applied, err := mongodb.EnsureIndexes(ctx, db)
	if err != nil {
		return err
	}
	for _, ci := range mongodb.IndexPlan() {
		logger.Info("indexes ensured", "collection", ci.Collection, "indexes", applied[ci.Collection])
	}
	return nil
}

// SyncSources applies every input, matching on feed URL. Sources already stored
// but absent from inputs are left alone: this reconciles, it does not prune.
func SyncSources(ctx context.Context, svc SourceEnsurer, inputs []domain.SourceInput, logger *slog.Logger) error {
	logger = orDiscard(logger)

	var created, updated int
	for _, in := range inputs {
		src, wasCreated, err := svc.Ensure(ctx, in)
		if err != nil {
			return fmt.Errorf("source %q: %w", in.FeedURL, err)
		}
		if wasCreated {
			created++
			logger.Info("source created", "id", src.ID, "feed_url", src.FeedURL)
		} else {
			updated++
		}
	}

	logger.Info("sources synced", "created", created, "updated", updated, "total", len(inputs))
	return nil
}

// LoadSources reads, parses and validates the seed list at ref, which is either
// a filesystem path or an https URL.
func LoadSources(ctx context.Context, ref string) ([]domain.SourceInput, error) {
	body, err := openSources(ctx, ref)
	if err != nil {
		return nil, err
	}
	defer func() { _ = body.Close() }()

	file, err := ParseSources(io.LimitReader(body, maxSourcesFileBytes))
	if err != nil {
		return nil, err
	}
	if len(file.Sources) == 0 {
		return nil, fmt.Errorf("seed file %q declares no sources", redactRef(ref))
	}
	return ValidateSources(file.Sources)
}

func openSources(ctx context.Context, ref string) (io.ReadCloser, error) {
	if !isRemote(ref) {
		f, err := os.Open(ref)
		if err != nil {
			return nil, fmt.Errorf("open seed file: %w", err)
		}
		return f, nil
	}

	// Plaintext is refused: this file decides which URLs the collector then
	// fetches, so anyone able to rewrite it in transit chooses that for us.
	if strings.HasPrefix(ref, "http://") {
		return nil, fmt.Errorf("seed file %q must be served over https", redactRef(ref))
	}

	fetchCtx, cancel := context.WithTimeout(ctx, sourcesFetchTimeout)
	defer cancel()

	req, err := http.NewRequestWithContext(fetchCtx, http.MethodGet, ref, nil)
	if err != nil {
		return nil, fmt.Errorf("seed file url: %w", err)
	}

	resp, err := sourcesClient.Do(req)
	if err != nil {
		return nil, fmt.Errorf("fetch seed file %q: %w", redactRef(ref), err)
	}
	if resp.StatusCode != http.StatusOK {
		_ = resp.Body.Close()
		return nil, fmt.Errorf("fetch seed file %q: unexpected status %s", redactRef(ref), resp.Status)
	}

	// The body is read inside the fetch timeout, so it must be drained before
	// this returns and cancel() fires.
	body, err := io.ReadAll(io.LimitReader(resp.Body, maxSourcesFileBytes))
	_ = resp.Body.Close()
	if err != nil {
		return nil, fmt.Errorf("read seed file %q: %w", redactRef(ref), err)
	}
	return io.NopCloser(bytes.NewReader(body)), nil
}

func isRemote(ref string) bool {
	return strings.HasPrefix(ref, "https://") || strings.HasPrefix(ref, "http://")
}

// redactRef drops any credential or query string before a reference reaches a
// log line or an error, because a private file is commonly fetched with a token
// in the URL.
func redactRef(ref string) string {
	if !isRemote(ref) {
		return ref
	}
	u, err := url.Parse(ref)
	if err != nil {
		return "<unparsable seed file url>"
	}
	u.User = nil
	u.RawQuery = ""
	u.Fragment = ""
	return u.String()
}

// SourcesFile is the on-disk seed format.
type SourcesFile struct {
	Sources []Source `yaml:"sources"`
}

// Source mirrors domain.SourceInput. Optional fields are pointers so an omitted
// key keeps the stored value instead of resetting it to a default.
type Source struct {
	Name                 string `yaml:"name"`
	FeedURL              string `yaml:"feed_url"`
	Type                 string `yaml:"type"`
	Language             string `yaml:"language"`
	Country              string `yaml:"country"`
	State                string `yaml:"state"`
	City                 string `yaml:"city"`
	Enabled              *bool  `yaml:"enabled"`
	Priority             *int   `yaml:"priority"`
	FetchIntervalSeconds *int   `yaml:"fetch_interval_seconds"`
}

// Input converts one entry into the service's input type.
func (s Source) Input() domain.SourceInput {
	return domain.SourceInput{
		Name:                 s.Name,
		FeedURL:              s.FeedURL,
		Type:                 domain.SourceType(s.Type),
		Language:             s.Language,
		Country:              s.Country,
		State:                s.State,
		City:                 s.City,
		Enabled:              s.Enabled,
		Priority:             s.Priority,
		FetchIntervalSeconds: s.FetchIntervalSeconds,
	}
}

// ParseSources parses the seed format, rejecting unknown keys so a typo fails
// fast rather than being silently ignored.
func ParseSources(r io.Reader) (*SourcesFile, error) {
	var file SourcesFile
	dec := yaml.NewDecoder(r)
	dec.KnownFields(true)
	if err := dec.Decode(&file); err != nil && !errors.Is(err, io.EOF) {
		return nil, fmt.Errorf("parse seed file: %w", err)
	}
	return &file, nil
}

// ValidateSources converts and validates every entry, reporting the file
// position of each failure so an operator can find it.
func ValidateSources(sources []Source) ([]domain.SourceInput, error) {
	inputs := make([]domain.SourceInput, 0, len(sources))
	seen := make(map[string]int, len(sources))
	var errs []error

	for i, s := range sources {
		in := s.Input()
		if _, err := domain.NewSource(in, time.Now()); err != nil {
			errs = append(errs, fmt.Errorf("sources[%d] (%s): %w", i, s.Name, err))
			continue
		}
		if first, duplicate := seen[s.FeedURL]; duplicate {
			errs = append(errs, fmt.Errorf("sources[%d]: feed_url %q already declared at sources[%d]", i, s.FeedURL, first))
			continue
		}
		seen[s.FeedURL] = i
		inputs = append(inputs, in)
	}

	if len(errs) > 0 {
		return nil, errors.Join(errs...)
	}
	return inputs, nil
}

func orDiscard(logger *slog.Logger) *slog.Logger {
	if logger == nil {
		return slog.New(slog.DiscardHandler)
	}
	return logger
}
