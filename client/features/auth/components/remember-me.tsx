"use client";

import { Checkbox } from "@/components/ui/checkbox";
import { Label } from "@/components/ui/label";

interface RememberMeProps {
  id?: string;
  checked: boolean;
  disabled?: boolean;
  onCheckedChange: (checked: boolean) => void;
}

export function RememberMe({
  id = "remember-me",
  checked,
  disabled = false,
  onCheckedChange,
}: RememberMeProps) {
  return (
    <div className="flex items-center gap-2.5">
      <Checkbox
        id={id}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onCheckedChange}
        aria-describedby={`${id}-description`}
      />
      <div className="flex flex-col">
        <Label
          htmlFor={id}
          className="cursor-pointer normal-case tracking-normal text-sm font-medium text-white"
        >
          Remember me
        </Label>
        <span id={`${id}-description`} className="sr-only">
          Keep me signed in on this device
        </span>
      </div>
    </div>
  );
}
