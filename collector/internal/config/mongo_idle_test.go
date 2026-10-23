package config

import (
	"strings"
	"testing"
	"time"
)

func TestMongoIdleLimitConfigAndEnvironment(t *testing.T) {
	path := writeConfig(t, "mongo:\n  max_connection_idle_time: 60s\n")
	cfg, err := Load(path, SkipAuthValidation)
	if err != nil || cfg.Mongo.MaxConnIdleTime != time.Minute {
		t.Fatalf("idle config = %v, %v", cfg, err)
	}
	t.Setenv("NEWS_MONGO_MAX_CONNECTION_IDLE_TIME", "15s")
	cfg, err = Load(path, SkipAuthValidation)
	if err != nil || cfg.Mongo.MaxConnIdleTime != 15*time.Second {
		t.Fatalf("idle environment = %v, %v", cfg, err)
	}
	t.Setenv("NEWS_MONGO_MAX_CONNECTION_IDLE_TIME", "0")
	cfg, err = Load(path, SkipAuthValidation)
	if err != nil || cfg.Mongo.MaxConnIdleTime != 0 {
		t.Fatalf("zero idle limit = %v, %v", cfg, err)
	}
	t.Setenv("NEWS_MONGO_MAX_CONNECTION_IDLE_TIME", "-1s")
	_, err = Load(path, SkipAuthValidation)
	if err == nil || !strings.Contains(err.Error(), "max_connection_idle_time") {
		t.Fatalf("negative idle limit error = %v", err)
	}
}

func TestMongoIdleLimitPreservesExistingDefault(t *testing.T) {
	t.Parallel()
	if Default().Mongo.MaxConnIdleTime != 0 {
		t.Fatal("existing collector defaults must leave the driver's URI/default idle policy unchanged")
	}
}
