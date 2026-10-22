// Package config loads application configuration from three layers, in
// increasing order of precedence: built-in defaults, an optional YAML file, and
// environment variables prefixed with EnvPrefix.
package config

import (
	"errors"
	"fmt"
	"io"
	"net"
	"net/url"
	"os"
	"strconv"
	"strings"
	"time"
	"unicode"

	"gopkg.in/yaml.v3"
)

// EnvPrefix is prepended to every environment variable that overrides a config value.
const EnvPrefix = "NEWS_"

// DefaultPath is the config file location used when none is supplied.
const DefaultPath = "configs/config.yaml"

// DefaultSourcesPath is the seed file location used when none is supplied.
const DefaultSourcesPath = "configs/sources.yaml"

// Config is the fully resolved application configuration.
type Config struct {
	App        App        `yaml:"app"`
	Server     Server     `yaml:"server"`
	Auth       Auth       `yaml:"auth"`
	Web        Web        `yaml:"web"`
	Mongo      Mongo      `yaml:"mongo"`
	Bootstrap  Bootstrap  `yaml:"bootstrap"`
	Collector  Collector  `yaml:"collector"`
	Scheduler  Scheduler  `yaml:"scheduler"`
	Scraper    Scraper    `yaml:"scraper"`
	Classifier Classifier `yaml:"classifier"`
	Logging    Logging    `yaml:"logging"`
}

// App holds process identity settings.
type App struct {
	Name        string `yaml:"name"`
	Environment string `yaml:"environment"`
}

// Bootstrap holds what the API reconciles against the database before it
// serves. It exists so a deployment cannot come up against an unmigrated
// database or a source list older than the image it is running, which is what
// happens whenever a one-shot migrate or seed container is skipped.
type Bootstrap struct {
	// Migrate ensures the collections and indexes the code expects.
	Migrate bool `yaml:"migrate"`

	// SourcesPath is the seed list applied at startup, matched on feed_url and
	// patched rather than replaced, so a value tuned through the API survives.
	// It is a filesystem path, or an https URL so the feed list can live outside
	// the image and be picked up by a restart instead of a rebuild. Empty
	// disables the sync, which is what a deployment that manages sources only
	// through the API wants.
	SourcesPath string `yaml:"sources_path"`

	// Timeout bounds the whole reconciliation. Index builds on a large database
	// are the slow part, so it is generous next to the other timeouts here.
	Timeout time.Duration `yaml:"timeout"`
}

// Server holds HTTP listener settings.
type Server struct {
	Host              string        `yaml:"host"`
	Port              int           `yaml:"port"`
	ReadHeaderTimeout time.Duration `yaml:"read_header_timeout"`
	ReadTimeout       time.Duration `yaml:"read_timeout"`
	WriteTimeout      time.Duration `yaml:"write_timeout"`
	IdleTimeout       time.Duration `yaml:"idle_timeout"`
	ShutdownTimeout   time.Duration `yaml:"shutdown_timeout"`
	MaxHeaderBytes    int           `yaml:"max_header_bytes"`
}

// Auth holds the credentials that guard the management and query APIs. The
// credential fields carry no YAML tag on purpose: secrets are accepted only
// from the environment (or the .env file that feeds it), so a checked-in config
// file can never hold one, and a key placed there fails the load instead of
// being silently honoured.
type Auth struct {
	Enabled      bool   `yaml:"enabled"`
	APIKeyHeader string `yaml:"api_key_header"`

	// APIKeys holds every currently accepted key. It is a list so a key can be
	// rotated by adding the replacement, moving clients over, then dropping the
	// old one — none of which needs a window where the API is unprotected.
	APIKeys []string `yaml:"-"`

	BasicUsername string `yaml:"-"`
	BasicPassword string `yaml:"-"`
}

// Web holds the reader-facing pages. They share the API's port, its process
// and its credentials; only whether they are served at all is separate.
type Web struct {
	// Enabled serves the pages. Off leaves the process a pure API.
	Enabled bool `yaml:"enabled"`

	// PageSize is how many cards one feed page carries. It also sets how far
	// apart consecutive pages' feed positions are, so changing it changes the
	// meaning of position_in_feed in the telemetry from that moment on.
	PageSize int `yaml:"page_size"`
}

// Mongo holds MongoDB connection settings.
type Mongo struct {
	URI                    string        `yaml:"uri"`
	Database               string        `yaml:"database"`
	ConnectTimeout         time.Duration `yaml:"connect_timeout"`
	ServerSelectionTimeout time.Duration `yaml:"server_selection_timeout"`
	OperationTimeout       time.Duration `yaml:"operation_timeout"`
	MaxPoolSize            uint64        `yaml:"max_pool_size"`
	MinPoolSize            uint64        `yaml:"min_pool_size"`
}

