package runid

import (
	"crypto/rand"
	"encoding/binary"
	"fmt"
	"time"
)

// New returns a UUIDv7-compatible, time-sortable execution identity.
func New(now time.Time) (string, error) {
	var id [16]byte
	milliseconds := uint64(now.UTC().UnixMilli())
	id[0] = byte(milliseconds >> 40)
	id[1] = byte(milliseconds >> 32)
	id[2] = byte(milliseconds >> 24)
	id[3] = byte(milliseconds >> 16)
	id[4] = byte(milliseconds >> 8)
	id[5] = byte(milliseconds)
	if _, err := rand.Read(id[6:]); err != nil {
		return "", fmt.Errorf("generate run ID: %w", err)
	}
	id[6] = (id[6] & 0x0f) | 0x70
	id[8] = (id[8] & 0x3f) | 0x80
	return format(id), nil
}

func Timestamp(value string) (time.Time, error) {
	var a uint32
	var b, c, d uint16
	var e uint64
	if _, err := fmt.Sscanf(value, "%08x-%04x-%04x-%04x-%012x", &a, &b, &c, &d, &e); err != nil {
		return time.Time{}, fmt.Errorf("parse run ID: %w", err)
	}
	var id [16]byte
	binary.BigEndian.PutUint32(id[0:4], a)
	binary.BigEndian.PutUint16(id[4:6], b)
	binary.BigEndian.PutUint16(id[6:8], c)
	binary.BigEndian.PutUint16(id[8:10], d)
	for index := 0; index < 6; index++ {
		id[10+index] = byte(e >> (40 - 8*index))
	}
	if id[6]>>4 != 7 || id[8]>>6 != 2 {
		return time.Time{}, fmt.Errorf("run ID is not UUIDv7")
	}
	milliseconds := uint64(id[0])<<40 | uint64(id[1])<<32 | uint64(id[2])<<24 |
		uint64(id[3])<<16 | uint64(id[4])<<8 | uint64(id[5])
	return time.UnixMilli(int64(milliseconds)).UTC(), nil
}

func format(id [16]byte) string {
	return fmt.Sprintf("%08x-%04x-%04x-%04x-%012x",
		binary.BigEndian.Uint32(id[0:4]),
		binary.BigEndian.Uint16(id[4:6]),
		binary.BigEndian.Uint16(id[6:8]),
		binary.BigEndian.Uint16(id[8:10]),
		uint64(id[10])<<40|uint64(id[11])<<32|uint64(id[12])<<24|
			uint64(id[13])<<16|uint64(id[14])<<8|uint64(id[15]),
	)
}
