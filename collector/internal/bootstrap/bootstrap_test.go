package bootstrap

import (
	"context"
	"errors"
	"io"
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"

	"github.com/riaz/newscollector/internal/domain"
)

const oneValidSource = `
sources:
  - name: The Hindu — Bengaluru
    feed_url: https://www.thehindu.com/news/cities/bangalore/feeder/default.rss
    type: rss
    language: en
    country: IN
    state: Karnataka
    city: Bengaluru
`

func TestParseSources(t *testing.T) {
	file, err := ParseSources(strings.NewReader(oneValidSource))
	if err != nil {
		t.Fatalf("ParseSources: %v", err)
	}
	if len(file.Sources) != 1 {
		t.Fatalf("parsed %d sources, want 1", len(file.Sources))
	}

	in := file.Sources[0].Input()
	if in.Type != domain.SourceTypeRSS || in.Country != "IN" || in.City != "Bengaluru" {
		t.Errorf("input = %+v, want the file values carried through", in)
	}
	// Omitted optional keys must stay nil so a re-sync cannot reset a tuned value.
	if in.Enabled != nil || in.Priority != nil || in.FetchIntervalSeconds != nil {
		t.Errorf("optional fields = %v/%v/%v, want nil", in.Enabled, in.Priority, in.FetchIntervalSeconds)
	}
}

func TestParseSourcesRejectsUnknownKeys(t *testing.T) {
	_, err := ParseSources(strings.NewReader(`
sources:
  - name: X
    feed_ur1: https://example.com/f.rss
`))
	if err == nil {
		t.Fatal("ParseSources accepted a typo'd key, want it rejected")
	}
	if !strings.Contains(err.Error(), "feed_ur1") {
		t.Errorf("error = %v, want it to name the offending key", err)
	}
}

func TestParseSourcesAcceptsAnEmptyDocument(t *testing.T) {
	file, err := ParseSources(strings.NewReader(""))
	if err != nil {
		t.Fatalf("ParseSources: %v", err)
	}
	if len(file.Sources) != 0 {
		t.Errorf("parsed %d sources, want 0", len(file.Sources))
	}
}

func TestParseSourcesRejectsMalformedYAML(t *testing.T) {
	if _, err := ParseSources(strings.NewReader("sources: [{")); err == nil {
		t.Fatal("ParseSources accepted malformed YAML")
	}
}

func TestValidateSourcesAcceptsAValidFile(t *testing.T) {
	file, err := ParseSources(strings.NewReader(oneValidSource))
	if err != nil {
		t.Fatalf("ParseSources: %v", err)
	}

	inputs, err := ValidateSources(file.Sources)
	if err != nil {
		t.Fatalf("ValidateSources: %v", err)
	}
	if len(inputs) != 1 {
		t.Errorf("validated %d inputs, want 1", len(inputs))
	}
}

func TestValidateSourcesReportsThePositionOfEveryBadEntry(t *testing.T) {
	file, err := ParseSources(strings.NewReader(`
sources:
  - name: Good
    feed_url: https://example.com/good.rss
    type: rss
    language: en
    country: IN
  - name: Bad scheme
    feed_url: file:///etc/passwd
    type: rss
    language: en
    country: IN
  - name: Bad type
    feed_url: https://example.com/other.rss
    type: json
    language: en
    country: IN
`))
	if err != nil {
		t.Fatalf("ParseSources: %v", err)
	}

	_, err = ValidateSources(file.Sources)
	if err == nil {
		t.Fatal("ValidateSources accepted two invalid entries")
	}
	for _, want := range []string{"sources[1]", "sources[2]", "Bad scheme", "Bad type"} {
		if !strings.Contains(err.Error(), want) {
			t.Errorf("error %q does not mention %q", err.Error(), want)
		}
	}
}

// A duplicate inside the file would otherwise surface as a confusing conflict
// only once it reached the unique index.
func TestValidateSourcesRejectsADuplicateFeedURLWithinTheFile(t *testing.T) {
	file, err := ParseSources(strings.NewReader(`
sources:
  - name: First
    feed_url: https://example.com/same.rss
    type: rss
    language: en
    country: IN
  - name: Second
    feed_url: https://example.com/same.rss
    type: atom
    language: en
    country: IN
`))
	if err != nil {
		t.Fatalf("ParseSources: %v", err)
	}

	_, err = ValidateSources(file.Sources)
	if err == nil {
		t.Fatal("ValidateSources accepted a feed URL declared twice")
	}
	if !strings.Contains(err.Error(), "already declared at sources[0]") {
		t.Errorf("error = %v, want it to point at the first declaration", err)
	}
}

