import { Client } from "@langchain/langgraph-sdk";

/** The LangGraph server runs, streams and stores every run; this page is served by the same server. The SDK is
 * large, so the first page loads it separately through `api.ts`. */
export const client = new Client({ apiUrl: location.origin });
