import { Toaster as Sonner } from "sonner"

import { cn } from "@/lib/utils"

const Toaster = ({ className, toastOptions, ...props }) => (
  <Sonner
    className={cn("toaster group", className)}
    toastOptions={{
      classNames: {
        toast:
          "group toast group-[.toaster]:bg-card group-[.toaster]:text-card-foreground " +
          "group-[.toaster]:border-border group-[.toaster]:shadow-lg",
        description: "group-[.toast]:text-muted-foreground",
        actionButton: "group-[.toast]:bg-primary group-[.toast]:text-primary-foreground",
        cancelButton: "group-[.toast]:bg-secondary group-[.toast]:text-secondary-foreground",
      },
      ...toastOptions,
    }}
    {...props}
  />
)

export { Toaster }
