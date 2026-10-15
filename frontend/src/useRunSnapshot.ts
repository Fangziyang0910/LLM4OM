import { currentLayout } from "./legacyRun";
import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "./api";
import type { JobRecord, Notice, Snapshot } from "./types";

export function useRunSnapshot(notice: Notice) {
  const [jobs, setJobs] = useState<JobRecord[]>([]);
  const [currentJob, setCurrentJob] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<string | null>(null);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const target = useRef<{ job: string; run: string | null } | null>(null);
  const requestSequence = useRef(0);
  const jobsSequence = useRef(0);
  const fingerprint = useRef("");

  const refreshJobs = useCallback(async () => {
    const sequence = ++jobsSequence.current;
    const result = await api<{ jobs: JobRecord[] }>("/api/jobs");
    if (sequence === jobsSequence.current) setJobs(result.jobs);
  }, []);

  const refreshRun = useCallback(async () => {
    const selection = target.current;
    if (!selection) return null;
    const sequence = ++requestSequence.current;
    let result: Snapshot;
    try {
      result = currentLayout(await api<Snapshot>(`/api/jobs/${selection.job}${selection.run ? "?run_id=" + selection.run : ""}`));
    } catch (error) {
      if (sequence !== requestSequence.current || target.current !== selection) return null;
      throw error;
    }
    if (sequence !== requestSequence.current || target.current !== selection) return null;
    const nextFingerprint = JSON.stringify([result.job, result.artifacts, result.events, result.versions, result.latest_run_id]);
    if (nextFingerprint !== fingerprint.current) {
      fingerprint.current = nextFingerprint;
      setSnapshot(result);
    }
    const error = result.bundle?.error || result.job.error;
    if (error) notice(error.message, true);
    return result;
  }, [notice]);

  const selectRun = useCallback((job: string | null, run: string | null = null) => {
    target.current = job ? { job, run } : null;
    requestSequence.current++;
    fingerprint.current = "";
    setCurrentJob(job);
    setSelectedRun(run);
    setSnapshot(null);
    return refreshRun();
  }, [refreshRun]);

  useEffect(() => {
    let stopped = false;
    let timer: ReturnType<typeof setTimeout>;
    const poll = async () => {
      try {
        await refreshJobs();
        if (!stopped) await refreshRun();
      } catch (error) {
        if (!stopped) notice((error as Error).message, true);
      } finally {
        if (!stopped) timer = setTimeout(poll, 1500);
      }
    };
    timer = setTimeout(poll, 1500);
    return () => { stopped = true; clearTimeout(timer); requestSequence.current++; jobsSequence.current++; };
  }, [notice, refreshJobs, refreshRun]);

  useEffect(() => {
    Object.assign(window, { currentJob, selectedRun, snapshot });
  }, [currentJob, selectedRun, snapshot]);

  return { jobs, currentJob, selectedRun, snapshot, refreshJobs, refreshRun, selectRun };
}
