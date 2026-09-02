import { cn } from "@/lib/utils";

function Select({
  className,
  children,
  ...props
}: React.SelectHTMLAttributes<HTMLSelectElement>) {
  return (
    <select
      data-slot="select"
      className={cn(
        "flex h-8 w-full items-center justify-between rounded-lg border border-border bg-background px-3 py-1 text-sm shadow-sm outline-none transition-all focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50",
        className
      )}
      {...props}
    >
      {children}
    </select>
  );
}

function SelectItem({
  children,
  ...props
}: React.OptionHTMLAttributes<HTMLOptionElement>) {
  return <option {...props}>{children}</option>;
}

export { Select, SelectItem };
