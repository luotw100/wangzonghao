import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider, useIsFetching } from "@tanstack/react-query";
import { App } from "./App";
import "./styles.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      // Cached data paints instantly on navigation; a background revalidate
      // still fires (staleTime is short) so the view self-corrects against
      // the server. Server is always the source of truth.
      staleTime: 1500,
      gcTime: 5 * 60 * 1000,
      refetchOnWindowFocus: true,
      refetchOnReconnect: true,
      retry: 1,
    },
  },
});

// Subtle global "syncing" chip: visible whenever any query is fetching in the
// background — including the revalidate that fires when you (re)enter a page.
function SyncIndicator() {
  const fetching = useIsFetching();
  if (!fetching) return null;
  return (
    <div className="pointer-events-none fixed right-4 top-3 z-[60] flex items-center gap-2 rounded-full border border-[var(--color-line)] bg-[var(--color-bg-elev)]/90 px-3 py-1 text-[11.5px] text-[var(--color-ink-3)] shadow">
      <span className="h-2.5 w-2.5 animate-spin rounded-full border border-[var(--color-ink-4)] border-t-[var(--color-brass)]" />
      同步中…
    </div>
  );
}

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <QueryClientProvider client={queryClient}>
      <App />
      <SyncIndicator />
    </QueryClientProvider>
  </StrictMode>,
);
