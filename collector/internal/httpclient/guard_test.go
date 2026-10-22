package httpclient

import (
	"errors"
	"net/netip"
	"strings"
	"testing"
)

func TestBlockedReasonRejectsUnroutableAddresses(t *testing.T) {
	blocked := []string{
		"0.0.0.0",
		"0.1.2.3",
		"10.1.2.3",
		"100.64.0.1",
		"127.0.0.1",
		"169.254.169.254", // the cloud metadata endpoint an SSRF is usually aimed at
		"172.16.5.4",
		"192.0.0.1",
		"192.0.2.10",
		"192.168.1.1",
		"198.18.0.1",
		"198.51.100.7",
		"203.0.113.9",
		"224.0.0.1",
		"255.255.255.255",
		"::",
		"::1",
		"64:ff9b::a00:1",
		"2001:db8::1",
		"2002:c0a8:0101::1",
		"fc00::1",
		"fd12:3456::1",
		"fe80::1",
		"fec0::1",
		"ff02::1",
		"::ffff:127.0.0.1", // loopback wearing an IPv6 costume
		"::ffff:10.0.0.1",
	}

	for _, raw := range blocked {
		addr := netip.MustParseAddr(raw)
		if reason := blockedReason(addr); reason == "" {
			t.Errorf("blockedReason(%s) = %q, want it blocked", raw, reason)
		}
	}
}

func TestBlockedReasonAllowsPublicAddresses(t *testing.T) {
	allowed := []string{"1.1.1.1", "8.8.8.8", "151.101.1.140", "2606:4700::1111", "2a03:2880:f10c::1"}

	for _, raw := range allowed {
		addr := netip.MustParseAddr(raw)
		if reason := blockedReason(addr); reason != "" {
			t.Errorf("blockedReason(%s) = %q, want it allowed", raw, reason)
		}
	}
}

func TestCheckURL(t *testing.T) {
	tests := []struct {
		name string
		url  string
		want error
	}{
		{name: "https", url: "https://news.example.com/feed.xml"},
		{name: "http with explicit port", url: "http://news.example.com:80/feed.xml"},
		{name: "public literal address", url: "https://8.8.8.8/feed.xml"},
		{name: "ftp scheme", url: "ftp://news.example.com/feed.xml", want: ErrInvalidURL},
		{name: "file scheme", url: "file:///etc/passwd", want: ErrInvalidURL},
		{name: "no host", url: "http:///feed.xml", want: ErrInvalidURL},
		{name: "credentials", url: "https://user:secret@news.example.com/feed.xml", want: ErrInvalidURL},
		{name: "non-web port", url: "http://news.example.com:6379/", want: ErrBlockedAddress},
		{name: "loopback literal", url: "http://127.0.0.1/feed.xml", want: ErrBlockedAddress},
		{name: "metadata endpoint", url: "http://169.254.169.254/latest/meta-data/", want: ErrBlockedAddress},
		{name: "private literal", url: "https://192.168.0.10/feed.xml", want: ErrBlockedAddress},
		{name: "ipv6 loopback literal", url: "http://[::1]/feed.xml", want: ErrBlockedAddress},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			_, err := checkURL(tc.url, true)
			switch {
			case tc.want == nil && err != nil:
				t.Fatalf("checkURL(%q) = %v, want no error", tc.url, err)
			case tc.want != nil && !errors.Is(err, tc.want):
				t.Fatalf("checkURL(%q) = %v, want %v", tc.url, err, tc.want)
			}
		})
	}
}

func TestCheckURLUnguardedStillRejectsUnfetchableURLs(t *testing.T) {
	// Turning the address guard off is for reaching a test server, not for
	// relaxing what counts as a fetchable URL.
	if _, err := checkURL("http://127.0.0.1:8080/feed.xml", false); err != nil {
		t.Fatalf("unguarded loopback should be allowed, got %v", err)
	}
	if _, err := checkURL("file:///etc/passwd", false); !errors.Is(err, ErrInvalidURL) {
		t.Fatalf("file scheme = %v, want ErrInvalidURL", err)
	}
	if _, err := checkURL("https://user:secret@example.com/", false); !errors.Is(err, ErrInvalidURL) {
		t.Fatalf("credentials = %v, want ErrInvalidURL", err)
	}
}

func TestGuardDial(t *testing.T) {
	tests := []struct {
		name    string
		network string
		address string
		wantErr bool
	}{
		{name: "public host", network: "tcp4", address: "8.8.8.8:443"},
		{name: "loopback", network: "tcp4", address: "127.0.0.1:443", wantErr: true},
		{name: "metadata", network: "tcp4", address: "169.254.169.254:80", wantErr: true},
		{name: "private", network: "tcp4", address: "10.0.0.5:80", wantErr: true},
		{name: "ipv6 unique local", network: "tcp6", address: "[fd00::1]:443", wantErr: true},
		{name: "forbidden port", network: "tcp4", address: "8.8.8.8:22", wantErr: true},
		{name: "non-tcp network", network: "udp", address: "8.8.8.8:443", wantErr: true},
		{name: "unparsable", network: "tcp4", address: "not-an-address", wantErr: true},
	}

	for _, tc := range tests {
		t.Run(tc.name, func(t *testing.T) {
			err := guardDial(tc.network, tc.address, nil)
			if tc.wantErr && !errors.Is(err, ErrBlockedAddress) {
				t.Fatalf("guardDial(%q, %q) = %v, want ErrBlockedAddress", tc.network, tc.address, err)
			}
			if !tc.wantErr && err != nil {
				t.Fatalf("guardDial(%q, %q) = %v, want no error", tc.network, tc.address, err)
			}
		})
	}
}

// The guard runs after DNS resolution, so a name that resolves to a blocked
// address is stopped at the socket rather than at the URL. This is what closes
// the rebinding window between checking a name and connecting to it.
func TestGuardDialIsWhatStopsAResolvedName(t *testing.T) {
	const feedURL = "http://rebind.example.com/feed.xml"

	if _, err := checkURL(feedURL, true); err != nil {
		t.Fatalf("a name is not judged before resolution, got %v", err)
	}
	err := guardDial("tcp4", "169.254.169.254:80", nil)
	if !errors.Is(err, ErrBlockedAddress) {
		t.Fatalf("resolved address = %v, want ErrBlockedAddress", err)
	}
	if !strings.Contains(err.Error(), "169.254.169.254") {
		t.Errorf("error should name the address it refused, got %v", err)
	}
}
