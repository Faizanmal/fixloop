import * as React from "react";
import { cn } from "@/lib/utils";

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement> {
  variant?:
    | "default"
    | "destructive"
    | "outline"
    | "secondary"
    | "ghost"
    | "link"
    | "gradient"
    | "emerald";
  size?: "default" | "sm" | "lg" | "icon";
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant = "default", size = "default", ...props }, ref) => {
    const baseStyles =
      "inline-flex items-center justify-center whitespace-nowrap rounded-lg text-xs font-semibold ring-offset-background transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer select-none font-mono";

    const variantStyles = {
      default:
        "bg-cyan-600 text-white shadow hover:bg-cyan-500 active:scale-[0.98]",
      destructive:
        "bg-rose-950/80 text-rose-300 border border-rose-800/80 hover:bg-rose-900 active:scale-[0.98]",
      outline:
        "border border-slate-700 bg-slate-900/60 text-slate-200 hover:bg-slate-800 hover:text-white",
      secondary:
        "bg-slate-800 text-slate-200 hover:bg-slate-700 hover:text-white",
      ghost:
        "text-slate-400 hover:bg-slate-800/60 hover:text-slate-100",
      link: "text-cyan-400 underline-offset-4 hover:underline",
      gradient:
        "bg-gradient-to-r from-cyan-500 to-indigo-600 text-white shadow-md shadow-cyan-950/40 hover:from-cyan-400 hover:to-indigo-500 active:scale-[0.98]",
      emerald:
        "bg-gradient-to-r from-emerald-500 to-teal-600 text-white shadow-md shadow-emerald-950/40 hover:from-emerald-400 hover:to-teal-500 active:scale-[0.98]",
    };

    const sizeStyles = {
      default: "h-9 px-4 py-2",
      sm: "h-7 rounded-md px-2.5 text-[11px]",
      lg: "h-10 rounded-xl px-5 text-sm",
      icon: "h-9 w-9 p-0",
    };

    return (
      <button
        ref={ref}
        className={cn(baseStyles, variantStyles[variant], sizeStyles[size], className)}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button };
