import * as React from "react";
import { cn } from "@/lib/utils";

export interface BadgeProps extends React.HTMLAttributes<HTMLDivElement> {
  variant?:
    | "default"
    | "secondary"
    | "destructive"
    | "outline"
    | "success"
    | "warning"
    | "info"
    | "purple";
}

function Badge({ className, variant = "default", ...props }: BadgeProps) {
  const baseStyles =
    "inline-flex items-center rounded-full border px-2.5 py-0.5 text-[10px] font-mono font-semibold transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2";

  const variantStyles = {
    default:
      "border-transparent bg-slate-800 text-slate-200 hover:bg-slate-700",
    secondary:
      "border-slate-800 bg-slate-900/60 text-slate-300 hover:bg-slate-800",
    destructive:
      "border-rose-800/60 bg-rose-950/40 text-rose-300",
    outline:
      "border-slate-700 text-slate-300",
    success:
      "border-emerald-500/30 bg-emerald-500/10 text-emerald-400",
    warning:
      "border-amber-500/30 bg-amber-500/10 text-amber-400",
    info:
      "border-cyan-500/30 bg-cyan-500/10 text-cyan-400",
    purple:
      "border-purple-500/30 bg-purple-500/10 text-purple-400",
  };

  return (
    <div
      className={cn(baseStyles, variantStyles[variant], className)}
      {...props}
    />
  );
}

export { Badge };
