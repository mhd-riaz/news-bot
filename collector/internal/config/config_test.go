package config

import (
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
)

func writeConfig(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), "config.yaml")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write fixture: %v", err)
	}
	return path
}

func TestDefaultIsValid(t *testing.T) {
	if err := Default().Validate(); err != nil {
		t.Fatalf("built-in defaults must validate, got: %v", err)
	}
}

func TestLoadWithoutFileUsesDefaults(t *testing.T) {
	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Server.Port != 8080 {
		t.Errorf("Server.Port = %d, want 8080", cfg.Server.Port)
	}
	if cfg.Mongo.Database != "news" {
		t.Errorf("Mongo.Database = %q, want %q", cfg.Mongo.Database, "news")
	}
}

func TestLoadFileOverridesDefaultsAndParsesDurations(t *testing.T) {
	path := writeConfig(t, `
app:
  name: custom-app
server:
  port: 9090
  shutdown_timeout: 45s
mongo:
  database: custom_db
logging:
  level: debug
  format: text
`)

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if cfg.App.Name != "custom-app" {
		t.Errorf("App.Name = %q, want %q", cfg.App.Name, "custom-app")
	}
	if cfg.Server.Port != 9090 {
		t.Errorf("Server.Port = %d, want 9090", cfg.Server.Port)
	}
	if cfg.Server.ShutdownTimeout != 45*time.Second {
		t.Errorf("Server.ShutdownTimeout = %s, want 45s", cfg.Server.ShutdownTimeout)
	}
	if cfg.Mongo.Database != "custom_db" {
		t.Errorf("Mongo.Database = %q, want %q", cfg.Mongo.Database, "custom_db")
	}
	if cfg.Server.ReadTimeout != 15*time.Second {
		t.Errorf("unspecified keys must keep their default, got ReadTimeout = %s", cfg.Server.ReadTimeout)
	}
}

func TestLoadRejectsUnknownKeys(t *testing.T) {
	path := writeConfig(t, "server:\n  prot: 9090\n")

	_, err := Load(path)
	if err == nil {
		t.Fatal("expected an error for a misspelled config key")
	}
	if !strings.Contains(err.Error(), "prot") {
		t.Errorf("error should name the unknown field, got: %v", err)
	}
}

func TestLoadReportsMissingFile(t *testing.T) {
	if _, err := Load(filepath.Join(t.TempDir(), "absent.yaml")); err == nil {
		t.Fatal("expected an error for a missing config file")
	}
}

func TestEnvOverridesFile(t *testing.T) {
	path := writeConfig(t, "server:\n  port: 9090\n")

	t.Setenv(EnvPrefix+"SERVER_PORT", "7070")
	t.Setenv(EnvPrefix+"MONGO_URI", "mongodb://mongo:27017")
	t.Setenv(EnvPrefix+"MONGO_MAX_POOL_SIZE", "25")
	t.Setenv(EnvPrefix+"SERVER_SHUTDOWN_TIMEOUT", "3s")

	cfg, err := Load(path)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if cfg.Server.Port != 7070 {
		t.Errorf("Server.Port = %d, want the env value 7070", cfg.Server.Port)
	}
	if cfg.Mongo.URI != "mongodb://mongo:27017" {
		t.Errorf("Mongo.URI = %q", cfg.Mongo.URI)
	}
	if cfg.Mongo.MaxPoolSize != 25 {
		t.Errorf("Mongo.MaxPoolSize = %d, want 25", cfg.Mongo.MaxPoolSize)
	}
	if cfg.Server.ShutdownTimeout != 3*time.Second {
		t.Errorf("Server.ShutdownTimeout = %s, want 3s", cfg.Server.ShutdownTimeout)
	}
	if cfg.Classifier.Enabled {
		t.Error("Classifier.Enabled = true, want the default false")
	}
}

func TestClassifierEnvironmentAndValidation(t *testing.T) {
	t.Setenv(EnvPrefix+"CLASSIFIER_ENABLED", "true")
	t.Setenv(EnvPrefix+"CLASSIFIER_ENDPOINT", "http://classifier:8000")
	t.Setenv(EnvPrefix+"CLASSIFIER_TIMEOUT", "8s")
	t.Setenv(EnvPrefix+"CLASSIFIER_API_KEY", "local-secret")

	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if !cfg.Classifier.Enabled || cfg.Classifier.Timeout != 8*time.Second || cfg.Classifier.APIKey != "local-secret" {
		t.Errorf("Classifier = %#v", cfg.Classifier)
	}

	cfg.App.Environment = "production"
	cfg.Classifier.APIKey = ""
	if err := cfg.Validate(); err == nil || !strings.Contains(err.Error(), "CLASSIFIER_API_KEY") {
		t.Errorf("production classifier validation = %v, want API key error", err)
	}
}

