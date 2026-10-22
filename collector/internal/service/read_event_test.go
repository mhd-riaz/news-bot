package service

import (
	"context"
	"errors"
	"testing"
	"time"

	"github.com/riaz/newscollector/internal/domain"
	"github.com/riaz/newscollector/internal/repository"
)

type fakeReadEventRepo struct {
	written []domain.ReadEvent
	err     error
	calls   int
}

var _ repository.ReadEventRepository = (*fakeReadEventRepo)(nil)

func (f *fakeReadEventRepo) CreateMany(_ context.Context, events []domain.ReadEvent) (int64, error) {
	f.calls++
	if f.err != nil {
		return 0, f.err
	}
	f.written = append(f.written, events...)
	return int64(len(events)), nil
}

func newReadEventService(repo repository.ReadEventRepository) *ReadEventService {
	now := time.Date(2026, 8, 23, 12, 0, 0, 0, time.UTC)
	return NewReadEventService(repo, func() time.Time { return now })
}

func TestRecordStoresTheWholeBatch(t *testing.T) {
	repo := &fakeReadEventRepo{}
	svc := newReadEventService(repo)

	written, err := svc.Record(context.Background(), []domain.ReadEventInput{
		{ArticleID: "0198f3d2-3333-7000-8000-000000000001", Kind: domain.ReadEventImpression, Position: 0},
		{ArticleID: "0198f3d2-3333-7000-8000-000000000002", Kind: domain.ReadEventDwell, Position: 1, Dwell: 4 * time.Second},
	})
	if err != nil {
		t.Fatalf("Record: %v", err)
	}
	if written != 2 {
		t.Errorf("written = %d, want 2", written)
	}
	if len(repo.written) != 2 {
		t.Fatalf("stored %d events, want 2", len(repo.written))
	}
	if got := repo.written[1].DwellMillis; got != 4000 {
		t.Errorf("dwell = %d ms, want 4000", got)
	}
}

// The only client is this application's own page, so an invalid event is a bug
// in it. Dropping the offender and storing the rest would hide that behind data
// that merely looks thinner than expected.
func TestRecordRejectsTheWholeBatchWhenOneEventIsInvalid(t *testing.T) {
	repo := &fakeReadEventRepo{}
	svc := newReadEventService(repo)

	_, err := svc.Record(context.Background(), []domain.ReadEventInput{
		{ArticleID: "0198f3d2-3333-7000-8000-000000000001", Kind: domain.ReadEventImpression},
		{ArticleID: "not-a-uuid", Kind: domain.ReadEventImpression},
	})
	if !errors.Is(err, domain.ErrValidation) {
		t.Fatalf("error = %v, want ErrValidation", err)
	}
	if repo.calls != 0 {
		t.Errorf("repository was called %d times, want 0", repo.calls)
	}
}

func TestRecordRejectsAnEmptyOrOversizedBatch(t *testing.T) {
	repo := &fakeReadEventRepo{}
	svc := newReadEventService(repo)

	oversized := make([]domain.ReadEventInput, domain.MaxReadEventBatch+1)
	for i := range oversized {
		oversized[i] = domain.ReadEventInput{
			ArticleID: "0198f3d2-3333-7000-8000-000000000001",
			Kind:      domain.ReadEventImpression,
		}
	}

	for name, batch := range map[string][]domain.ReadEventInput{
		"empty":     nil,
		"oversized": oversized,
	} {
		t.Run(name, func(t *testing.T) {
			if _, err := svc.Record(context.Background(), batch); !errors.Is(err, domain.ErrValidation) {
				t.Fatalf("error = %v, want ErrValidation", err)
			}
		})
	}
	if repo.calls != 0 {
		t.Errorf("repository was called %d times, want 0", repo.calls)
	}
}

func TestRecordTranslatesRepositoryFailure(t *testing.T) {
	repo := &fakeReadEventRepo{err: repository.ErrNotFound}
	svc := newReadEventService(repo)

	_, err := svc.Record(context.Background(), []domain.ReadEventInput{
		{ArticleID: "0198f3d2-3333-7000-8000-000000000001", Kind: domain.ReadEventClick},
	})
	if !errors.Is(err, ErrNotFound) {
		t.Fatalf("error = %v, want ErrNotFound", err)
	}
}
