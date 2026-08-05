import { render, screen, fireEvent } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { SurfaceDrawer } from "../SurfaceDrawer";
import { SURFACE_GROUPS } from "@/lib/surfaceGroups";

const trust = SURFACE_GROUPS.find((g) => g.id === "trust")!;
const system = SURFACE_GROUPS.find((g) => g.id === "system")!;

describe("SurfaceDrawer", () => {
  it("lists the group's members with the group blurb", () => {
    render(<SurfaceDrawer group={trust} onOpen={vi.fn()} onClose={vi.fn()} />);
    expect(screen.getByText(trust.blurb)).toBeInTheDocument();
    for (const m of trust.members) {
      expect(screen.getByText(m.label)).toBeInTheDocument();
    }
  });

  it("explains what a surface is and does before you open it", () => {
    // The whole point of the drawer: no unexplained icons.
    const member = trust.members[0];
    render(<SurfaceDrawer group={trust} onOpen={vi.fn()} onClose={vi.fn()} />);

    expect(screen.queryByText(member.what)).not.toBeInTheDocument();
    fireEvent.click(screen.getByText(member.label));
    expect(screen.getByText(member.what)).toBeInTheDocument();
    expect(screen.getByText(member.does)).toBeInTheDocument();
  });

  it("lets the user pick the destination rather than hard-coding it", () => {
    const onOpen = vi.fn();
    const member = trust.members[0];
    render(<SurfaceDrawer group={trust} onOpen={onOpen} onClose={vi.fn()} />);
    fireEvent.click(screen.getByText(member.label));

    fireEvent.click(screen.getByRole("button", { name: /panel/i }));
    expect(onOpen).toHaveBeenLastCalledWith(member, "panel");

    fireEvent.click(screen.getByRole("button", { name: /dock/i }));
    expect(onOpen).toHaveBeenLastCalledWith(member, "dock");
  });

  it("marks the surface that is already open", () => {
    const member = trust.members[1];
    render(
      <SurfaceDrawer group={trust} activeSurfaceId={member.id} onOpen={vi.fn()} onClose={vi.fn()} />
    );
    expect(screen.getByText("Open")).toBeInTheDocument();
  });

  it("hides Determinex's own release tooling unless internal", () => {
    // Mission Control / Roadmap track shipping Determinex, not the user's
    // project, and must not appear in an end-user build.
    const { rerender } = render(
      <SurfaceDrawer group={system} onOpen={vi.fn()} onClose={vi.fn()} />
    );
    expect(screen.queryByText("Mission Control")).not.toBeInTheDocument();

    rerender(<SurfaceDrawer group={system} onOpen={vi.fn()} onClose={vi.fn()} showInternal />);
    expect(screen.getByText("Mission Control")).toBeInTheDocument();
  });

  it("closes when asked", () => {
    const onClose = vi.fn();
    render(<SurfaceDrawer group={trust} onOpen={vi.fn()} onClose={onClose} />);
    fireEvent.click(screen.getByTestId("surface-drawer-close"));
    expect(onClose).toHaveBeenCalled();
  });
});