// The shipped seed file must always be valid; a broken default would fail only
// at startup, which is now the API's startup.
func TestShippedSourcesFileIsValid(t *testing.T) {
	inputs, err := LoadSources(context.Background(), "../../configs/sources.yaml")
	if err != nil {
		t.Fatalf("the shipped seed file is invalid: %v", err)
	}
	if len(inputs) == 0 {
		t.Fatal("the shipped seed file declares no sources")
	}
}

func TestLoadSourcesReportsAMissingFile(t *testing.T) {
	if _, err := LoadSources(context.Background(), "testdata/does-not-exist.yaml"); !errors.Is(err, os.ErrNotExist) {
		t.Errorf("error = %v, want it to wrap os.ErrNotExist", err)
	}
}

// A URL is what keeps the feed list out of the image, so it has to work end to
// end, not just parse.
func TestLoadSourcesReadsAnHTTPSURL(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		_, _ = io.WriteString(w, oneValidSource)
	}))
	defer srv.Close()

	// httptest's TLS certificate is self-signed, so the test client is the one
	// that trusts it; production uses the system pool.
	previous := sourcesClient
	sourcesClient = srv.Client()
	defer func() { sourcesClient = previous }()

	inputs, err := LoadSources(context.Background(), srv.URL)
	if err != nil {
		t.Fatalf("LoadSources: %v", err)
	}
	if len(inputs) != 1 {
		t.Errorf("loaded %d sources, want 1", len(inputs))
	}
}

// Plaintext would let anyone on the path choose which feeds the collector
// fetches.
func TestLoadSourcesRefusesPlaintextHTTP(t *testing.T) {
	_, err := LoadSources(context.Background(), "http://example.com/sources.yaml")
	if err == nil || !strings.Contains(err.Error(), "https") {
		t.Errorf("error = %v, want it to refuse plaintext http", err)
	}
}

func TestLoadSourcesReportsANon200(t *testing.T) {
	srv := httptest.NewTLSServer(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusNotFound)
	}))
	defer srv.Close()

	previous := sourcesClient
	sourcesClient = srv.Client()
	defer func() { sourcesClient = previous }()

	if _, err := LoadSources(context.Background(), srv.URL); err == nil {
		t.Error("LoadSources accepted a 404 response")
	}
}

// A token in the query string must not reach a log line or an error.
func TestRedactRefDropsCredentialsAndQuery(t *testing.T) {
	got := redactRef("https://user:pw@example.com/sources.yaml?token=secret#frag")
	if strings.Contains(got, "secret") || strings.Contains(got, "pw") {
		t.Errorf("redactRef = %q, want the credential and query gone", got)
	}
	if !strings.Contains(got, "example.com/sources.yaml") {
		t.Errorf("redactRef = %q, want it to keep enough to identify the file", got)
	}
}

// ensurerStub records what SyncSources applied, so the loop can be exercised
// without a database.
type ensurerStub struct {
	applied []domain.SourceInput
	err     error
}

func (e *ensurerStub) Ensure(_ context.Context, in domain.SourceInput) (*domain.Source, bool, error) {
	if e.err != nil {
		return nil, false, e.err
	}
	e.applied = append(e.applied, in)
	return &domain.Source{ID: "id", FeedURL: in.FeedURL}, true, nil
}

func TestSyncSourcesAppliesEveryInput(t *testing.T) {
	inputs, err := ParseSources(strings.NewReader(oneValidSource))
	if err != nil {
		t.Fatalf("ParseSources: %v", err)
	}
	validated, err := ValidateSources(inputs.Sources)
	if err != nil {
		t.Fatalf("ValidateSources: %v", err)
	}

	stub := &ensurerStub{}
	if err := SyncSources(context.Background(), stub, validated, nil); err != nil {
		t.Fatalf("SyncSources: %v", err)
	}
	if len(stub.applied) != 1 {
		t.Errorf("applied %d sources, want 1", len(stub.applied))
	}
}

// A failure must name the feed that caused it, or an operator has to guess
// which of twenty entries is at fault.
func TestSyncSourcesNamesTheFailingFeed(t *testing.T) {
	stub := &ensurerStub{err: errors.New("boom")}
	inputs := []domain.SourceInput{{FeedURL: "https://example.com/broken.rss"}}

	err := SyncSources(context.Background(), stub, inputs, nil)
	if err == nil || !strings.Contains(err.Error(), "https://example.com/broken.rss") {
		t.Errorf("error = %v, want it to name the failing feed", err)
	}
}