// Collector holds the settings for fetching and parsing feeds.
type Collector struct {
	UserAgent        string        `yaml:"user_agent"`
	RequestTimeout   time.Duration `yaml:"request_timeout"`
	MaxResponseBytes int64         `yaml:"max_response_bytes"`
	MaxRedirects     int           `yaml:"max_redirects"`
	MaxItemsPerFeed  int           `yaml:"max_items_per_feed"`

	// AllowPrivateNetworks turns off the outbound address guard so a feed can be
	// served from localhost during development. It is refused outright in
	// production, because with it on any operator who can register a feed URL can
	// make the collector read internal services.
	AllowPrivateNetworks bool `yaml:"allow_private_networks"`
}

// Scheduler holds the settings of the background collection loop.
type Scheduler struct {
	// Enabled turns the loop off without removing its configuration, which is
	// what an operator wants while investigating a misbehaving publisher.
	Enabled bool `yaml:"enabled"`

	// Interval is how often due sources are looked for.
	Interval time.Duration `yaml:"interval"`

	// BatchSize bounds one tick's work.
	BatchSize int `yaml:"batch_size"`

	// MaxConcurrent bounds how many collections run at the same time.
	MaxConcurrent int `yaml:"max_concurrent"`

	// LockTTL is how long a source lease is held. It must outlast a collection,
	// or a second collector could start one while the first is still running.
	LockTTL time.Duration `yaml:"lock_ttl"`
}

// Logging holds structured-logging settings.
type Logging struct {
	Level  string `yaml:"level"`
	Format string `yaml:"format"`
}

// Scraper holds the settings for the full-text enrichment stage: fetching an
// article's own page for the sources whose feed sends only a teaser.
type Scraper struct {
	// Enabled turns the enrichment scheduler off without removing its
	// configuration, mirroring Scheduler.Enabled.
	Enabled bool `yaml:"enabled"`

	// Interval is how often the backlog is looked at.
	Interval time.Duration `yaml:"interval"`

	// BatchSize bounds one tick's work.
	BatchSize int `yaml:"batch_size"`

	// UserAgent identifies this collector when fetching article pages and
	// robots.txt files, distinct from collector.user_agent so the two stages'
	// traffic can be told apart in a publisher's own logs if it ever matters.
	UserAgent string `yaml:"user_agent"`

	// RequestTimeout bounds one article fetch.
	RequestTimeout time.Duration `yaml:"request_timeout"`

	// MaxResponseBytes caps one article page. Pages carry more markup than a
	// feed document, so this is deliberately looser than
	// collector.max_response_bytes.
	MaxResponseBytes int64 `yaml:"max_response_bytes"`

	// AllowPrivateNetworks mirrors collector.allow_private_networks for article
	// fetches, and is refused the same way outside development.
	AllowPrivateNetworks bool `yaml:"allow_private_networks"`

	// MinContentWords is the shortest extraction accepted as an article; a
	// shorter result is treated as a failed attempt rather than being stored.
	MinContentWords int `yaml:"min_content_words"`

	// MaxAttempts bounds how many times one article is tried before it is
	// abandoned.
	MaxAttempts int `yaml:"max_attempts"`

	// RetryBase is the wait after a first transient failure, doubling per
	// attempt up to a fixed cap.
	RetryBase time.Duration `yaml:"retry_base"`

	// MaxArticleAge drops articles published before it from the backlog. Zero
	// means no bound, which a backfill wants; a steady-state deployment wants
	// one, or the backlog grows with every publisher that goes quiet for a week.
	MaxArticleAge time.Duration `yaml:"max_article_age"`

	// PerHostDelay is the minimum gap between two article requests to the same
	// host. A publisher's own Crawl-delay overrides it when longer.
	PerHostDelay time.Duration `yaml:"per_host_delay"`

	// CircuitFailureThreshold is how many consecutive failures rest a host, and
	// CircuitOpenFor is how long the rest lasts. Resting a host protects the
	// rest of its queued articles from a publisher's temporary outage: without
	// it, an hour of 503s would spend every one of them their whole attempt
	// budget and mark them all permanently failed.
	CircuitFailureThreshold int           `yaml:"circuit_failure_threshold"`
	CircuitOpenFor          time.Duration `yaml:"circuit_open_for"`

	// RobotsCacheTTL is how long one publisher's robots.txt rules are reused
	// before they are read again.
	RobotsCacheTTL time.Duration `yaml:"robots_cache_ttl"`

	// ClaimTTL is how long an article may sit claimed before it is assumed
	// abandoned and returned to the backlog. It must comfortably outlast one
	// attempt, or a fetch that is merely slow gets reclaimed as if it were dead.
	ClaimTTL time.Duration `yaml:"claim_ttl"`
}

// Classifier holds the settings for the internal model-classification service.
type Classifier struct {
	Enabled                 bool          `yaml:"enabled"`
	Endpoint                string        `yaml:"endpoint"`
	Timeout                 time.Duration `yaml:"timeout"`
	BatchSize               int           `yaml:"batch_size"`
	MaxAttempts             int           `yaml:"max_attempts"`
	ClaimTTL                time.Duration `yaml:"claim_ttl"`
	MetadataRefreshInterval time.Duration `yaml:"metadata_refresh_interval"`
	APIKey                  string        `yaml:"-"`
}

