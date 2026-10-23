import { useMemo, useState } from "react";
import { ChevronLeft, ChevronRight, CodeXml, Download, FileText, GitCompare, type LucideIcon, Sigma, Table2 } from "lucide-react";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Button } from "@/components/ui/button";
import { t } from "@/i18n";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia } from "@/components/ui/empty";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tabs, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Toggle } from "@/components/ui/toggle";
import { versions, type Version } from "@/features/runs/steps";
import { parseDelimited } from "@/features/runs/tables";
import type { Language } from "@/types";
import type { RunValues, Step } from "@/features/runs/types";
import { Code, CopyButton, Diff, Markdown, Plain, download } from "@/components/Content";
import { Solution } from "@/features/runs/Solution";

export type Tab = "solution" | "formulation" | "code" | "problem";
const TABS: [Tab, string, LucideIcon][] = [
  ["solution", t("解"), Table2], ["formulation", t("数学模型"), Sigma], ["code", t("求解代码"), CodeXml], ["problem", t("问题与数据"), FileText],
];

/** What the run produced: the solution, the formulation and the code (each in every version), and the problem. */
export function Outputs({ values, steps, active, tab, setTab, picked, setPicked, language, finished }: {
  values: RunValues; steps: Step[]; active: boolean; tab: Tab; setTab: (tab: Tab) => void;
  picked: Partial<Record<"formulation" | "code", string>>; setPicked: (key: "formulation" | "code", id: string | undefined) => void;
  language?: Language; finished: boolean;
}) {
  const formulations = useMemo(() => versions(steps, "formulation", values.formulation), [steps, values.formulation]);
  const codes = useMemo(() => versions(steps, "code", values.code), [steps, values.code]);
  const counts: Partial<Record<Tab, number>> = { formulation: formulations.length, code: codes.length };

  return <div className="flex h-full min-h-0 flex-col">
    <Tabs value={tab} onValueChange={value => setTab(value as Tab)} className="shrink-0 gap-0">
      <TabsList variant="line" aria-label={t("运行产物")} className="h-11 w-full justify-start overflow-x-auto rounded-none border-b px-3">
        {TABS.map(([id, label, TabIcon]) => <TabsTrigger key={id} value={id} className="flex-none px-2 sm:px-2.5 [&_svg]:hidden sm:[&_svg]:inline-block">
          <TabIcon />{label}
          {(counts[id] ?? 0) > 1 ? <span className="rounded-full bg-muted px-1.5 text-[10px] leading-4 text-muted-foreground tabular">{counts[id]}</span> : null}
          {active && (counts[id] ?? 0) > 0 ? <span className="size-1.5 animate-pulse rounded-full bg-primary" aria-label={t("正在更新")} /> : null}
        </TabsTrigger>)}
      </TabsList>
    </Tabs>
    <div role="tabpanel" className="min-h-0 flex-1 overflow-y-auto p-4 md:p-5">
      {tab === "solution" ? values.solve ? <Solution solve={values.solve} />
        : <Blank icon={Table2} text={active ? t("代码在沙箱中求解后，解会显示在这里。") : values.failure ? t("没有求解结果。") : finished ? t("没有求解结果。") : t("运行没有完成。")} />
        : null}
      {tab === "formulation" ? <Versioned key="formulation" items={formulations} picked={picked.formulation} pick={id => setPicked("formulation", id)}
        noun={t("数学模型")} active={active} file="formulation.md"
        empty={active ? t("方法给出数学模型后显示在这里。") : t("这个方法没有单独给出数学模型；请看求解代码。")}
        render={text => <Markdown text={text} />} /> : null}
      {tab === "code" ? <Versioned key="code" items={codes} picked={picked.code} pick={id => setPicked("code", id)}
        noun={t("代码")} active={active} file="model.py" extra={language?.name}
        empty={active ? t("方法写出代码后显示在这里。") : t("没有求解代码。")}
        render={text => <Code text={text} />} /> : null}
      {tab === "problem" ? <Problem values={values} /> : null}
    </div>
  </div>;
}

function Blank({ icon: BlankIcon, text }: { icon: LucideIcon; text: string }) {
  return <Empty className="h-full border-0">
    <EmptyHeader><EmptyMedia variant="icon"><BlankIcon /></EmptyMedia><EmptyDescription>{text}</EmptyDescription></EmptyHeader>
  </Empty>;
}