func TestEnvBlankValueIsIgnored(t *testing.T) {
	t.Setenv(EnvPrefix+"MONGO_DATABASE", "   ")

	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	if cfg.Mongo.Database != "news" {
		t.Errorf("blank env var must not clear the default, got %q", cfg.Mongo.Database)
	}
}

func TestEnvMalformedValuesAreReported(t *testing.T) {
	t.Setenv(EnvPrefix+"SERVER_PORT", "not-a-number")
	t.Setenv(EnvPrefix+"MONGO_CONNECT_TIMEOUT", "soon")

	_, err := Load("")
	if err == nil {
		t.Fatal("expected an error for malformed environment values")
	}
	for _, want := range []string{"SERVER_PORT", "MONGO_CONNECT_TIMEOUT"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error should mention %s, got: %v", want, err)
		}
	}
}

func TestValidate(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(*Config)
		wantMsg string
	}{
		{"port too low", func(c *Config) { c.Server.Port = 0 }, "server.port"},
		{"port too high", func(c *Config) { c.Server.Port = 70000 }, "server.port"},
		{"empty app name", func(c *Config) { c.App.Name = "" }, "app.name"},
		{"unknown environment", func(c *Config) { c.App.Environment = "qa" }, "app.environment"},
		{"non-positive timeout", func(c *Config) { c.Server.ShutdownTimeout = 0 }, "server.shutdown_timeout"},
		{"empty mongo uri", func(c *Config) { c.Mongo.URI = "" }, "mongo.uri"},
		{"wrong mongo scheme", func(c *Config) { c.Mongo.URI = "http://localhost:27017" }, "mongo.uri"},
		{"empty database", func(c *Config) { c.Mongo.Database = "" }, "mongo.database"},
		{"illegal database char", func(c *Config) { c.Mongo.Database = "news/db" }, "mongo.database"},
		{"zero pool", func(c *Config) { c.Mongo.MaxPoolSize = 0 }, "mongo.max_pool_size"},
		{"min above max", func(c *Config) { c.Mongo.MinPoolSize = 100; c.Mongo.MaxPoolSize = 10 }, "mongo.min_pool_size"},
		{"unknown log level", func(c *Config) { c.Logging.Level = "verbose" }, "logging.level"},
		{"unknown log format", func(c *Config) { c.Logging.Format = "xml" }, "logging.format"},
		{"empty user agent", func(c *Config) { c.Collector.UserAgent = " " }, "collector.user_agent"},
		{"zero request timeout", func(c *Config) { c.Collector.RequestTimeout = 0 }, "collector.request_timeout"},
		{"zero response cap", func(c *Config) { c.Collector.MaxResponseBytes = 0 }, "collector.max_response_bytes"},
		{"response cap too high", func(c *Config) { c.Collector.MaxResponseBytes = 1 << 40 }, "collector.max_response_bytes"},
		{"negative redirects", func(c *Config) { c.Collector.MaxRedirects = -1 }, "collector.max_redirects"},
		{"too many redirects", func(c *Config) { c.Collector.MaxRedirects = 50 }, "collector.max_redirects"},
		{"zero item cap", func(c *Config) { c.Collector.MaxItemsPerFeed = 0 }, "collector.max_items_per_feed"},
		{
			"private networks in production",
			func(c *Config) { c.App.Environment = "production"; c.Collector.AllowPrivateNetworks = true },
			"collector.allow_private_networks",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Default()
			tc.mutate(cfg)

			err := cfg.Validate()
			if err == nil {
				t.Fatalf("expected a validation error mentioning %s", tc.wantMsg)
			}
			if !strings.Contains(err.Error(), tc.wantMsg) {
				t.Errorf("error should mention %s, got: %v", tc.wantMsg, err)
			}
		})
	}
}

func TestValidateReportsAllProblemsAtOnce(t *testing.T) {
	cfg := Default()
	cfg.Server.Port = 0
	cfg.Logging.Level = "verbose"

	err := cfg.Validate()
	if err == nil {
		t.Fatal("expected a validation error")
	}
	if !strings.Contains(err.Error(), "server.port") || !strings.Contains(err.Error(), "logging.level") {
		t.Errorf("both problems should be reported, got: %v", err)
	}
}