// Address returns the host:port the HTTP server should listen on.
func (s Server) Address() string {
	return net.JoinHostPort(s.Host, strconv.Itoa(s.Port))
}

// RedactedURI returns the MongoDB URI with any embedded credentials replaced,
// so the connection target can be logged without leaking a password.
func (m Mongo) RedactedURI() string {
	u, err := url.Parse(m.URI)
	if err != nil {
		return "<unparsable mongo uri>"
	}
	if u.User != nil {
		u.User = url.User("redacted")
	}
	return u.String()
}

// Default returns the built-in configuration used as the base of every load.
func Default() *Config {
	return &Config{
		App: App{
			Name:        "news-collector",
			Environment: "development",
		},
		Server: Server{
			Host:              "0.0.0.0",
			Port:              8080,
			ReadHeaderTimeout: 5 * time.Second,
			ReadTimeout:       15 * time.Second,
			WriteTimeout:      30 * time.Second,
			IdleTimeout:       60 * time.Second,
			ShutdownTimeout:   15 * time.Second,
			MaxHeaderBytes:    1 << 20,
		},
		Auth: Auth{
			// Off in the built-in defaults so a bare `go run` works, but the
			// shipped config file turns it on and validation refuses to leave it
			// off in production, so nothing reaches a server unguarded.
			Enabled:      false,
			APIKeyHeader: DefaultAPIKeyHeader,
		},
		Web: Web{
			Enabled:  true,
			PageSize: 30,
		},
		Mongo: Mongo{
			URI:                    "mongodb://localhost:27017",
			Database:               "news",
			ConnectTimeout:         10 * time.Second,
			ServerSelectionTimeout: 10 * time.Second,
			OperationTimeout:       30 * time.Second,
			MaxPoolSize:            50,
			MinPoolSize:            0,
		},
		Bootstrap: Bootstrap{
			Migrate:     true,
			SourcesPath: DefaultSourcesPath,
			Timeout:     2 * time.Minute,
		},
		Collector: Collector{
			UserAgent:            "news-collector/1.0 (+https://github.com/riaz/newscollector)",
			RequestTimeout:       20 * time.Second,
			MaxResponseBytes:     10 << 20,
			MaxRedirects:         5,
			MaxItemsPerFeed:      500,
			AllowPrivateNetworks: false,
		},
		Scheduler: Scheduler{
			Enabled:       true,
			Interval:      60 * time.Second,
			BatchSize:     50,
			MaxConcurrent: 4,
			LockTTL:       5 * time.Minute,
		},
		Scraper: Scraper{
			Enabled:                 true,
			Interval:                5 * time.Minute,
			BatchSize:               50,
			UserAgent:               "news-collector/1.0 (+https://github.com/riaz/newscollector)",
			RequestTimeout:          20 * time.Second,
			MaxResponseBytes:        20 << 20,
			AllowPrivateNetworks:    false,
			MinContentWords:         80,
			MaxAttempts:             3,
			RetryBase:               15 * time.Minute,
			MaxArticleAge:           30 * 24 * time.Hour,
			PerHostDelay:            2 * time.Second,
			CircuitFailureThreshold: 3,
			CircuitOpenFor:          15 * time.Minute,
			RobotsCacheTTL:          24 * time.Hour,
			ClaimTTL:                10 * time.Minute,
		},
		Classifier: Classifier{
			Enabled:                 false,
			Endpoint:                "http://classifier:8000",
			Timeout:                 10 * time.Second,
			BatchSize:               50,
			MaxAttempts:             3,
			ClaimTTL:                5 * time.Minute,
			MetadataRefreshInterval: time.Hour,
		},
		Logging: Logging{
			Level:  "info",
			Format: "json",
		},
	}
}

// Option adjusts which checks a load or validation performs.
type Option func(*options)

type options struct {
	skipAuth bool
}

// SkipAuthValidation drops the auth checks. It is for the binaries that never
// serve HTTP — migrate and seed — where auth settings are not theirs to hold,
// so an API-server-only setting such as a deliberately disabled auth must not
// stop a migration. The API server never passes it, so a production server
// still refuses to start with auth off.
func SkipAuthValidation(o *options) { o.skipAuth = true }

func newOptions(opts []Option) options {
	var o options
	for _, apply := range opts {
		apply(&o)
	}
	return o
}

// Load resolves configuration from defaults, the YAML file at path when it is
// non-empty, and environment variables, then validates the result. A path that
// does not exist is reported as an error; pass "" to skip the file layer.
func Load(path string, opts ...Option) (*Config, error) {
	cfg := Default()

	if path != "" {
		if err := cfg.loadFile(path); err != nil {
			return nil, err
		}
	}
	if err := cfg.applyEnv(); err != nil {
		return nil, err
	}
	if err := cfg.Validate(opts...); err != nil {
		return nil, fmt.Errorf("invalid configuration: %w", err)
	}
	return cfg, nil
}

