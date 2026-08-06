package main

import (
	"bytes"
	"strings"
	"testing"
)

func TestProfileCmdSetThenList(t *testing.T) {
	newProfileStoreDir(t)
	var out, errOut bytes.Buffer
	if e := runProfileCmd([]string{"set", "x1", "--agent-id", "x1"}, &out, &errOut); e != nil {
		t.Fatalf("set: %v (stderr=%q)", e, errOut.String())
	}
	out.Reset()
	if e := runProfileCmd([]string{"list"}, &out, &errOut); e != nil {
		t.Fatalf("list: %v", e)
	}
	if !strings.Contains(out.String(), "x1") {
		t.Fatalf("list output missing x1: %q", out.String())
	}
}

func TestProfileCmdSetRequiresAgentID(t *testing.T) {
	newProfileStoreDir(t)
	var out, errOut bytes.Buffer
	if e := runProfileCmd([]string{"set", "x1"}, &out, &errOut); e == nil {
		t.Fatal("set without --agent-id should error")
	}
}

func TestProfileCmdGetMissing(t *testing.T) {
	newProfileStoreDir(t)
	var out, errOut bytes.Buffer
	if e := runProfileCmd([]string{"get", "nope"}, &out, &errOut); e == nil {
		t.Fatal("get missing should error")
	}
}

func TestProfileCmdGetJSONFlagBeforeName(t *testing.T) {
	newProfileStoreDir(t)
	_ = profileSet(Profile{Name: "x1", AgentID: "x1"})
	var out, errOut bytes.Buffer
	if e := runProfileCmd([]string{"get", "--json", "x1"}, &out, &errOut); e != nil {
		t.Fatalf("get --json x1: %v (stderr=%q)", e, errOut.String())
	}
	if !strings.Contains(out.String(), `"agent_id"`) {
		t.Fatalf("--json output should contain agent_id: %q", out.String())
	}
}
