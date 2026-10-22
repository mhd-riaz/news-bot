package httpclient

import (
	"fmt"
	"net"
	"net/netip"
	"net/url"
	"strings"
	"syscall"
)

// allowedPorts are the only destination ports a guarded fetch may reach. Feeds
// are published on the web ports; anything else is far more likely to be an
// internal service than a newspaper.
var allowedPorts = map[string]struct{}{
	"":    {},
	"80":  {},
	"443": {},
}

// reservedPrefixes are ranges netip's classification helpers do not already
// cover but that must never be reachable from a user-supplied feed URL.
//
// The 6to4 and NAT64 ranges are listed because they embed an IPv4 address: a
// request to one of them is a request to whatever IPv4 host is encoded inside,
// which would otherwise bypass the IPv4 rules entirely.
var reservedPrefixes = []netip.Prefix{
	netip.MustParsePrefix("0.0.0.0/8"),       // "this network"
	netip.MustParsePrefix("100.64.0.0/10"),   // carrier-grade NAT
	netip.MustParsePrefix("192.0.0.0/24"),    // IETF protocol assignments
	netip.MustParsePrefix("192.0.2.0/24"),    // TEST-NET-1
	netip.MustParsePrefix("198.18.0.0/15"),   // benchmarking
	netip.MustParsePrefix("198.51.100.0/24"), // TEST-NET-2
	netip.MustParsePrefix("203.0.113.0/24"),  // TEST-NET-3
	netip.MustParsePrefix("240.0.0.0/4"),     // reserved, includes broadcast
	netip.MustParsePrefix("64:ff9b::/96"),    // NAT64, embeds IPv4
	netip.MustParsePrefix("100::/64"),        // discard-only
	netip.MustParsePrefix("2001:db8::/32"),   // documentation
	netip.MustParsePrefix("2002::/16"),       // 6to4, embeds IPv4
	netip.MustParsePrefix("fec0::/10"),       // deprecated site-local
	netip.MustParsePrefix("::ffff:0:0:0/96"), // IPv4-translated
	netip.MustParsePrefix("::/104"),          // IPv4-compatible, deprecated
}

// checkURL rejects a URL that must not be fetched no matter where it resolves:
// a scheme other than HTTP, embedded credentials, a missing host, or — when the
// address guard is on — a port that is not a web port or a host that is already
// a blocked literal address. It returns the parsed URL so a caller does not
// parse twice.
func checkURL(raw string, guarded bool) (*url.URL, error) {
	u, err := url.Parse(strings.TrimSpace(raw))
	if err != nil {
		return nil, fmt.Errorf("%w: not a valid URL", ErrInvalidURL)
	}
	if err := checkParsedURL(u, guarded); err != nil {
		return nil, err
	}
	return u, nil
}

func checkParsedURL(u *url.URL, guarded bool) error {
	switch strings.ToLower(u.Scheme) {
	case "http", "https":
	default:
		return fmt.Errorf("%w: scheme %q is not http or https", ErrInvalidURL, u.Scheme)
	}
	if u.Host == "" {
		return fmt.Errorf("%w: no host", ErrInvalidURL)
	}
	// Credentials would be sent to whatever a redirect points at, and would end
	// up in any error the fetch returns.
	if u.User != nil {
		return fmt.Errorf("%w: must not embed credentials", ErrInvalidURL)
	}
	if !guarded {
		return nil
	}
	if _, ok := allowedPorts[u.Port()]; !ok {
		return fmt.Errorf("%w: port %s is not allowed; only 80 and 443 are", ErrBlockedAddress, u.Port())
	}
	// A URL naming a blocked IP outright is rejected before any connection is
	// attempted. Names are checked after resolution instead, by the dial guard.
	if addr, err := netip.ParseAddr(strings.Trim(u.Hostname(), "[]")); err == nil {
		if reason := blockedReason(addr); reason != "" {
			return fmt.Errorf("%w: %s is a %s", ErrBlockedAddress, addr, reason)
		}
	}
	return nil
}

// guardDial is installed as net.Dialer.Control, so it runs after DNS resolution
// and immediately before the socket connects to that exact address. Checking
// here rather than at URL-validation time is what makes the guard immune to DNS
// rebinding: a name that resolved to a public address a moment ago cannot be
// re-pointed at 169.254.169.254 in between.
func guardDial(network, address string, _ syscall.RawConn) error {
	switch network {
	case "tcp", "tcp4", "tcp6":
	default:
		return fmt.Errorf("%w: network %q is not allowed", ErrBlockedAddress, network)
	}

	host, port, err := net.SplitHostPort(address)
	if err != nil {
		return fmt.Errorf("%w: unparsable destination %q", ErrBlockedAddress, address)
	}
	if _, ok := allowedPorts[port]; !ok {
		return fmt.Errorf("%w: port %s is not allowed; only 80 and 443 are", ErrBlockedAddress, port)
	}

	addr, err := netip.ParseAddr(host)
	if err != nil {
		return fmt.Errorf("%w: unparsable destination address %q", ErrBlockedAddress, host)
	}
	if reason := blockedReason(addr); reason != "" {
		return fmt.Errorf("%w: %s is a %s", ErrBlockedAddress, addr, reason)
	}
	return nil
}

// blockedReason names why an address may not be contacted, or returns "" when
// it is a routable public address.
func blockedReason(addr netip.Addr) string {
	if !addr.IsValid() {
		return "invalid address"
	}
	// An IPv4-mapped IPv6 address is the IPv4 address it carries, so it must be
	// judged by the IPv4 rules rather than slipping through as "some IPv6".
	addr = addr.Unmap()

	switch {
	case addr.IsUnspecified():
		return "unspecified address"
	case addr.IsLoopback():
		return "loopback address"
	case addr.IsPrivate():
		return "private address"
	case addr.IsLinkLocalUnicast(), addr.IsLinkLocalMulticast():
		return "link-local address"
	case addr.IsInterfaceLocalMulticast(), addr.IsMulticast():
		return "multicast address"
	}

	for _, p := range reservedPrefixes {
		if p.Contains(addr) {
			return "reserved address"
		}
	}
	return ""
}