func (c *Config) loadFile(path string) error {
	f, err := os.Open(path)
	if err != nil {
		return fmt.Errorf("open config file: %w", err)
	}
	defer func() { _ = f.Close() }()

	dec := yaml.NewDecoder(f)
	dec.KnownFields(true) // reject typo'd keys instead of silently ignoring them
	if err := dec.Decode(c); err != nil && !errors.Is(err, io.EOF) {
		return fmt.Errorf("parse config file %q: %w", path, err)
	}
	return nil
}

func (c *Config) applyEnv() error {
	b := &envBinder{}

	b.str("APP_NAME", &c.App.Name)
	b.str("APP_ENVIRONMENT", &c.App.Environment)

	b.str("SERVER_HOST", &c.Server.Host)
	b.integer("SERVER_PORT", &c.Server.Port)
	b.duration("SERVER_READ_HEADER_TIMEOUT", &c.Server.ReadHeaderTimeout)
	b.duration("SERVER_READ_TIMEOUT", &c.Server.ReadTimeout)
	b.duration("SERVER_WRITE_TIMEOUT", &c.Server.WriteTimeout)
	b.duration("SERVER_IDLE_TIMEOUT", &c.Server.IdleTimeout)
	b.duration("SERVER_SHUTDOWN_TIMEOUT", &c.Server.ShutdownTimeout)
	b.integer("SERVER_MAX_HEADER_BYTES", &c.Server.MaxHeaderBytes)

	b.boolean("AUTH_ENABLED", &c.Auth.Enabled)
	b.str("AUTH_API_KEY_HEADER", &c.Auth.APIKeyHeader)
	b.list("AUTH_API_KEYS", &c.Auth.APIKeys)
	b.str("AUTH_BASIC_USERNAME", &c.Auth.BasicUsername)
	b.str("AUTH_BASIC_PASSWORD", &c.Auth.BasicPassword)

	b.boolean("WEB_ENABLED", &c.Web.Enabled)
	b.integer("WEB_PAGE_SIZE", &c.Web.PageSize)

	b.str("MONGO_URI", &c.Mongo.URI)
	b.str("MONGO_DATABASE", &c.Mongo.Database)
	b.duration("MONGO_CONNECT_TIMEOUT", &c.Mongo.ConnectTimeout)
	b.duration("MONGO_SERVER_SELECTION_TIMEOUT", &c.Mongo.ServerSelectionTimeout)
	b.duration("MONGO_OPERATION_TIMEOUT", &c.Mongo.OperationTimeout)
	b.unsigned("MONGO_MAX_POOL_SIZE", &c.Mongo.MaxPoolSize)
	b.unsigned("MONGO_MIN_POOL_SIZE", &c.Mongo.MinPoolSize)

	b.boolean("BOOTSTRAP_MIGRATE", &c.Bootstrap.Migrate)
	b.str("BOOTSTRAP_SOURCES_PATH", &c.Bootstrap.SourcesPath)
	b.duration("BOOTSTRAP_TIMEOUT", &c.Bootstrap.Timeout)

	b.str("COLLECTOR_USER_AGENT", &c.Collector.UserAgent)
	b.duration("COLLECTOR_REQUEST_TIMEOUT", &c.Collector.RequestTimeout)
	b.integer64("COLLECTOR_MAX_RESPONSE_BYTES", &c.Collector.MaxResponseBytes)
	b.integer("COLLECTOR_MAX_REDIRECTS", &c.Collector.MaxRedirects)
	b.integer("COLLECTOR_MAX_ITEMS_PER_FEED", &c.Collector.MaxItemsPerFeed)
	b.boolean("COLLECTOR_ALLOW_PRIVATE_NETWORKS", &c.Collector.AllowPrivateNetworks)

	b.boolean("SCHEDULER_ENABLED", &c.Scheduler.Enabled)
	b.duration("SCHEDULER_INTERVAL", &c.Scheduler.Interval)
	b.integer("SCHEDULER_BATCH_SIZE", &c.Scheduler.BatchSize)
	b.integer("SCHEDULER_MAX_CONCURRENT", &c.Scheduler.MaxConcurrent)
	b.duration("SCHEDULER_LOCK_TTL", &c.Scheduler.LockTTL)

	b.boolean("SCRAPER_ENABLED", &c.Scraper.Enabled)
	b.duration("SCRAPER_INTERVAL", &c.Scraper.Interval)
	b.integer("SCRAPER_BATCH_SIZE", &c.Scraper.BatchSize)
	b.str("SCRAPER_USER_AGENT", &c.Scraper.UserAgent)
	b.duration("SCRAPER_REQUEST_TIMEOUT", &c.Scraper.RequestTimeout)
	b.integer64("SCRAPER_MAX_RESPONSE_BYTES", &c.Scraper.MaxResponseBytes)
	b.boolean("SCRAPER_ALLOW_PRIVATE_NETWORKS", &c.Scraper.AllowPrivateNetworks)
	b.integer("SCRAPER_MIN_CONTENT_WORDS", &c.Scraper.MinContentWords)
	b.integer("SCRAPER_MAX_ATTEMPTS", &c.Scraper.MaxAttempts)
	b.duration("SCRAPER_RETRY_BASE", &c.Scraper.RetryBase)
	b.duration("SCRAPER_MAX_ARTICLE_AGE", &c.Scraper.MaxArticleAge)
	b.duration("SCRAPER_PER_HOST_DELAY", &c.Scraper.PerHostDelay)
	b.integer("SCRAPER_CIRCUIT_FAILURE_THRESHOLD", &c.Scraper.CircuitFailureThreshold)
	b.duration("SCRAPER_CIRCUIT_OPEN_FOR", &c.Scraper.CircuitOpenFor)
	b.duration("SCRAPER_ROBOTS_CACHE_TTL", &c.Scraper.RobotsCacheTTL)
	b.duration("SCRAPER_CLAIM_TTL", &c.Scraper.ClaimTTL)

	b.boolean("CLASSIFIER_ENABLED", &c.Classifier.Enabled)
	b.str("CLASSIFIER_ENDPOINT", &c.Classifier.Endpoint)
	b.duration("CLASSIFIER_TIMEOUT", &c.Classifier.Timeout)
	b.integer("CLASSIFIER_BATCH_SIZE", &c.Classifier.BatchSize)
	b.integer("CLASSIFIER_MAX_ATTEMPTS", &c.Classifier.MaxAttempts)
	b.duration("CLASSIFIER_CLAIM_TTL", &c.Classifier.ClaimTTL)
	b.duration("CLASSIFIER_METADATA_REFRESH_INTERVAL", &c.Classifier.MetadataRefreshInterval)
	b.str("CLASSIFIER_API_KEY", &c.Classifier.APIKey)

	b.str("LOGGING_LEVEL", &c.Logging.Level)
	b.str("LOGGING_FORMAT", &c.Logging.Format)

	return errors.Join(b.errs...)
}

