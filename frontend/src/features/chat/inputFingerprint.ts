import { sha256 } from "js-sha256";

/** Match the server's checkpoint input without sending the attachment contents again. */
export function inputFingerprint(data: Record<string, string>, description = ""): string {
  const files = Object.entries(data).map(([name, text]) => sha256.create().update(name).update("\0").update(text).hex());
  return sha256(sha256(description) + files.sort().join(""));
}
