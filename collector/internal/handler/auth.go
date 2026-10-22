package handler

import (
	"crypto/sha256"
	"crypto/subtle"
	"net/http"
)

// authRealm is fixed rather than derived from configuration, so no configured
// value can reach the WWW-Authenticate header and inject into it.
const authRealm = "news-collector"

// AuthCredentials is the set of credentials an Authenticator will accept.
type AuthCredentials struct {
	APIKeyHeader  string
	APIKeys       []string
	BasicUsername string
	BasicPassword string
}

// Authenticator guards the API with an API key header or HTTP basic auth.
// Either one is sufficient: keys suit scripts and scrapers, basic auth suits a
// browser or curl session, and both are checked the same way.
//
// Only digests are retained. Comparing fixed-width digests in constant time
// keeps the answer independent of both the value and the length of what was
// presented, so a caller cannot learn a credential by timing its rejection.
type Authenticator struct {
	apiKeyHeader string
	apiKeys      [][sha256.Size]byte
	basicUser    [sha256.Size]byte
	basicPass    [sha256.Size]byte
	basicEnabled bool
}

// NewAuthenticator builds an Authenticator from creds. It returns nil when no
// credential is configured, which callers must treat as "auth is off" — the
// configuration layer is what refuses that combination in production.
func NewAuthenticator(creds AuthCredentials) *Authenticator {
	if len(creds.APIKeys) == 0 && creds.BasicUsername == "" {
		return nil
	}

	a := &Authenticator{
		apiKeyHeader: creds.APIKeyHeader,
		apiKeys:      make([][sha256.Size]byte, 0, len(creds.APIKeys)),
		basicEnabled: creds.BasicUsername != "",
	}
	for _, key := range creds.APIKeys {
		a.apiKeys = append(a.apiKeys, sha256.Sum256([]byte(key)))
	}
	if a.basicEnabled {
		a.basicUser = sha256.Sum256([]byte(creds.BasicUsername))
		a.basicPass = sha256.Sum256([]byte(creds.BasicPassword))
	}
	return a
}

// Require wraps next so that only an authenticated request reaches it. A nil
// Authenticator passes everything through, so an unguarded development stack
// needs no separate routing path.
func (a *Authenticator) Require(next http.Handler) http.Handler {
	if a == nil {
		return next
	}
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if a.authenticate(r) {
			next.ServeHTTP(w, r)
			return
		}
		// Advertising basic auth lets a browser or curl prompt for a password.
		// The response says nothing about which scheme would have worked, or
		// whether the path exists.
		w.Header().Set("WWW-Authenticate", `Basic realm="`+authRealm+`", charset="UTF-8"`)
		writeError(w, http.StatusUnauthorized, CodeUnauthorized, "valid credentials are required")
	})
}

func (a *Authenticator) authenticate(r *http.Request) bool {
	if key := r.Header.Get(a.apiKeyHeader); key != "" && a.matchAPIKey(key) {
		return true
	}
	if user, pass, ok := r.BasicAuth(); ok && a.matchBasic(user, pass) {
		return true
	}
	return false
}

// matchAPIKey checks every configured key without stopping at the first match,
// so the time taken does not reveal a key's position in the rotation list.
func (a *Authenticator) matchAPIKey(presented string) bool {
	digest := sha256.Sum256([]byte(presented))

	var matched int
	for i := range a.apiKeys {
		matched |= subtle.ConstantTimeCompare(digest[:], a.apiKeys[i][:])
	}
	return matched == 1
}

func (a *Authenticator) matchBasic(user, pass string) bool {
	if !a.basicEnabled {
		return false
	}
	userDigest := sha256.Sum256([]byte(user))
	passDigest := sha256.Sum256([]byte(pass))

	// Bitwise AND, not &&: both comparisons always run, so a wrong username
	// costs the same as a wrong password.
	matched := subtle.ConstantTimeCompare(userDigest[:], a.basicUser[:]) &
		subtle.ConstantTimeCompare(passDigest[:], a.basicPass[:])
	return matched == 1
}
