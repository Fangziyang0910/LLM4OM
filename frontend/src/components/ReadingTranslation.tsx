import { useState, type ReactNode } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "@/api";
import { locale, t } from "@/i18n";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

/** A reading view; source text still supplies copies, downloads and subsequent modeling. */
export function ReadingTranslation({ text, active = false, render }: {
  text: string; active?: boolean; render: (text: string) => ReactNode;
}) {
  const [showTranslation, setShowTranslation] = useState(true);
  const [requested, setRequested] = useState(false);
  const prose = text.replace(/```[\s\S]*?```|`[^`]*`|\$\$[\s\S]*?\$\$|\$[^$\n]+\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)/g, "");
  const chinese = prose.match(/[㐀-鿿]/g)?.length ?? 0;
  const words = prose.match(/[A-Za-z]{2,}/g)?.length ?? 0;
  const needed = requested || (locale === "en" ? chinese > 0 : words > chinese);
  const query = useQuery({
    queryKey: ["reading-translation", locale, text],
    queryFn: () => api<{ original: string; translation: string }>("/api/translations", { text, locale }),
    enabled: needed && !active && showTranslation, staleTime: Infinity, retry: false,
  });
  if (active) return render(text);
  if (!needed) return <div className="flex min-w-0 flex-col gap-3">
    {locale === "zh" && words > 0 ? <Button variant="link" size="xs" className="h-auto self-start p-0"
      onClick={() => { setRequested(true); setShowTranslation(true); }}>{t("翻译为中文")}</Button> : null}
    {render(text)}
  </div>;
  const translated = query.data?.original === text ? query.data.translation : undefined;
  return <div className="flex min-w-0 flex-col gap-3">
    <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
      {query.isFetching ? <span role="status" className="flex items-center gap-1.5"><Spinner />{t("正在生成阅读译文……")}</span>
        : <span>{showTranslation && translated ? t("阅读译文") : t("原文")}</span>}
      <Button variant="link" size="xs" className="h-auto p-0" onClick={() => setShowTranslation(!showTranslation)}>
        {showTranslation ? t("查看原文") : t("查看译文")}
      </Button>
      <span>{t("译文仅供阅读，复制和下载保留原文。")}</span>
    </div>
    {query.isError && showTranslation ? <div role="alert" className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
      {t("阅读译文暂时无法生成，当前显示原文。")}
      <Button variant="outline" size="xs" onClick={() => void query.refetch()}>{t("重试")}</Button>
    </div> : null}
    {render(showTranslation && translated ? translated : text)}
  </div>;
}