// Validate reports every configuration problem at once rather than only the first.
func (c *Config) Validate(opts ...Option) error {
	o := newOptions(opts)

	var errs []error

	if strings.TrimSpace(c.App.Name) == "" {
		errs = append(errs, errors.New("app.name must not be empty"))
	}
	errs = append(errs, oneOf("app.environment", c.App.Environment, "development", "staging", "production"))

	if c.Server.Port < 1 || c.Server.Port > 65535 {
		errs = append(errs, fmt.Errorf("server.port must be between 1 and 65535, got %d", c.Server.Port))
	}
	if strings.TrimSpace(c.Server.Host) == "" {
		errs = append(errs, errors.New("server.host must not be empty"))
	}
	if c.Server.MaxHeaderBytes <= 0 {
		errs = append(errs, errors.New("server.max_header_bytes must be greater than zero"))
	}
	errs = append(errs,
		positive("server.read_header_timeout", c.Server.ReadHeaderTimeout),
		positive("server.read_timeout", c.Server.ReadTimeout),
		positive("server.write_timeout", c.Server.WriteTimeout),
		positive("server.idle_timeout", c.Server.IdleTimeout),
		positive("server.shutdown_timeout", c.Server.ShutdownTimeout),
		positive("mongo.connect_timeout", c.Mongo.ConnectTimeout),
		positive("mongo.server_selection_timeout", c.Mongo.ServerSelectionTimeout),
		positive("mongo.operation_timeout", c.Mongo.OperationTimeout),
		validateMongoURI(c.Mongo.URI),
		validateDatabaseName(c.Mongo.Database),
		positive("bootstrap.timeout", c.Bootstrap.Timeout),
	)

	if c.Mongo.MaxPoolSize == 0 {
		errs = append(errs, errors.New("mongo.max_pool_size must be greater than zero"))
	} else if c.Mongo.MinPoolSize > c.Mongo.MaxPoolSize {
		errs = append(errs, fmt.Errorf("mongo.min_pool_size (%d) must not exceed mongo.max_pool_size (%d)",
			c.Mongo.MinPoolSize, c.Mongo.MaxPoolSize))
	}

	errs = append(errs,
		oneOf("logging.level", c.Logging.Level, "debug", "info", "warn", "error"),
		oneOf("logging.format", c.Logging.Format, "json", "text"),
	)
	if !o.skipAuth {
		errs = append(errs, c.Auth.validate(c.App.Environment)...)
	}
	errs = append(errs, c.Collector.validate(c.App.Environment)...)
	classifierTimeout := time.Duration(0)
	if c.Classifier.Enabled {
		classifierTimeout = c.Classifier.Timeout
	}
	errs = append(errs, c.Scheduler.validate(c.Collector.RequestTimeout, classifierTimeout)...)
	errs = append(errs, c.Scraper.validate(c.App.Environment)...)
	errs = append(errs, c.Classifier.validate(c.App.Environment)...)
	errs = append(errs, c.Web.validate()...)

	return errors.Join(errs...)
}

// DefaultAPIKeyHeader carries the API key when no other header is configured.
const DefaultAPIKeyHeader = "X-API-Key"

