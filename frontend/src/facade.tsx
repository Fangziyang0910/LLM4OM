// 浏览器级公共渲染门面:与原 visuals.js 相同的命令式调用形状,
// 通过 flushSync 同步渲染,供页面内调试与浏览器验收直接调用。
import { createRoot, type Root } from "react-dom/client";
import { flushSync } from "react-dom";
import { Decision } from "./components/Decision";
import { Records } from "./components/Records";
import { RuntimeDetails } from "./components/RuntimeDetails";
import { artifactKey } from "./ui";
import type { Snapshot } from "./types";

const roots = new WeakMap<HTMLElement, Root>();

const mount = (host: HTMLElement, node: React.ReactNode) => {
  let root = roots.get(host);
  if (!root) {
    root = createRoot(host);
    roots.set(host, root);
  }
  flushSync(() => root!.render(node));
};

export function installUiFacade() {
  (window as any).UI = {
    artifactKey,
    records: (host: HTMLElement, value: any, tab: string, contents: Record<string, any>, dataPreviews = {}) =>
      mount(host, <Records value={value} tab={tab} contents={contents} dataPreviews={dataPreviews} />),
    runtimeDetails: (host: HTMLElement, snapshot: Snapshot) =>
      mount(host, <RuntimeDetails snapshot={snapshot} />),
    decision: (
      host: HTMLElement,
      solve: any,
      solution: any,
      _ledger: any,
      snapshot: Snapshot,
      solvedIR: any,
    ) =>
      mount(
        host,
        <Decision
          solve={solve}
          solution={solution}
          snapshot={snapshot}
          solvedIR={solvedIR}
          onOpenDiagnostics={() => {}}
        />,
      ),
  };
}
