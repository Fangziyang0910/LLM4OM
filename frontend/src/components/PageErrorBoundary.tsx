import { Component, type ReactNode } from "react";
import { RefreshCw, TriangleAlert } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Empty, EmptyContent, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from "@/components/ui/empty";
import { t } from "@/i18n";

/** A failed lazy import must leave navigation and a reload action available. */
export class PageErrorBoundary extends Component<{ children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() {
    if (!this.state.failed) return this.props.children;
    return <Empty role="alert" className="h-full">
      <EmptyHeader><EmptyMedia variant="icon"><TriangleAlert /></EmptyMedia>
        <EmptyTitle>{t("页面未能加载")}</EmptyTitle>
        <EmptyDescription>{t("请重新加载页面后继续，已保存的内容会保留。")}</EmptyDescription>
      </EmptyHeader>
      <EmptyContent><Button variant="outline" onClick={() => location.reload()}><RefreshCw />{t("重新加载")}</Button></EmptyContent>
    </Empty>;
  }
}
