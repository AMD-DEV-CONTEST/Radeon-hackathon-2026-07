package protocol

import (
	"errors"
	"fmt"
	"sync"
)

// ── Seat Protocol ───────────────────────────────────────────────────
//
// Seat Protocol defines user/* seats with typed operation whitelists.
// A seat declares an identity and the operations it is allowed to perform.

// Op represents a typed operation permission.
type Op string

const (
	OpVaultRead    Op = "vault.read"
	OpMemorySet    Op = "memory.set"
	OpMemoryGet    Op = "memory.get"
	OpSparkRecall  Op = "spark.recall"
	OpSeatDeclare  Op = "seat.declare"
)

// Seat represents a user/* seat with its operation whitelist.
type Seat struct {
	Name        string   `json:"name"`
	Description string   `json:"description,omitempty"`
	Ops         []Op     `json:"ops"` // whitelist of permitted ops
}

// HasOp checks whether the seat is permitted to perform an operation.
func (s *Seat) HasOp(op Op) bool {
	for _, p := range s.Ops {
		if p == op {
			return true
		}
	}
	return false
}

// SeatStore is the interface for seat declaration and lookup.
type SeatStore interface {
	Declare(seat Seat) error
	Get(name string) (*Seat, error)
}

// ── Errors ─────────────────────────────────────────────────────────

var (
	ErrSeatNotFound    = errors.New("protocol: seat not found")
	ErrSeatAlreadyDeclared = errors.New("protocol: seat already declared")
	ErrOpNotPermitted  = errors.New("protocol: operation not permitted for this seat")
)

// ── In-Memory Seat Store ───────────────────────────────────────────

// MemSeatStore is an in-memory implementation for testing.
type MemSeatStore struct {
	mu    sync.RWMutex
	seats map[string]*Seat
}

func NewMemSeatStore() *MemSeatStore {
	return &MemSeatStore{seats: make(map[string]*Seat)}
}

func (s *MemSeatStore) Declare(seat Seat) error {
	s.mu.Lock()
	defer s.mu.Unlock()
	if _, ok := s.seats[seat.Name]; ok {
		return ErrSeatAlreadyDeclared
	}
	s.seats[seat.Name] = &Seat{
		Name:        seat.Name,
		Description: seat.Description,
		Ops:         seat.Ops,
	}
	return nil
}

func (s *MemSeatStore) Get(name string) (*Seat, error) {
	s.mu.RLock()
	defer s.mu.RUnlock()
	seat, ok := s.seats[name]
	if !ok {
		return nil, ErrSeatNotFound
	}
	return seat, nil
}

// ── Common Seat Definitions ────────────────────────────────────────

// AnniversaryKeeperSeat returns the standard user/anniversary-keeper seat.
func AnniversaryKeeperSeat() Seat {
	return Seat{
		Name:        "user/anniversary-keeper",
		Description: "Manages anniversary vault entries and recall sparks",
		Ops:         []Op{OpVaultRead, OpSparkRecall},
	}
}

// MemoryKeeperSeat returns the standard user/memory-keeper seat.
func MemoryKeeperSeat() Seat {
	return Seat{
		Name:        "user/memory-keeper",
		Description: "Manages life-memory storage and retrieval",
		Ops:         []Op{OpMemorySet, OpMemoryGet},
	}
}

// ── Authorization Check ────────────────────────────────────────────

// Authorize checks whether the named seat is permitted to perform the given op.
func Authorize(store SeatStore, seatName string, op Op) error {
	seat, err := store.Get(seatName)
	if err != nil {
		return fmt.Errorf("protocol: %w: %s", err, seatName)
	}
	if !seat.HasOp(op) {
		return fmt.Errorf("%w: seat=%s op=%s", ErrOpNotPermitted, seatName, op)
	}
	return nil
}
