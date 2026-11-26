import { expect, test } from "vitest";
import { en } from "@/locales/en";
import { SCENARIOS } from "@/features/composer/scenarios";
test("every scenario text has English", () => {
  const missing = SCENARIOS.flatMap(item => [item.industry, item.title, item.summary, item.description]).filter(text => !(text in en));
  expect(missing).toEqual([]);
});
