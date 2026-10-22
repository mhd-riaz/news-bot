// Package mongodb owns MongoDB connection management, the canonical collection
// names and the index plan. Domain and service code never imports the driver.
package mongodb

import (
	"context"
	"errors"
	"fmt"
	"time"

	"go.mongodb.org/mongo-driver/v2/mongo"
	"go.mongodb.org/mongo-driver/v2/mongo/options"
	"go.mongodb.org/mongo-driver/v2/mongo/readpref"
)

// Settings describes how to reach MongoDB. It mirrors the config package
// without importing it, so this package stays independently testable.
type Settings struct {
	URI                    string
	Database               string
	AppName                string
	ConnectTimeout         time.Duration
	ServerSelectionTimeout time.Duration
	OperationTimeout       time.Duration
	MaxPoolSize            uint64
	MinPoolSize            uint64
}

// Client is the owned MongoDB handle for one database.
type Client struct {
	client *mongo.Client
	db     *mongo.Database
}

// Connect builds a client from settings. The driver connects lazily, so a
// successful return does not mean the deployment is reachable; call Ping.
func Connect(s Settings) (*Client, error) {
	if s.URI == "" {
		return nil, errors.New("mongodb: uri must not be empty")
	}
	if s.Database == "" {
		return nil, errors.New("mongodb: database must not be empty")
	}

	opts := options.Client().
		ApplyURI(s.URI).
		SetAppName(s.AppName).
		SetConnectTimeout(s.ConnectTimeout).
		SetServerSelectionTimeout(s.ServerSelectionTimeout).
		SetTimeout(s.OperationTimeout).
		SetMaxPoolSize(s.MaxPoolSize).
		SetMinPoolSize(s.MinPoolSize)

	c, err := mongo.Connect(opts)
	if err != nil {
		return nil, fmt.Errorf("mongodb: build client: %w", err)
	}

	return &Client{client: c, db: c.Database(s.Database)}, nil
}

// Database returns the handle used by repository implementations.
func (c *Client) Database() *mongo.Database { return c.db }

// Ping verifies the deployment is reachable, satisfying the readiness check.
func (c *Client) Ping(ctx context.Context) error {
	if err := c.client.Ping(ctx, readpref.Primary()); err != nil {
		return fmt.Errorf("mongodb: ping: %w", err)
	}
	return nil
}

// Close releases pooled connections, waiting for in-flight work until ctx ends.
func (c *Client) Close(ctx context.Context) error {
	if err := c.client.Disconnect(ctx); err != nil {
		return fmt.Errorf("mongodb: disconnect: %w", err)
	}
	return nil
}