// Minimum credential lengths. An API key is machine-generated, so it can be
// held to a length that is infeasible to guess; a basic password is typed by a
// person, so the floor is lower but still well past a dictionary word.
const (
	minAPIKeyLength        = 32
	minBasicPasswordLength = 16
)

// validate reports every problem with the auth settings at once. No message
// ever quotes a credential value, because configuration errors are logged.
func (a Auth) validate(environment string) []error {
	var errs []error

	if !a.Enabled {
		// Turning auth off is a development convenience. In production it would
		// publish source management and the whole article corpus to anyone who
		// can reach the port, so it is refused outright.
		if environment == "production" {
			errs = append(errs, errors.New("auth.enabled must not be false in production"))
		}
		return errs
	}

	if err := validateHeaderName(a.APIKeyHeader); err != nil {
		errs = append(errs, err)
	}

	for i, key := range a.APIKeys {
		if len(key) < minAPIKeyLength {
			errs = append(errs, fmt.Errorf("%sAUTH_API_KEYS entry %d must be at least %d characters",
				EnvPrefix, i+1, minAPIKeyLength))
		}
	}

	// A half-configured basic credential is a misconfiguration, not a request to
	// disable basic auth, so it is reported rather than quietly ignored.
	hasBasic := a.BasicUsername != "" || a.BasicPassword != ""
	if hasBasic {
		if a.BasicUsername == "" {
			errs = append(errs, fmt.Errorf("%sAUTH_BASIC_USERNAME must be set when a basic password is configured", EnvPrefix))
		}
		if len(a.BasicPassword) < minBasicPasswordLength {
			errs = append(errs, fmt.Errorf("%sAUTH_BASIC_PASSWORD must be at least %d characters",
				EnvPrefix, minBasicPasswordLength))
		}
	}

	if !hasBasic && len(a.APIKeys) == 0 {
		errs = append(errs, fmt.Errorf("auth.enabled is true but no credentials are configured; set %sAUTH_API_KEYS, "+
			"or %sAUTH_BASIC_USERNAME and %sAUTH_BASIC_PASSWORD", EnvPrefix, EnvPrefix, EnvPrefix))
	}

	return errs
}

// validateHeaderName refuses anything that is not an RFC 9110 field name. The
// value reaches a response header on a rejected request, so a name carrying a
// separator or control character would let configuration inject a header.
func validateHeaderName(name string) error {
	if name == "" {
		return errors.New("auth.api_key_header must not be empty")
	}
	for _, r := range name {
		if r > unicode.MaxASCII || !isTokenChar(byte(r)) {
			return fmt.Errorf("auth.api_key_header %q is not a valid HTTP header name", name)
		}
	}
	return nil
}

func isTokenChar(c byte) bool {
	switch {
	case c >= 'a' && c <= 'z', c >= 'A' && c <= 'Z', c >= '0' && c <= '9':
		return true
	}
	return strings.IndexByte("!#$%&'*+-.^_`|~", c) >= 0
}

// maxCollectorResponseBytes is the ceiling on the per-response cap itself. A
// feed larger than this is not a feed, and allowing an arbitrary limit would
// let one misconfigured source exhaust the process's memory.
const maxCollectorResponseBytes = 64 << 20

// maxCollectorRedirects bounds the configurable redirect budget. Every hop is a
// fresh chance for a publisher to point the collector somewhere else, so the
// chain stays short even when an operator asks for more.
const maxCollectorRedirects = 10

func (c Collector) validate(environment string) []error {
	var errs []error

	if strings.TrimSpace(c.UserAgent) == "" {
		errs = append(errs, errors.New("collector.user_agent must not be empty"))
	}
	errs = append(errs, positive("collector.request_timeout", c.RequestTimeout))

	if c.MaxResponseBytes <= 0 || c.MaxResponseBytes > maxCollectorResponseBytes {
		errs = append(errs, fmt.Errorf("collector.max_response_bytes must be between 1 and %d, got %d",
			maxCollectorResponseBytes, c.MaxResponseBytes))
	}
	if c.MaxRedirects < 0 || c.MaxRedirects > maxCollectorRedirects {
		errs = append(errs, fmt.Errorf("collector.max_redirects must be between 0 and %d, got %d",
			maxCollectorRedirects, c.MaxRedirects))
	}
	if c.MaxItemsPerFeed <= 0 {
		errs = append(errs, fmt.Errorf("collector.max_items_per_feed must be greater than zero, got %d", c.MaxItemsPerFeed))
	}
	if c.AllowPrivateNetworks && environment == "production" {
		errs = append(errs, errors.New("collector.allow_private_networks must not be enabled in production"))
	}

	return errs
}

// maxSchedulerBatchSize and maxSchedulerConcurrency bound one tick's work.
// Beyond these a single tick would open more sockets and MongoDB operations
// than the pools are sized for, so a typo would degrade the API rather than
// speed up collection.
const (
	maxSchedulerBatchSize   = 500
	maxSchedulerConcurrency = 64
)

