import * as React from "react"
import { Tooltip } from "radix-ui"

import { cn } from "@/lib/utils"

function TooltipProvider({
  delayDuration = 200,
  ...props
}: React.ComponentProps<typeof Tooltip.Provider>) {
  return <Tooltip.Provider delayDuration={delayDuration} {...props} />
}

function TooltipRoot({
  ...props
}: React.ComponentProps<typeof Tooltip.Root>) {
  return <Tooltip.Root {...props} />
}

function TooltipTrigger({
  ...props
}: React.ComponentProps<typeof Tooltip.Trigger>) {
  return <Tooltip.Trigger {...props} />
}

function TooltipContent({
  className,
  sideOffset = 4,
  ...props
}: React.ComponentProps<typeof Tooltip.Content>) {
  return (
    <Tooltip.Portal>
      <Tooltip.Content
        sideOffset={sideOffset}
        className={cn(
          "z-50 max-w-xs rounded-md bg-primary px-3 py-1.5 text-xs text-primary-foreground shadow-md animate-in fade-in-0 zoom-in-95",
          className
        )}
        {...props}
      />
    </Tooltip.Portal>
  )
}

export {
  TooltipProvider,
  TooltipRoot as TooltipBase,
  TooltipTrigger,
  TooltipContent,
}