func TestAuthValidation(t *testing.T) {
	const (
		validKey      = "9f2c1d4e8a6b0c3d5e7f9a1b2c3d4e5f60718293"
		validPassword = "correct-horse-battery"
	)

	enabled := func(mutate func(*Auth)) func(*Config) {
		return func(c *Config) {
			c.Auth.Enabled = true
			c.Auth.APIKeys = []string{validKey}
			mutate(&c.Auth)
		}
	}

	tests := []struct {
		name    string
		mutate  func(*Config)
		wantMsg string
	}{
		{
			"disabled in production",
			func(c *Config) { c.App.Environment = "production"; c.Auth.Enabled = false },
			"auth.enabled",
		},
		{
			"enabled with no credentials",
			enabled(func(a *Auth) { a.APIKeys = nil }),
			"no credentials are configured",
		},
		{
			"short api key",
			enabled(func(a *Auth) { a.APIKeys = []string{"tooshort"} }),
			"AUTH_API_KEYS",
		},
		{
			"basic password without username",
			enabled(func(a *Auth) { a.BasicPassword = validPassword }),
			"AUTH_BASIC_USERNAME",
		},
		{
			"basic username without password",
			enabled(func(a *Auth) { a.BasicUsername = "operator" }),
			"AUTH_BASIC_PASSWORD",
		},
		{
			"short basic password",
			enabled(func(a *Auth) { a.BasicUsername = "operator"; a.BasicPassword = "short" }),
			"AUTH_BASIC_PASSWORD",
		},
		{
			"empty header name",
			enabled(func(a *Auth) { a.APIKeyHeader = "" }),
			"auth.api_key_header",
		},
		{
			"header name with a separator",
			enabled(func(a *Auth) { a.APIKeyHeader = "X-Api Key: injected" }),
			"auth.api_key_header",
		},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			cfg := Default()
			tc.mutate(cfg)

			err := cfg.Validate()
			if err == nil {
				t.Fatalf("expected a validation error mentioning %s", tc.wantMsg)
			}
			if !strings.Contains(err.Error(), tc.wantMsg) {
				t.Errorf("error should mention %s, got: %v", tc.wantMsg, err)
			}
		})
	}
}

func TestSkipAuthValidationIgnoresAuthProblems(t *testing.T) {
	cfg := Default()
	cfg.App.Environment = "production"
	cfg.Auth.Enabled = false

	if err := cfg.Validate(); err == nil {
		t.Fatal("without the option, disabled auth in production must be refused")
	}
	if err := cfg.Validate(SkipAuthValidation); err != nil {
		t.Fatalf("auth problems must be ignored for non-serving binaries, got: %v", err)
	}

	// Only the auth checks are dropped; the rest still run.
	cfg.Logging.Level = "verbose"
	if err := cfg.Validate(SkipAuthValidation); err == nil {
		t.Fatal("non-auth problems must still be reported")
	}
}

func TestLoadSkipAuthValidationInProduction(t *testing.T) {
	t.Setenv(EnvPrefix+"APP_ENVIRONMENT", "production")
	t.Setenv(EnvPrefix+"AUTH_ENABLED", "false")

	if _, err := Load(""); err == nil {
		t.Fatal("the API server must still refuse disabled auth in production")
	}
	if _, err := Load("", SkipAuthValidation); err != nil {
		t.Fatalf("migrate and seed must load with auth disabled, got: %v", err)
	}
}

func TestAuthAcceptsEitherCredentialKind(t *testing.T) {
	const (
		validKey      = "9f2c1d4e8a6b0c3d5e7f9a1b2c3d4e5f60718293"
		validPassword = "correct-horse-battery"
	)

	cases := map[string]func(*Auth){
		"api keys only": func(a *Auth) { a.APIKeys = []string{validKey} },
		"basic only":    func(a *Auth) { a.BasicUsername = "operator"; a.BasicPassword = validPassword },
		"both": func(a *Auth) {
			a.APIKeys = []string{validKey}
			a.BasicUsername = "operator"
			a.BasicPassword = validPassword
		},
	}

	for name, mutate := range cases {
		t.Run(name, func(t *testing.T) {
			cfg := Default()
			cfg.App.Environment = "production"
			cfg.Auth.Enabled = true
			mutate(&cfg.Auth)

			if err := cfg.Validate(); err != nil {
				t.Fatalf("expected a valid configuration, got: %v", err)
			}
		})
	}
}

