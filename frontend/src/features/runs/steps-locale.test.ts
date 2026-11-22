import { expect, test } from "vitest";
import { t } from "@/i18n";
import { phases, roleLabel, roleName } from "./steps";
import type { Step } from "./types";

test("localized role labels do not merge calls from different modeling nodes", () => {
  const steps: Step[] = [
    { id: "code", type: "llm", title: "llmopt.code", time: 1, content: "" },
    { id: "agent", type: "llm", title: "trival.code_agent", time: 2, content: "" },
    { id: "artifact", type: "artifact", title: "Code", node: "trival.code_agent", time: 3, content: "" },
  ];

  expect(roleLabel("llmopt.code")).toBe(t("求解代码"));
  expect(roleLabel("trival.code_agent")).toBe(t("求解代码"));
  const grouped = phases(steps);
  expect(grouped[0].calls.map(call => call.id)).toEqual(["agent"]);
  expect(grouped[1].calls.map(call => call.id)).toEqual(["code"]);
  expect(roleName("trival.code_agent")).toBe("code agent");
});

test("unknown plugin role labels retain a readable role identifier", () => {
  expect(roleLabel("plugin.custom_validator")).toBe("custom validator");
});
