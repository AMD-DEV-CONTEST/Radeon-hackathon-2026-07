import { cn } from "@/lib/utils";

interface WorkflowStepProps {
  step: string;
  title: string;
  description: string;
  showConnector?: boolean;
  className?: string;
}

export function WorkflowStep({
  step,
  title,
  description,
  showConnector = false,
  className,
}: WorkflowStepProps) {
  return (
    <div
      className={cn(
        "relative flex flex-col items-center text-center md:flex-1",
        className
      )}
    >
      <div className="relative z-10 flex h-14 w-14 items-center justify-center rounded-full border-2 border-primary bg-primary/10">
        <span className="text-sm font-bold text-primary">{step}</span>
      </div>
      {showConnector ? (
        <div
          aria-hidden="true"
          className="absolute left-[calc(50%+2rem)] top-7 hidden h-0.5 w-[calc(100%-1rem)] bg-primary/35 md:block"
        />
      ) : null}
      <h3 className="mt-4 text-sm font-semibold text-white">{title}</h3>
      <p className="mt-1.5 max-w-[180px] text-xs leading-relaxed text-muted-foreground">
        {description}
      </p>
    </div>
  );
}