func TestAuthEnvOverrides(t *testing.T) {
	t.Setenv(EnvPrefix+"AUTH_ENABLED", "true")
	t.Setenv(EnvPrefix+"AUTH_API_KEY_HEADER", "X-News-Api-Key")
	t.Setenv(EnvPrefix+"AUTH_API_KEYS",
		" 9f2c1d4e8a6b0c3d5e7f9a1b2c3d4e5f60718293 , ,0011223344556677889900aabbccddeeff00112233,")
	t.Setenv(EnvPrefix+"AUTH_BASIC_USERNAME", "operator")
	t.Setenv(EnvPrefix+"AUTH_BASIC_PASSWORD", "correct-horse-battery")

	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if !cfg.Auth.Enabled {
		t.Error("auth should be enabled")
	}
	if cfg.Auth.APIKeyHeader != "X-News-Api-Key" {
		t.Errorf("api_key_header = %q", cfg.Auth.APIKeyHeader)
	}
	// Blank entries and surrounding spaces are dropped, not carried through as keys.
	if len(cfg.Auth.APIKeys) != 2 {
		t.Fatalf("api keys = %d, want 2", len(cfg.Auth.APIKeys))
	}
	if cfg.Auth.APIKeys[0] != "9f2c1d4e8a6b0c3d5e7f9a1b2c3d4e5f60718293" {
		t.Errorf("first key = %q", cfg.Auth.APIKeys[0])
	}
	if cfg.Auth.BasicUsername != "operator" {
		t.Errorf("basic username = %q", cfg.Auth.BasicUsername)
	}
}

// Secrets belong in the environment, so the file layer must not accept them.
func TestConfigFileRejectsAuthCredentials(t *testing.T) {
	path := writeConfig(t, "auth:\n  enabled: true\n  basic_password: hunter2\n")

	if _, err := Load(path); err == nil {
		t.Fatal("expected credentials in the config file to be rejected")
	}
}

func TestRedactedURIHidesCredentials(t *testing.T) {
	m := Mongo{URI: "mongodb://admin:sup3rs3cret@localhost:27017/news"}

	got := m.RedactedURI()
	if strings.Contains(got, "sup3rs3cret") {
		t.Fatalf("RedactedURI leaked the password: %q", got)
	}
	if !strings.Contains(got, "localhost:27017") {
		t.Errorf("RedactedURI should keep the host, got %q", got)
	}
}

func TestServerAddress(t *testing.T) {
	s := Server{Host: "127.0.0.1", Port: 8080}
	if got := s.Address(); got != "127.0.0.1:8080" {
		t.Errorf("Address() = %q, want %q", got, "127.0.0.1:8080")
	}
}

func TestCollectorEnvOverrides(t *testing.T) {
	t.Setenv(EnvPrefix+"COLLECTOR_MAX_RESPONSE_BYTES", "2097152")
	t.Setenv(EnvPrefix+"COLLECTOR_MAX_REDIRECTS", "2")
	t.Setenv(EnvPrefix+"COLLECTOR_ALLOW_PRIVATE_NETWORKS", "true")
	t.Setenv(EnvPrefix+"COLLECTOR_REQUEST_TIMEOUT", "7s")

	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if cfg.Collector.MaxResponseBytes != 2<<20 {
		t.Errorf("MaxResponseBytes = %d, want 2097152", cfg.Collector.MaxResponseBytes)
	}
	if cfg.Collector.MaxRedirects != 2 {
		t.Errorf("MaxRedirects = %d, want 2", cfg.Collector.MaxRedirects)
	}
	if !cfg.Collector.AllowPrivateNetworks {
		t.Error("AllowPrivateNetworks = false, want the env override applied")
	}
	if cfg.Collector.RequestTimeout != 7*time.Second {
		t.Errorf("RequestTimeout = %s, want 7s", cfg.Collector.RequestTimeout)
	}
}

func TestCollectorMalformedBooleanIsReported(t *testing.T) {
	t.Setenv(EnvPrefix+"COLLECTOR_ALLOW_PRIVATE_NETWORKS", "yes-please")

	_, err := Load("")
	if err == nil || !strings.Contains(err.Error(), "COLLECTOR_ALLOW_PRIVATE_NETWORKS") {
		t.Fatalf("error should name the malformed variable, got: %v", err)
	}
}

