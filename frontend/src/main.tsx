import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { LucideProvider } from "lucide-react";
import { createRoot } from "react-dom/client";
import { Toaster } from "sonner";
import "katex/dist/katex.min.css";
import "./style.css";
import App from "./App";

const queryClient = new QueryClient({ defaultOptions: { queries: { retry: 1 } } });

createRoot(document.getElementById("root")!).render(
  <QueryClientProvider client={queryClient}>
    <LucideProvider size={18} strokeWidth={1.75}>
      <App />
    </LucideProvider>
    <Toaster theme="system" position="bottom-right" closeButton />
  </QueryClientProvider>,
);
