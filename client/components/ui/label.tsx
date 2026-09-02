import * as React from "react";

import { cn } from "@/lib/utils";

const Label = React.forwardRef<
  HTMLLabelElement,
  React.ComponentProps<"label">
>(({ className, ...props }, ref) => {
  return (
    <label
      ref={ref}
      data-slot="label"
      className={cn(
        "text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground",
        className
      )}
      {...props}
    />
  );
});

Label.displayName = "Label";

export { Label };