func TestSchedulerEnvOverrides(t *testing.T) {
	t.Setenv(EnvPrefix+"SCHEDULER_ENABLED", "false")
	t.Setenv(EnvPrefix+"SCHEDULER_INTERVAL", "30s")
	t.Setenv(EnvPrefix+"SCHEDULER_BATCH_SIZE", "10")
	t.Setenv(EnvPrefix+"SCHEDULER_MAX_CONCURRENT", "2")
	t.Setenv(EnvPrefix+"SCHEDULER_LOCK_TTL", "90s")

	cfg, err := Load("")
	if err != nil {
		t.Fatalf("Load: %v", err)
	}

	if cfg.Scheduler.Enabled {
		t.Error("Enabled = true, want the env override applied")
	}
	if cfg.Scheduler.Interval != 30*time.Second || cfg.Scheduler.LockTTL != 90*time.Second {
		t.Errorf("durations = %s / %s, want 30s / 90s", cfg.Scheduler.Interval, cfg.Scheduler.LockTTL)
	}
	if cfg.Scheduler.BatchSize != 10 || cfg.Scheduler.MaxConcurrent != 2 {
		t.Errorf("batch/concurrency = %d/%d, want 10/2", cfg.Scheduler.BatchSize, cfg.Scheduler.MaxConcurrent)
	}
}

func TestSchedulerValidation(t *testing.T) {
	tests := []struct {
		name    string
		mutate  func(*Config)
		wantErr string
	}{
		{
			name:    "no interval",
			mutate:  func(c *Config) { c.Scheduler.Interval = 0 },
			wantErr: "scheduler.interval",
		},
		{
			name:    "batch beyond the cap",
			mutate:  func(c *Config) { c.Scheduler.BatchSize = maxSchedulerBatchSize + 1 },
			wantErr: "scheduler.batch_size",
		},
		{
			name:    "concurrency beyond the cap",
			mutate:  func(c *Config) { c.Scheduler.MaxConcurrent = maxSchedulerConcurrency + 1 },
			wantErr: "scheduler.max_concurrent",
		},
		{
			// A lease that expires while its own fetch is still running is the
			// exact collision the lease exists to prevent.
			name:    "lease shorter than a fetch",
			mutate:  func(c *Config) { c.Scheduler.LockTTL = c.Collector.RequestTimeout },
			wantErr: "scheduler.lock_ttl",
		},
	}

	for _, tt := range tests {
		t.Run(tt.name, func(t *testing.T) {
			cfg := Default()
			tt.mutate(cfg)

			err := cfg.Validate()
			if err == nil || !strings.Contains(err.Error(), tt.wantErr) {
				t.Fatalf("error = %v, want it to name %s", err, tt.wantErr)
			}
		})
	}
}

// A disabled scheduler is not configured at all, so its settings must not be
// able to stop the process starting.
func TestDisabledSchedulerIsNotValidated(t *testing.T) {
	cfg := Default()
	cfg.Scheduler.Enabled = false
	cfg.Scheduler.Interval = 0
	cfg.Scheduler.BatchSize = 0
	cfg.Scheduler.MaxConcurrent = 0
	cfg.Scheduler.LockTTL = 0

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

// The page size becomes a domain.ArticleFilter limit, whose bound this package
// restates rather than imports. The two must not drift.
func TestMaxWebPageSizeMatchesTheDomainListLimit(t *testing.T) {
	if maxWebPageSize != domain.MaxListLimit {
		t.Fatalf("maxWebPageSize = %d, but domain.MaxListLimit = %d", maxWebPageSize, domain.MaxListLimit)
	}
}

// A disabled site is not configured at all, for the same reason.
func TestDisabledWebIsNotValidated(t *testing.T) {
	cfg := Default()
	cfg.Web.Enabled = false
	cfg.Web.PageSize = 0

	if err := cfg.Validate(); err != nil {
		t.Fatalf("Validate: %v", err)
	}
}

func TestWebPageSizeIsBounded(t *testing.T) {
	for _, size := range []int{0, -1, maxWebPageSize + 1} {
		cfg := Default()
		cfg.Web.PageSize = size
		if err := cfg.Validate(); err == nil {
			t.Errorf("page_size %d was accepted", size)
		}
	}
}
