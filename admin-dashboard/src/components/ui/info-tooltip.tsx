/**
 * InfoTooltip - tap/click or hover "ℹ" icon showing beginner-friendly explanation
 * Supports both hover (desktop) and tap (mobile/touchscreen)
 */

import { useState } from 'react';
import { Info } from 'lucide-react';
import {
  TooltipBase,
  TooltipTrigger,
  TooltipContent,
} from '@/components/ui/tooltip';

interface InfoTooltipProps {
  text: string;
}

export function InfoTooltip({ text }: InfoTooltipProps) {
  const [open, setOpen] = useState(false);

  return (
    <TooltipBase open={open} onOpenChange={setOpen}>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-full text-muted-foreground hover:text-foreground transition-colors ml-1"
          aria-label="説明を表示"
          onClick={(e) => {
            e.stopPropagation();
            setOpen((prev) => !prev);
          }}
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </TooltipBase>
  );
}