func (s Scheduler) validate(requestTimeout, classifierTimeout time.Duration) []error {
	if !s.Enabled {
		return nil
	}

	var errs []error

	errs = append(errs, positive("scheduler.interval", s.Interval))

	if s.BatchSize < 1 || s.BatchSize > maxSchedulerBatchSize {
		errs = append(errs, fmt.Errorf("scheduler.batch_size must be between 1 and %d, got %d",
			maxSchedulerBatchSize, s.BatchSize))
	}
	if s.MaxConcurrent < 1 || s.MaxConcurrent > maxSchedulerConcurrency {
		errs = append(errs, fmt.Errorf("scheduler.max_concurrent must be between 1 and %d, got %d",
			maxSchedulerConcurrency, s.MaxConcurrent))
	}

	// A lease that expires while its own fetch is still running would let a
	// second collector start the same source, which is the exact collision the
	// lease exists to prevent.
	minimumTTL := requestTimeout + classifierTimeout
	if s.LockTTL <= minimumTTL {
		errs = append(errs, fmt.Errorf("scheduler.lock_ttl (%s) must exceed collector.request_timeout (%s) plus classifier.timeout (%s)",
			s.LockTTL, requestTimeout, classifierTimeout))
	}

	return errs
}

// validate reports invalid classifier settings without exposing its API key.
func (c Classifier) validate(environment string) []error {
	if !c.Enabled {
		return nil
	}
	var errs []error
	u, err := url.Parse(c.Endpoint)
	if err != nil || u.Scheme == "" || u.Host == "" || (u.Scheme != "http" && u.Scheme != "https") || u.User != nil {
		errs = append(errs, errors.New("classifier.endpoint must be an absolute http or https URL without credentials"))
	}
	errs = append(errs,
		positive("classifier.timeout", c.Timeout),
		positive("classifier.claim_ttl", c.ClaimTTL),
		positive("classifier.metadata_refresh_interval", c.MetadataRefreshInterval),
	)
	if c.BatchSize < 1 {
		errs = append(errs, fmt.Errorf("classifier.batch_size must be greater than zero, got %d", c.BatchSize))
	}
	if c.MaxAttempts < 1 {
		errs = append(errs, fmt.Errorf("classifier.max_attempts must be greater than zero, got %d", c.MaxAttempts))
	}
	if c.ClaimTTL <= c.Timeout {
		errs = append(errs, fmt.Errorf("classifier.claim_ttl (%s) must exceed classifier.timeout (%s)", c.ClaimTTL, c.Timeout))
	}
	if environment == "production" && strings.TrimSpace(c.APIKey) == "" {
		errs = append(errs, fmt.Errorf("%sCLASSIFIER_API_KEY must be set when classifier.enabled is true in production", EnvPrefix))
	}
	return errs
}

// maxScraperResponseBytes bounds an article page. It is looser than
// maxCollectorResponseBytes: an ad-heavy article page routinely runs larger
// than a feed document ever does.
const maxScraperResponseBytes = 64 << 20

func (s Scraper) validate(environment string) []error {
	if !s.Enabled {
		return nil
	}

	var errs []error

	if strings.TrimSpace(s.UserAgent) == "" {
		errs = append(errs, errors.New("scraper.user_agent must not be empty"))
	}
	errs = append(errs,
		positive("scraper.interval", s.Interval),
		positive("scraper.request_timeout", s.RequestTimeout),
		positive("scraper.retry_base", s.RetryBase),
		positive("scraper.per_host_delay", s.PerHostDelay),
		positive("scraper.circuit_open_for", s.CircuitOpenFor),
		positive("scraper.robots_cache_ttl", s.RobotsCacheTTL),
		positive("scraper.claim_ttl", s.ClaimTTL),
	)

	if s.BatchSize < 1 {
		errs = append(errs, fmt.Errorf("scraper.batch_size must be greater than zero, got %d", s.BatchSize))
	}
	if s.MaxResponseBytes <= 0 || s.MaxResponseBytes > maxScraperResponseBytes {
		errs = append(errs, fmt.Errorf("scraper.max_response_bytes must be between 1 and %d, got %d",
			maxScraperResponseBytes, s.MaxResponseBytes))
	}
	if s.MinContentWords < 1 {
		errs = append(errs, fmt.Errorf("scraper.min_content_words must be greater than zero, got %d", s.MinContentWords))
	}
	if s.MaxAttempts < 1 {
		errs = append(errs, fmt.Errorf("scraper.max_attempts must be greater than zero, got %d", s.MaxAttempts))
	}
	if s.MaxArticleAge < 0 {
		errs = append(errs, errors.New("scraper.max_article_age must not be negative"))
	}
	if s.CircuitFailureThreshold < 1 {
		errs = append(errs, fmt.Errorf("scraper.circuit_failure_threshold must be greater than zero, got %d",
			s.CircuitFailureThreshold))
	}
	if s.AllowPrivateNetworks && environment == "production" {
		errs = append(errs, errors.New("scraper.allow_private_networks must not be enabled in production"))
	}

	return errs
}

