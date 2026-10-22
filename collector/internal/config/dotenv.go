package config

import (
	"errors"
	"fmt"
	"os"

	"github.com/joho/godotenv"
)

// DefaultEnvFile is the dotenv file loaded when none is named.
const DefaultEnvFile = ".env"

// EnvFilePath returns the dotenv file to load, honouring NEWS_ENV_FILE so a
// container can point at a mounted secret without a command-line flag.
func EnvFilePath() string {
	if p := os.Getenv(EnvPrefix + "ENV_FILE"); p != "" {
		return p
	}
	return DefaultEnvFile
}

// LoadEnvFile applies the KEY=VALUE pairs in path to the process environment.
//
// Variables already present are left alone, so a value injected by the platform
// always beats the file: the same binary reads secrets from .env on a laptop and
// from Coolify's injected environment in the homelab, with no branch either way.
// A missing file is not an error, because in deployment there is none.
func LoadEnvFile(path string) error {
	if path == "" {
		return nil
	}
	if _, err := os.Stat(path); err != nil {
		if errors.Is(err, os.ErrNotExist) {
			return nil
		}
		return fmt.Errorf("read env file %q: %w", path, err)
	}
	if err := godotenv.Load(path); err != nil {
		return fmt.Errorf("parse env file %q: %w", path, err)
	}
	return nil
}
