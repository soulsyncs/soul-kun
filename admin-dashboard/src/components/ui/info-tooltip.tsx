/**
 * InfoTooltip - hover "?" icon showing beginner-friendly explanation
 */

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
  return (
    <TooltipBase>
      <TooltipTrigger asChild>
        <button
          type="button"
          className="inline-flex items-center justify-center rounded-full text-muted-foreground hover:text-foreground transition-colors ml-1"
          aria-label="説明を表示"
        >
          <Info className="h-3.5 w-3.5" />
        </button>
      </TooltipTrigger>
      <TooltipContent>{text}</TooltipContent>
    </TooltipBase>
  );
}
