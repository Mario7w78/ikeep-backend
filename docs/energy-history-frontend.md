# Energy History — Frontend Integration Guide

## Overview

The `nivel_energia` field in `ContextoUsuario` tells the scheduler your current energy level so it can avoid scheduling hard tasks when you're low. **But a single value is noisy** — maybe you just woke up groggy, or had a bad hour.

To make better decisions, the scheduler needs **patterns, not snapshots**.

This document describes how the **mobile/web frontend** stores, manages, and sends energy history to the backend so the scheduler can detect whether low energy is a trend or just a bad moment.

---

## Energy Scale: 1–3

Energy is measured on a **3-level scale** to keep it simple for the user:

| Value | Label | Emoji | Meaning |
|-------|-------|-------|---------|
| **1** | Baja | 😴 | Low energy — avoid hard tasks |
| **2** | Normal | 🙂 | Default — regular scheduling |
| **3** | Alta | ⚡ | High energy — can handle anything |

The backend treats `nivel < 2` as "low energy" for pattern detection. If the user doesn't set it, defaults to **2** (Normal).

---

## Design Principle

**No backend persistence.** Energy history lives entirely on the device. The backend never stores it, never owns it, and never requests it asynchronously. The frontend includes it as part of the regular schedule request payload.

This gives us:
- **Privacy** — data never leaves the device
- **Simplicity** — no new tables, migrations, or auth requirements
- **Offline-first** — history is available even without connectivity

---

## Data Structure

### Individual Record

Each entry records one energy report from the user:

```typescript
interface EnergyRecord {
  /** ISO 8601 datetime when the user reported their energy */
  timestamp: string;
  /** Energy level 1–3 (1=baja, 2=normal, 3=alta) */
  nivel: number;
  /** Day of week: 0=Monday, 6=Sunday (derived from timestamp) */
  dia_semana: number;
  /** Optional context the user can provide */
  contexto?: string;
}
```

### History Payload

Sent inside `ContextoUsuario`:

```typescript
interface ContextoUsuario {
  nivel_energia: number;            // 1–3, current energy (required)
  horario_inicio: number;           // active hours start (minutes from midnight)
  horario_fin: number;              // active hours end
  bloques_sueno: BloqueSueno[];     // sleep blocks
  historial_energia: EnergyRecord[]; // optional, last 14 days
}
```

**The field is optional.** If not present or empty, the scheduler falls back to the current single-value behavior (RB-01).

---

## Storage

### Mobile (React Native / Expo)

Use `AsyncStorage` (or `expo-secure-store` for sensitive contexts):

```typescript
const STORAGE_KEY = '@ikeep/energy_history';

// Save a new entry
async function saveEnergyRecord(record: EnergyRecord): Promise<void> {
  const raw = await AsyncStorage.getItem(STORAGE_KEY);
  const history: EnergyRecord[] = raw ? JSON.parse(raw) : [];
  history.push(record);
  // Keep only last 90 days to avoid unbounded growth
  const cutoff = Date.now() - 90 * 24 * 60 * 60 * 1000;
  const pruned = history.filter(e => new Date(e.timestamp).getTime() > cutoff);
  await AsyncStorage.setItem(STORAGE_KEY, JSON.stringify(pruned));
}

// Read history for API call
async function getEnergyHistory(days: number = 14): Promise<EnergyRecord[]> {
  const raw = await AsyncStorage.getItem(STORAGE_KEY);
  if (!raw) return [];
  const history: EnergyRecord[] = JSON.parse(raw);
  const cutoff = Date.now() - days * 24 * 60 * 60 * 1000;
  return history.filter(e => new Date(e.timestamp).getTime() > cutoff);
}
```

### Web (Desktop / PWA)

Use `localStorage` with the same pattern.

---

## When to Collect Energy

### 1. On schedule request (minimum)

When the user opens the "Generate Schedule" screen, show a quick energy picker:

```typescript
// Before calling POST /api/v1/horarios/generar
const currentEnergy = await showEnergyPrompt(); // returns 1–3
const history = await getEnergyHistory(14);

const payload = {
  ...requestBody,
  contexto_usuario: {
    ...contextoUsuario,
    nivel_energia: currentEnergy,
    historial_energia: history,
  },
};
```

### 2. Passive collection (recommended)

Ask for energy once per day at a natural moment (opening the app, completing a task, etc.). This builds history even on days the user doesn't generate a schedule.

```typescript
// On app launch or task completion
if (!hasReportedEnergyToday()) {
  const nivel = await showEnergyPrompt();
  await saveEnergyRecord({
    timestamp: new Date().toISOString(),
    nivel,
    dia_semana: new Date().getDay(),
  });
}
```

### 3. Context hints (optional — but valuable)

Allow the user to add short optional context:

```
"dormí mal"
"después del gym"
"semana de parciales"
"recién me levanté"
```

This text is **not used by the scheduler** yet, but it's stored for future features (e.g., detecting that poor sleep correlates with low energy).

---

## Backend Payload Format

Here's how the full `ContextoUsuario` looks on the wire with history:

```json
{
  "nivel_energia": 1,
  "horario_inicio": 420,
  "horario_fin": 1080,
  "bloques_sueno": [
    { "dia": 1, "inicio": 0, "fin": 420 }
  ],
  "historial_energia": [
    {
      "timestamp": "2026-05-25T08:00:00Z",
      "nivel": 3,
      "dia_semana": 1,
      "contexto": "dormí bien"
    },
    {
      "timestamp": "2026-05-26T08:00:00Z",
      "nivel": 1,
      "dia_semana": 2,
      "contexto": "trasnoché"
    },
    {
      "timestamp": "2026-05-27T10:00:00Z",
      "nivel": 2,
      "dia_semana": 3
    }
  ]
}
```

---

## How the Backend Uses This

The scheduler analyses the history to classify the user's energy pattern:

| Pattern | Condition | Scheduler Behavior |
|---|---|---|
| **Transient low** | < 20% of last 14 days are low (< 2) | Current RB-01: put hard tasks early to get them done |
| **Trending low** | 20–60% of last 14 days are low (< 2) | Max 1 difficult task per day, interleave with easy tasks, enforce breaks |
| **Chronic low** | > 60% of last 14 days are low (< 2) | Avoid difficult tasks when possible, prefer short tasks, maximize rest blocks |

If history is absent or empty, it falls back to the current behavior (single `nivel_energia` value).

---

## Recommendations

### Minimum History
Send **at least 14 days** of history for the scheduler to detect patterns reliably.

### Storage Limit
Keep **up to 90 days** on the device, prune older entries.

### Privacy
Since data never leaves the device, no GDPR/consent considerations apply for storage. Only what the user explicitly sends in a request reaches the backend.

### Future-Proofing
If you later decide to sync history to the cloud (multi-device, analytics), the structure stays the same — just add a backend endpoint to receive it.
