import { cn } from "@/lib/utils";

function ScrollArea({
  className,
  children,
  ...props
}: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      data-slot="scroll-area"
      className={cn("overflow-auto", className)}
      {...props}
    >
      {children}
    </div>
  );
}

export { ScrollArea };
