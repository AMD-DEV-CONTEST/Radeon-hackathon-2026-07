import DashboardAuthGate from "@/components/dashboard/DashboardAuthGate";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <DashboardAuthGate>
      <div className="dashboard-shell flex min-h-0 flex-1">{children}</div>
    </DashboardAuthGate>
  );
}
