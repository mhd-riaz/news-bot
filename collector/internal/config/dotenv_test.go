package config

import (
	"os"
	"path/filepath"
	"testing"
)

func writeEnvFile(t *testing.T, body string) string {
	t.Helper()
	path := filepath.Join(t.TempDir(), ".env")
	if err := os.WriteFile(path, []byte(body), 0o600); err != nil {
		t.Fatalf("write env file: %v", err)
	}
	return path
}

func TestLoadEnvFileSetsVariables(t *testing.T) {
	t.Setenv(EnvPrefix+"AUTH_BASIC_USERNAME", "")
	os.Unsetenv(EnvPrefix + "AUTH_BASIC_USERNAME")

	path := writeEnvFile(t, EnvPrefix+"AUTH_BASIC_USERNAME=operator\n")

	if err := LoadEnvFile(path); err != nil {
		t.Fatalf("LoadEnvFile: %v", err)
	}
	if got := os.Getenv(EnvPrefix + "AUTH_BASIC_USERNAME"); got != "operator" {
		t.Fatalf("value = %q, want %q", got, "operator")
	}
}

// The platform injects the real secret; the file must not be able to shadow it.
func TestLoadEnvFileDoesNotOverrideTheEnvironment(t *testing.T) {
	t.Setenv(EnvPrefix+"MONGO_DATABASE", "from-environment")

	path := writeEnvFile(t, EnvPrefix+"MONGO_DATABASE=from-file\n")

	if err := LoadEnvFile(path); err != nil {
		t.Fatalf("LoadEnvFile: %v", err)
	}
	if got := os.Getenv(EnvPrefix + "MONGO_DATABASE"); got != "from-environment" {
		t.Fatalf("value = %q, want the environment to win", got)
	}
}

func TestLoadEnvFileIgnoresAMissingFile(t *testing.T) {
	if err := LoadEnvFile(filepath.Join(t.TempDir(), "absent")); err != nil {
		t.Fatalf("LoadEnvFile: %v", err)
	}
	if err := LoadEnvFile(""); err != nil {
		t.Fatalf("LoadEnvFile(\"\"): %v", err)
	}
}

func TestEnvFilePathHonoursTheOverride(t *testing.T) {
	if got := EnvFilePath(); got != DefaultEnvFile {
		t.Fatalf("EnvFilePath() = %q, want %q", got, DefaultEnvFile)
	}

	t.Setenv(EnvPrefix+"ENV_FILE", "/run/secrets/news.env")

	if got := EnvFilePath(); got != "/run/secrets/news.env" {
		t.Fatalf("EnvFilePath() = %q, want the override", got)
	}
}
