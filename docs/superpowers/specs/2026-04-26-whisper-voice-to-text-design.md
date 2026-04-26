# Whisper Voice-to-Text Page Design

**Date:** 2026-04-26
**Status:** Approved
**Scope:** Backend (MyAgent) + Frontend (MyWeb)

## Overview

A voice-to-text page in MyWeb that provides dictation, file upload, and live captioning using the existing Whisper backend in MyAgent. Built in three phases, with Phase 1 (dictation + history + settings) as the initial deliverable.

## Backend Changes (MyAgent)

### Extend Transcribe Endpoint

`POST /api/whisper/transcribe`

- Add optional query params: `model` (str), `beam_size` (int), `language` (str)
- Falls back to env var defaults (`WHISPER_MODEL`, `WHISPER_BEAM_SIZE`) when not provided
- Add `jwt_required` auth — transcriptions are tied to a user
- Auto-save transcription result to history table after successful transcription

### WhisperService Changes

- `transcribe()` accepts optional `model`, `beam_size`, `language` params
- When `model` differs from current loaded model, loads new model (cached via `lru_cache(maxsize=4)`)

### New Transcriptions Table

```sql
CREATE TABLE IF NOT EXISTS transcriptions (
    id TEXT PRIMARY KEY,          -- uuid
    user_id TEXT NOT NULL,
    text TEXT NOT NULL,
    language TEXT,
    duration_seconds REAL,
    model TEXT,
    segments TEXT,                -- JSON array of {start, end, text}
    filename TEXT,                -- nullable, set for file uploads
    created_at TEXT NOT NULL      -- ISO8601
);
CREATE INDEX idx_transcriptions_user ON transcriptions(user_id, created_at DESC);
```

### New History Endpoints

- `GET /api/whisper/history` — list user's transcriptions, paginated (newest first). Query params: `page` (int, default 1), `per_page` (int, default 20).
- `GET /api/whisper/history/{id}` — single transcription with full segments (owner only)
- `DELETE /api/whisper/history/{id}` — delete transcription (owner only)

All history endpoints require `jwt_required`.

### New Files

- `src/services/whisper/history.py` — TranscriptionHistoryService with CRUD operations
- `src/services/whisper/models.py` — Pydantic models for history request/response (if not already present)
- Updates to `src/services/whisper/service.py` — add param forwarding
- Updates to `src/gateway/routes/whisper.py` — add auth, query params, history routes

## Frontend (MyWeb)

### New Page

`src/tools/whisper/WhisperPage.tsx` at route `/whisper`

### Layout

Split view:
- **Left panel (main):** Recorder + transcription result
- **Right panel (sidebar):** Scrollable history list

### Left Panel — Recorder Area

- Large record button (microphone icon, toggles recording on/off)
- Recording indicator: pulsing dot + duration timer when active
- Collapsible settings panel:
  - Model selector dropdown: tiny, base, small, medium, large
  - Beam size number input (default 5)
  - Language dropdown: "Auto-detect" + common languages (en, es, fr, de, zh, ja, ko, pt, ru, ar, hi)
- After transcription: editable text area with result, copy-to-clipboard button
- File upload (Phase 2): drag-and-drop zone, accepts wav/mp3/ogg/webm/m4a
- Status states: idle, recording, transcribing (spinner), result, error

### Right Panel — History Sidebar

- List of past transcriptions: truncated text preview (~80 chars), language badge, relative timestamp, duration
- Click entry to load full transcript into the main text area
- Delete button per entry (inline confirmation)
- "Load more" pagination at bottom

### Audio Recording

- `MediaRecorder` API with `audio/webm` codec (best cross-browser support)
- Accumulate chunks via `ondataavailable`, assemble into single Blob on stop
- Send raw bytes to `POST /api/whisper/transcribe` with settings as query params

### API Module

New `src/api/whisper.ts`:
- `transcribe(audioBlob: Blob, options?: { model?, beam_size?, language?, filename? }): Promise<TranscriptionResult>`
- `getHistory(page?: number): Promise<TranscriptionListResult>`
- `getTranscription(id: string): Promise<TranscriptionResult>`
- `deleteTranscription(id: string): Promise<void>`

Uses existing `apiFetch` wrapper from `src/api/client.ts`.

### State Management

`useReducer` for page state (consistent with MailPage pattern):
- `recordingStatus`: idle | recording | transcribing
- `currentTranscript`: TranscriptionResult | null
- `history`: TranscriptionResult[]
- `historyPage`: number
- `hasMoreHistory`: boolean
- `settings`: { model, beam_size, language }
- `error`: string | null

### Registry

Add whisper tool to `src/tools/registry.ts` for sidebar navigation.

## Phase Breakdown

### Phase 1 — Dictation + History + Settings (This Spec)

Everything described above except file upload and live captioning.

### Phase 2 — File Upload

- Add drag-and-drop zone to recorder area
- Accept common audio formats (wav, mp3, ogg, webm, m4a)
- Send file bytes to same transcribe endpoint with `filename` query param
- Same result display and history saving

### Phase 3 — Live Captioning

- Chunk `MediaRecorder` output at ~3s intervals
- Send each chunk to transcribe endpoint
- Append text results incrementally to the text area
- May require backend adjustments for handling short audio clips
- Possible future WebSocket upgrade for lower latency

## Testing

### Backend

- Unit tests for TranscriptionHistoryService CRUD operations
- Unit test for transcribe with custom model/beam_size/language params
- Auth tests: reject unauthenticated requests to transcribe and history endpoints
- Error handling: invalid model name, missing audio data

### Frontend

- Component tests for WhisperPage:
  - Record button state transitions (idle -> recording -> transcribing -> result)
  - History list rendering and click-to-load
  - Settings panel toggle and value changes
  - Error state display
- Mock `MediaRecorder` and `apiFetch` in tests
- E2E test (Playwright) for full dictation flow

## Success Criteria

- User can record audio via browser microphone, transcribe it, and see text result
- User can select model, beam size, and language before transcribing
- Transcriptions are persisted in the database and appear in the history sidebar
- User can click a history entry to view its full transcript
- User can delete history entries
- All endpoints require JWT authentication
- Unit tests pass for both backend and frontend
