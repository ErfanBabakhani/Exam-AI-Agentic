"use client";

type RecentFileKind = "exam" | "student";

export type RecentFileEntry = {
  id: string;
  kind: RecentFileKind;
  name: string;
  size: number;
  lastUsedAt: string;
  reusableInSession: boolean;
};

const STORAGE_KEY = "zanista_recent_files";
const MAX_RECENT_FILES = 20;
const sessionFiles = new Map<string, File>();

function sortByRecent(left: RecentFileEntry, right: RecentFileEntry) {
  return new Date(right.lastUsedAt).getTime() - new Date(left.lastUsedAt).getTime();
}

function dedupeLatestByName(entries: RecentFileEntry[]): RecentFileEntry[] {
  const latestByName = new Map<string, RecentFileEntry>();
  for (const entry of [...entries].sort(sortByRecent)) {
    const key = `${entry.kind}:${entry.name.toLowerCase()}`;
    if (!latestByName.has(key)) {
      latestByName.set(key, entry);
    }
  }
  return [...latestByName.values()].sort(sortByRecent);
}

function readRecentEntries(): RecentFileEntry[] {
  if (typeof window === "undefined") {
    return [];
  }
  try {
    const raw = window.localStorage.getItem(STORAGE_KEY);
    if (!raw) {
      return [];
    }
    const parsed = JSON.parse(raw) as Omit<RecentFileEntry, "reusableInSession">[];
    return parsed.map((entry) => ({
      ...entry,
      reusableInSession: sessionFiles.has(entry.id),
    }));
  } catch {
    return [];
  }
}

function persistEntries(entries: RecentFileEntry[]) {
  if (typeof window === "undefined") {
    return;
  }
  window.localStorage.setItem(
    STORAGE_KEY,
    JSON.stringify(
      entries.map(({ reusableInSession: _reusableInSession, ...entry }) => entry),
    ),
  );
}

export function rememberRecentFile(kind: RecentFileKind, file: File): RecentFileEntry[] {
  const id = `${kind}:${file.name}:${file.size}:${file.lastModified}`;
  sessionFiles.set(id, file);
  const nextEntry: RecentFileEntry = {
    id,
    kind,
    name: file.name,
    size: file.size,
    lastUsedAt: new Date().toISOString(),
    reusableInSession: true,
  };
  const existing = readRecentEntries().filter(
    (entry) => entry.id !== id && !(entry.kind === kind && entry.name.toLowerCase() === file.name.toLowerCase()),
  );
  const updated = dedupeLatestByName([nextEntry, ...existing]).slice(0, MAX_RECENT_FILES);
  persistEntries(updated);
  return updated;
}

export function listRecentFiles(kind: RecentFileKind): RecentFileEntry[] {
  return dedupeLatestByName(
    readRecentEntries()
      .filter((entry) => entry.kind === kind && sessionFiles.has(entry.id))
      .map((entry) => ({
        ...entry,
        reusableInSession: true,
      })),
  );
}

export function getReusableRecentFile(id: string): File | null {
  return sessionFiles.get(id) ?? null;
}