// maxWebPageSize mirrors domain.MaxListLimit. It is restated rather than
// imported because this package deliberately depends on nothing but the
// standard library; the pair is held together by a test.
const maxWebPageSize = 100

func (w Web) validate() []error {
	if !w.Enabled {
		return nil
	}
	if w.PageSize < 1 || w.PageSize > maxWebPageSize {
		return []error{fmt.Errorf("web.page_size must be between 1 and %d, got %d", maxWebPageSize, w.PageSize)}
	}
	return nil
}

func validateMongoURI(uri string) error {
	if strings.TrimSpace(uri) == "" {
		return errors.New("mongo.uri must not be empty")
	}
	if !strings.HasPrefix(uri, "mongodb://") && !strings.HasPrefix(uri, "mongodb+srv://") {
		return errors.New(`mongo.uri must start with "mongodb://" or "mongodb+srv://"`)
	}
	if _, err := url.Parse(uri); err != nil {
		return fmt.Errorf("mongo.uri is not a valid URI: %w", err)
	}
	return nil
}

// invalidDatabaseChars are the characters MongoDB forbids in a database name.
const invalidDatabaseChars = "/\\. \"$*<>:|?"

func validateDatabaseName(name string) error {
	if strings.TrimSpace(name) == "" {
		return errors.New("mongo.database must not be empty")
	}
	if strings.ContainsAny(name, invalidDatabaseChars) || strings.ContainsRune(name, 0) {
		return fmt.Errorf("mongo.database %q contains characters that MongoDB forbids (%s)", name, invalidDatabaseChars)
	}
	if len(name) > 63 {
		return fmt.Errorf("mongo.database must be at most 63 bytes, got %d", len(name))
	}
	return nil
}

func positive(field string, d time.Duration) error {
	if d <= 0 {
		return fmt.Errorf("%s must be greater than zero, got %s", field, d)
	}
	return nil
}

func oneOf(field, value string, allowed ...string) error {
	for _, a := range allowed {
		if value == a {
			return nil
		}
	}
	return fmt.Errorf("%s must be one of %s, got %q", field, strings.Join(allowed, ", "), value)
}

// envBinder applies environment overrides, collecting parse errors so a single
// load reports every malformed variable instead of only the first.
type envBinder struct {
	errs []error
}

func (b *envBinder) lookup(key string) (string, bool) {
	raw, ok := os.LookupEnv(EnvPrefix + key)
	if !ok {
		return "", false
	}
	trimmed := strings.TrimSpace(raw)
	if trimmed == "" {
		return "", false
	}
	return trimmed, true
}

func (b *envBinder) fail(key string, err error) {
	b.errs = append(b.errs, fmt.Errorf("%s%s: %w", EnvPrefix, key, err))
}

func (b *envBinder) str(key string, dst *string) {
	if v, ok := b.lookup(key); ok {
		*dst = v
	}
}

// list reads a comma-separated variable, dropping empty entries so a trailing
// comma or a gap left by a removed value does not become a zero-length item.
func (b *envBinder) list(key string, dst *[]string) {
	v, ok := b.lookup(key)
	if !ok {
		return
	}
	values := make([]string, 0, strings.Count(v, ",")+1)
	for _, part := range strings.Split(v, ",") {
		if trimmed := strings.TrimSpace(part); trimmed != "" {
			values = append(values, trimmed)
		}
	}
	*dst = values
}

func (b *envBinder) integer(key string, dst *int) {
	v, ok := b.lookup(key)
	if !ok {
		return
	}
	n, err := strconv.Atoi(v)
	if err != nil {
		b.fail(key, fmt.Errorf("expected an integer, got %q", v))
		return
	}
	*dst = n
}

func (b *envBinder) unsigned(key string, dst *uint64) {
	v, ok := b.lookup(key)
	if !ok {
		return
	}
	n, err := strconv.ParseUint(v, 10, 64)
	if err != nil {
		b.fail(key, fmt.Errorf("expected a non-negative integer, got %q", v))
		return
	}
	*dst = n
}

func (b *envBinder) integer64(key string, dst *int64) {
	v, ok := b.lookup(key)
	if !ok {
		return
	}
	n, err := strconv.ParseInt(v, 10, 64)
	if err != nil {
		b.fail(key, fmt.Errorf("expected an integer, got %q", v))
		return
	}
	*dst = n
}

func (b *envBinder) boolean(key string, dst *bool) {
	v, ok := b.lookup(key)
	if !ok {
		return
	}
	parsed, err := strconv.ParseBool(v)
	if err != nil {
		b.fail(key, fmt.Errorf("expected true or false, got %q", v))
		return
	}
	*dst = parsed
}

func (b *envBinder) duration(key string, dst *time.Duration) {
	v, ok := b.lookup(key)
	if !ok {
		return
	}
	d, err := time.ParseDuration(v)
	if err != nil {
		b.fail(key, fmt.Errorf("expected a duration such as 15s, got %q", v))
		return
	}
	*dst = d
}
