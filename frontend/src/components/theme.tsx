import { Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";

export function Toaster() {
  const { resolvedTheme } = useTheme();
  return <Sonner theme={resolvedTheme === "dark" ? "dark" : "light"} position="bottom-right" closeButton richColors
    toastOptions={{ classNames: { toast: "font-sans" } }} />;
}

export function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button variant="ghost" size="icon-sm" aria-label="切换外观"><Sun className="dark:hidden" /><Moon className="hidden dark:block" /></Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" side="top">
      <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
        <DropdownMenuRadioItem value="light"><Sun />浅色</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="dark"><Moon />深色</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="system"><Monitor />跟随系统</DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>;
}