/** One output in every version the method wrote: step through them, compare with the previous one, copy or download. */
function Versioned({ items, picked, pick, noun, active, file, extra, empty, render }: {
  items: Version[]; picked?: string; pick: (id: string | undefined) => void; noun: string; active: boolean; file: string;
  extra?: string; empty: string; render: (text: string) => React.ReactNode;
}) {
  const [compare, setCompare] = useState(false);
  if (!items.length) return <Blank icon={noun === t("代码") ? CodeXml : Sigma} text={empty} />;
  const current = items.find(item => item.id === picked) ?? items[items.length - 1];
  const position = items.indexOf(current);
  const latest = position === items.length - 1;
  const previous = position > 0 ? items[position - 1] : null;
  const go = (index: number) => pick(index === items.length - 1 ? undefined : items[index].id);

  return <div className="flex flex-col gap-4">
    <div className="flex flex-wrap items-center gap-2">
      {items.length > 1 ? <div className="flex items-center gap-1">
        <Button variant="outline" size="icon-sm" aria-label={t("上一版")} disabled={position === 0} onClick={() => go(position - 1)}><ChevronLeft /></Button>
        <Select value={current.id} onValueChange={id => go(items.findIndex(item => item.id === id))}>
          <SelectTrigger size="sm" aria-label={t("{noun}版本", { noun })} className="max-w-72"><SelectValue /></SelectTrigger>
          <SelectContent>{items.map((item, number) => <SelectItem key={item.id} value={item.id}>
            {t("第 {number} 版", { number: number + 1 })}<span className="text-muted-foreground">{t(item.title)}</span></SelectItem>)}</SelectContent>
        </Select>
        <Button variant="outline" size="icon-sm" aria-label={t("下一版")} disabled={latest} onClick={() => go(position + 1)}><ChevronRight /></Button>
      </div> : <span className="text-xs text-muted-foreground">{t(current.title)}</span>}
      {extra ? <span className="text-xs text-muted-foreground">{extra}</span> : null}
      <span className="ml-auto flex items-center gap-1">
        {previous ? <Toggle size="sm" pressed={compare} onPressedChange={setCompare} aria-label={t("与上一版对比")} className="h-8 text-xs">
          <GitCompare />{t("对比上一版")}</Toggle> : null}
        <CopyButton text={current.text} label={t("复制{noun}", { noun })} />
        <Button variant="ghost" size="icon-sm" aria-label={t("下载{noun}", { noun })} title={t("下载")} onClick={() => download(file, current.text)}><Download /></Button>
      </span>
    </div>
    {!latest ? <Alert className="py-2"><AlertDescription className="flex flex-wrap items-center gap-x-2 text-xs">
      {t(active ? "这是第 {number} 版，不是目前的{noun}。" : "这是第 {number} 版，不是最终的{noun}。", { number: position + 1, noun })}
      <Button variant="link" size="xs" className="h-auto p-0" onClick={() => pick(undefined)}>{t("看最新一版")}</Button></AlertDescription></Alert> : null}
    {compare && previous ? <Diff before={previous.text} after={current.text} /> : render(current.text)}
  </div>;
}

function Problem({ values }: { values: RunValues }) {
  const files = Object.entries(values.data ?? {});
  return <div className="flex flex-col gap-4">
    <Card className="gap-3 py-4 shadow-none">
      <CardHeader className="flex items-center gap-2 px-4">
        <CardTitle className="text-sm">{t("问题描述")}</CardTitle>
        <CopyButton text={values.description ?? ""} label={t("复制问题")} className="ml-auto" />
      </CardHeader>
      <CardContent className="px-4 text-sm leading-relaxed whitespace-pre-wrap">{values.description}</CardContent>
    </Card>
    {files.map(([name, content]) => <DataFile key={name} name={name} content={content} />)}
    {values.spec ? <details className="rounded-lg border p-4">
      <summary className="cursor-pointer text-sm font-medium">{t("运行配置")}</summary>
      <Plain className="mt-3 max-h-96 overflow-auto">{JSON.stringify(values.spec, null, 2)}</Plain>
    </details> : null}
  </div>;
}

function DataFile({ name, content }: { name: string; content: string }) {
  const table = useMemo(() => parseDelimited(content, name.endsWith(".tsv") ? "\t" : ","), [name, content]);
  return <Card className="gap-3 py-4 shadow-none">
    <CardHeader className="flex items-center gap-2 px-4">
      <FileText className="size-4 text-muted-foreground" />
      <CardTitle className="font-mono text-sm">{name}</CardTitle>
      <span className="text-xs text-muted-foreground">{t("{count} 行", { count: content.split("\n").filter(Boolean).length })}</span>
      <Button variant="ghost" size="icon-sm" className="ml-auto" aria-label={t("下载 {name}", { name })} onClick={() => download(name, content)}><Download /></Button>
    </CardHeader>
    <CardContent className="px-4">
      {table ? <div className="max-h-96 overflow-auto rounded-lg border">
        <Table className="text-[13px]">
          <TableHeader className="sticky top-0 bg-muted/80 backdrop-blur"><TableRow>
            {table[0].map((cell, index) => <TableHead key={index} className="h-8 font-mono text-xs">{cell}</TableHead>)}
          </TableRow></TableHeader>
          <TableBody>{table.slice(1, 501).map((row, index) => <TableRow key={index}>
            {row.map((cell, column) => <TableCell key={column} className={column ? "py-1.5 text-right font-mono tabular" : "py-1.5 font-mono font-medium"}>{cell}</TableCell>)}
          </TableRow>)}</TableBody>
        </Table>
      </div> : <Plain className="max-h-96 overflow-y-auto">{content}</Plain>}
    </CardContent>
  </Card>;
}
