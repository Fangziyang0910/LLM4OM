import { Languages, Monitor, Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Toaster as Sonner } from "sonner";
import { Button } from "@/components/ui/button";
import { DropdownMenu, DropdownMenuContent, DropdownMenuLabel, DropdownMenuRadioGroup, DropdownMenuRadioItem, DropdownMenuSeparator, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { locale, setLocale, t, type Locale } from "@/i18n";

export function Toaster() {
  const { resolvedTheme } = useTheme();
  return <Sonner theme={resolvedTheme === "dark" ? "dark" : "light"} position="bottom-right" closeButton richColors
    toastOptions={{ classNames: { toast: "font-sans" } }} />;
}

export function ThemeMenu() {
  const { theme, setTheme } = useTheme();
  return <DropdownMenu>
    <DropdownMenuTrigger asChild>
      <Button variant="ghost" size="icon-sm" aria-label={t("外观与语言")}><Sun className="dark:hidden" /><Moon className="hidden dark:block" /></Button>
    </DropdownMenuTrigger>
    <DropdownMenuContent align="end" side="top">
      <DropdownMenuRadioGroup value={theme ?? "system"} onValueChange={setTheme}>
        <DropdownMenuRadioItem value="light"><Sun />{t("浅色")}</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="dark"><Moon />{t("深色")}</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="system"><Monitor />{t("跟随系统")}</DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
      <DropdownMenuSeparator />
      <DropdownMenuLabel className="flex items-center gap-2 text-xs font-normal text-muted-foreground"><Languages className="size-3.5" />{t("语言")}</DropdownMenuLabel>
      <DropdownMenuRadioGroup value={locale} onValueChange={value => setLocale(value as Locale)}>
        <DropdownMenuRadioItem value="zh">中文</DropdownMenuRadioItem>
        <DropdownMenuRadioItem value="en">English</DropdownMenuRadioItem>
      </DropdownMenuRadioGroup>
    </DropdownMenuContent>
  </DropdownMenu>;
}
