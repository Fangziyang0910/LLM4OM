// Runs saved before ADR-0006 use the candidate layout. Map their public names onto
// the current check layout so the same views read them; saved files are not changed.
import type { Snapshot } from "./types";

const renames: [string, string][] = [
  ['"candidates/', '"checks/'],
  ["/candidate-snapshot.json", "/record-snapshot.json"],
  ["/candidate.json", "/record.json"],
  ["/assessment.json", "/check.json"],
  ['"candidate-selection.json"', '"selection.json"'],
  ['"final_candidate_id"', '"selected_check_id"'],
  ['"candidate_id"', '"check_id"'],
  ['"assessment_ref"', '"check_ref"'],
  ['"candidate_assessed"', '"check_finished"'],
  ['"candidates":', '"checks":'],
  ['"max_candidates"', '"max_checks"'],
];

export function currentLayout(snapshot: Snapshot): Snapshot {
  if (!snapshot.bundle || !("final_candidate_id" in snapshot.bundle)) return snapshot;
  // ponytail: whole-document text mapping; a public value that literally contains these
  // quoted names would also be renamed. Replace with field-wise mapping if that ever matters.
  let text = JSON.stringify(snapshot);
  for (const [before, after] of renames) text = text.split(before).join(after);
  return JSON.parse(text) as Snapshot;
}
