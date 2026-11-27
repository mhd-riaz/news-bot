package handler

import (
	"net/http"
	"net/http/httptest"
	"strings"
	"testing"
	"time"
)

const (
	testAPIKey    = "9f2c1d4e8a6b0c3d5e7f9a1b2c3d4e5f60718293"
	testUsername  = "operator"
	testPassword  = "correct-horse-battery"
	testAPIHeader = "X-API-Key"
)

func newGuardedServer(t *testing.T, creds AuthCredentials) http.Handler {
	t.Helper()
	logger := discardLogger()
	return NewRouter(
		NewHealth(stubPinger{}, time.Second, "test", logger),
		NewSource(&fakeSourceManager{}, logger),
		NewCollectionRun(&fakeRunReader{}, logger),
		NewArticle(&fakeArticleReader{}, logger),
		NewAuthenticator(creds),
		logger,
	)
}

func bothCredentials() AuthCredentials {
	return AuthCredentials{
		APIKeyHeader:  testAPIHeader,
		APIKeys:       []string{testAPIKey},
		BasicUsername: testUsername,
		BasicPassword: testPassword,
	}
}

func TestNewAuthenticatorReturnsNilWithoutCredentials(t *testing.T) {
	if a := NewAuthenticator(AuthCredentials{APIKeyHeader: testAPIHeader}); a != nil {
		t.Fatal("expected a nil authenticator when nothing is configured")
	}
}

func TestNilAuthenticatorLetsRequestsThrough(t *testing.T) {
	var auth *Authenticator
	rec := httptest.NewRecorder()
	auth.Require(http.HandlerFunc(func(w http.ResponseWriter, _ *http.Request) {
		w.WriteHeader(http.StatusTeapot)
	})).ServeHTTP(rec, httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil))

	if rec.Code != http.StatusTeapot {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusTeapot)
	}
}

func TestGuardedRouteRejectsAnonymousRequest(t *testing.T) {
	rec := do(t, newGuardedServer(t, bothCredentials()), http.MethodGet, "/api/v1/articles")

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
	if got := rec.Header().Get("WWW-Authenticate"); !strings.HasPrefix(got, "Basic realm=") {
		t.Fatalf("WWW-Authenticate = %q, want a Basic challenge", got)
	}
	if body := rec.Body.String(); !strings.Contains(body, `"code":"unauthorized"`) {
		t.Fatalf("body = %q, want the unauthorized error envelope", body)
	}
}

func TestHealthEndpointsStayOpen(t *testing.T) {
	server := newGuardedServer(t, bothCredentials())

	for _, path := range []string{"/health/live", "/health/ready"} {
		if rec := do(t, server, http.MethodGet, path); rec.Code != http.StatusOK {
			t.Fatalf("%s status = %d, want %d", path, rec.Code, http.StatusOK)
		}
	}
}

func TestAPIKeyGrantsAccess(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
	req.Header.Set(testAPIHeader, testAPIKey)

	rec := httptest.NewRecorder()
	newGuardedServer(t, bothCredentials()).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestAnyRotatedAPIKeyIsAccepted(t *testing.T) {
	const replacement = "0011223344556677889900aabbccddeeff00112233"

	creds := bothCredentials()
	creds.APIKeys = []string{testAPIKey, replacement}
	server := newGuardedServer(t, creds)

	for _, key := range creds.APIKeys {
		req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
		req.Header.Set(testAPIHeader, key)

		rec := httptest.NewRecorder()
		server.ServeHTTP(rec, req)

		if rec.Code != http.StatusOK {
			t.Fatalf("status = %d for key %q, want %d", rec.Code, key, http.StatusOK)
		}
	}
}

func TestWrongAPIKeyIsRejected(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
	req.Header.Set(testAPIHeader, testAPIKey+"x")

	rec := httptest.NewRecorder()
	newGuardedServer(t, bothCredentials()).ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
}

func TestAPIKeyIsReadFromTheConfiguredHeaderOnly(t *testing.T) {
	creds := bothCredentials()
	creds.APIKeyHeader = "X-News-Api-Key"
	server := newGuardedServer(t, creds)

	req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
	req.Header.Set("X-API-Key", testAPIKey)

	rec := httptest.NewRecorder()
	server.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
}

func TestBasicAuthGrantsAccess(t *testing.T) {
	req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
	req.SetBasicAuth(testUsername, testPassword)

	rec := httptest.NewRecorder()
	newGuardedServer(t, bothCredentials()).ServeHTTP(rec, req)

	if rec.Code != http.StatusOK {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusOK)
	}
}

func TestBasicAuthRejectsWrongCredentials(t *testing.T) {
	cases := map[string]struct{ user, pass string }{
		"wrong password": {testUsername, testPassword + "!"},
		"wrong username": {"intruder", testPassword},
		"both wrong":     {"intruder", "hunter2"},
		"empty":          {"", ""},
	}

	server := newGuardedServer(t, bothCredentials())

	for name, tc := range cases {
		t.Run(name, func(t *testing.T) {
			req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
			req.SetBasicAuth(tc.user, tc.pass)

			rec := httptest.NewRecorder()
			server.ServeHTTP(rec, req)

			if rec.Code != http.StatusUnauthorized {
				t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
			}
		})
	}
}

// With only keys configured, a basic credential must not become a second way in.
func TestBasicAuthRejectedWhenOnlyAPIKeysConfigured(t *testing.T) {
	server := newGuardedServer(t, AuthCredentials{
		APIKeyHeader: testAPIHeader,
		APIKeys:      []string{testAPIKey},
	})

	req := httptest.NewRequest(http.MethodGet, "/api/v1/articles", nil)
	req.SetBasicAuth(testUsername, testPassword)

	rec := httptest.NewRecorder()
	server.ServeHTTP(rec, req)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
}

// An unknown path under the guarded prefix must not reveal that it is unknown
// before the caller authenticates.
func TestUnknownGuardedPathRequiresAuthFirst(t *testing.T) {
	server := newGuardedServer(t, bothCredentials())

	if rec := do(t, server, http.MethodGet, "/api/v1/nope"); rec.Code != http.StatusUnauthorized {
		t.Fatalf("anonymous status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}

	req := httptest.NewRequest(http.MethodGet, "/api/v1/nope", nil)
	req.Header.Set(testAPIHeader, testAPIKey)

	rec := httptest.NewRecorder()
	server.ServeHTTP(rec, req)

	if rec.Code != http.StatusNotFound {
		t.Fatalf("authenticated status = %d, want %d", rec.Code, http.StatusNotFound)
	}
}

func TestGuardedWriteRouteRequiresAuth(t *testing.T) {
	rec := request(t, newGuardedServer(t, bothCredentials()), http.MethodPost, "/api/v1/sources", `{"name":"x"}`)

	if rec.Code != http.StatusUnauthorized {
		t.Fatalf("status = %d, want %d", rec.Code, http.StatusUnauthorized)
	}
}
