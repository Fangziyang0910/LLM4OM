import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ThemeProvider } from "next-themes";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/inter";
import "@fontsource-variable/jetbrains-mono";
import "./index.css";
import App from "./App";
import { Toaster } from "./components/theme";
import { TooltipProvider } from "./components/ui/tooltip";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
    <QueryClientProvider client={queryClient}>
      <TooltipProvider delayDuration={300}>
        <App />
      </TooltipProvider>
      <Toaster />
    </QueryClientProvider>
  </ThemeProvider>,
);
