# iPhone Shortcut → Whisper / Voice Agent

How to set up iOS Shortcuts that talk to MyAgent over voice. Three endpoints to
choose between:

| Endpoint | What it does | Best for |
|---|---|---|
| `POST /api/whisper/transcribe` | Audio → JSON `{text, segments, ...}` | Pure speech-to-text dictation |
| `POST /api/whisper/agent` | Audio → transcribe → LLM tool → execute → JSON `{reply, tool, result, ...}` | Quick commands when you're willing to wait ~5-15s |
| `POST /api/whisper/agent/async` | Same as `/agent` but returns `202 + job_id` instantly; reply pushed via ntfy.sh | The right default — phone doesn't block, push notification when done |

Transcripts captured from the phone show up in the Whisper page in MyWeb
alongside browser-captured ones (source badge `shortcut`).

## Prereqs

1. A device token. Two ways to get one:
   - **From the web UI** — MyWeb → Settings → **Whisper device token** → click
     **Generate**. Copy the plaintext `whsk_…` token (you only see it once).
   - **From iPhone only** — build the "Whisper Setup" Shortcut below; it
     logs in and mints the token in one tap.
2. Your MyAgent server URL reachable from the phone. If MyAgent is on your
   local LAN, the phone needs to be on the same network (or use Tailscale /
   another VPN).

## Phone-only setup (no web UI)

If you don't want to touch MyWeb, build this Shortcut once. It logs in,
generates a device token, and saves it to a file the recording Shortcut reads.

### "Whisper Setup" Shortcut (run once)

1. **Ask for Input** → Prompt: `Server URL` (e.g. `https://mybox:8000`),
   save as variable `ServerURL`
2. **Ask for Input** → Prompt: `Email`, save as `Email`
3. **Ask for Input** → Prompt: `Password`, Input Type: **Secure**, save as
   `Password`
4. **Text** → contents: `{"email":"[Email]","password":"[Password]"}`
   (brackets = inserted variables)
5. **Get Contents of URL**
   - URL: `[ServerURL]/api/account/login`
   - Method: `POST`
   - Headers: `Content-Type: application/json`
   - Request Body: `File` → the Text from step 4
6. **Get Dictionary Value** → Get: `Value`, Key: `token`, from Contents of
   URL → this is the JWT
7. **Get Contents of URL**
   - URL: `[ServerURL]/api/auth/device-token`
   - Method: `POST`
   - Headers: `Authorization: Bearer [JWT from step 6]`
8. **Get Dictionary Value** → Get: `Value`, Key: `token`, from step 7's
   Contents of URL → this is the `whsk_…` device token
9. **Save File** → destination: `iCloud Drive/Shortcuts/whisper_token.txt`,
   contents: the device token from step 8, **Overwrite if Exists: On**
10. **Save File** → destination: `iCloud Drive/Shortcuts/whisper_server.txt`,
    contents: `[ServerURL]`, **Overwrite if Exists: On**
11. **Show Result** → `Setup complete. Token saved.`

The password is never persisted — only the device token is. Run this again
any time you want to rotate (overwriting the file invalidates the old
token server-side on rotate).

Now the recording Shortcut below reads both files instead of you typing
the URL and token each time.

## Build the Shortcut

Open the **Shortcuts** app on iPhone → tap **+** to create a new Shortcut.

### Action 1 — Record Audio

- Tap **+ Add Action** → search **Record Audio** → add it.
- Tap the action → set **Audio Quality: Normal** and **Stop: On Tap**.
  (Whisper handles low-bitrate audio fine; "Normal" keeps file size down.)

### Action 2 — Get Contents of URL

- Add **Get Contents of URL**.
- **URL**: `https://YOUR_SERVER/api/whisper/transcribe?filename=shortcut.m4a`
  (replace `YOUR_SERVER` with the host:port of MyAgent)
- Tap the expand arrow on the action and set:
  - **Method**: `POST`
  - **Headers**:
    - `X-Device-Token` → paste the `whsk_…` token you generated
    - `Content-Type` → `audio/m4a`
  - **Request Body**: `File` → select the **Recorded Audio** from Action 1
    (tap the field, choose Variables → Recorded Audio)

### Action 3 — Get Dictionary Value

- Add **Get Dictionary Value**.
- **Get**: `Value for`
- **Key**: `text`
- **Dictionary**: the **Contents of URL** from Action 2

### Action 4 — Output (pick one or chain several)

The transcript is now in the variable `Dictionary Value`. Hand it to whatever
you want:

- **Show Result** — pops up the text on screen
- **Speak Text** — reads it back aloud
- **Send Message** — text it to a contact
- **Append to Note** — keep a running journal
- **Run Shortcut** — chain into another shortcut that does something with it

## Quick test

1. Tap the Shortcut from the Shortcuts app (or pin it to your Home Screen).
2. Speak for a few seconds; tap **Stop** in the Record Audio panel.
3. Wait a moment — depending on your server, transcription takes ~1-3× the
   audio duration.
4. The output action fires with the transcript.
5. Open MyWeb → **Whisper** page → you should see the transcript at the top of
   the History list with a `shortcut` badge.

## Async voice agent (recommended)

Phone fires audio, gets a `job_id` instantly, server processes in background and
pushes the spoken reply to your phone via [ntfy.sh](https://ntfy.sh). No waiting.

### Server setup (one time)

1. Pick an ntfy topic name — something hard to guess, like `myagent-alex-7f3k4q`.
   The topic acts as a shared secret; anyone with the topic name can read your
   notifications.
2. Add to `MyAgent/.env`:
   ```
   NTFY_TOPIC=myagent-alex-7f3k4q
   ```
3. Restart MyAgent.

### iPhone setup (one time)

1. Install the **ntfy** app from the App Store.
2. In the app, tap **+** → "Subscribe to topic" → enter the same topic name.
   Notifications will start arriving on this phone.

### Voice agent Shortcut (async variant)

1. **Record Audio** — Stop: On Tap.
2. **Get Contents of URL**
   - URL: `http://YOUR_SERVER/api/whisper/agent/async?filename=clip.m4a`
   - Method: `POST`
   - Headers: `X-Device-Token: whsk_…`, `Content-Type: audio/m4a`
   - Request Body: File → Recorded Audio
3. (Optional) **Show Result** → "Sent" — purely so the Shortcut visibly completes.

That's it. A second later, your phone gets a push notification with the agent's
reply. The Shortcut itself returns in well under a second.

### What the voice agent can do

The agent picks **one** tool per command. Available tools:

| Tool | Trigger phrases | What it does |
|---|---|---|
| `save_note` | "remember to…", "save this", "note that…" | Stores in MemoryService with embedding |
| `recall_notes` | "what did I say about…", "do I have notes on…" | Semantic search of saved notes |
| `create_event` | "add lunch with Bob Friday at noon" | New calendar event |
| `list_events` | "what's on my calendar tomorrow" | Queries calendar in a date range |
| `search_web` | "weather in Austin", "who won the game" | Web search via configured provider |
| `answer` | greetings, opinions, general Q&A | Pure LLM answer, no data access |

Replies are kept short (1-2 sentences) so they fit nicely in an ntfy push.

## Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 Missing or invalid credentials` | Wrong / revoked token, or header name typo | Re-check `X-Device-Token` header. Rotate token in Settings if unsure. |
| `413` | Recording exceeded 25 MB | Keep clips short; bump server cap in `whisper/routes.py:MAX_AUDIO_BYTES` if you really need longer. |
| `Could not reach server` | Phone can't see MyAgent | Confirm same LAN / VPN. Test the URL in Safari first. |
| Transcript is empty | Audio captured but silent or model couldn't decode | Speak louder, try again. Check server logs for faster-whisper output. |
| Long pause then timeout | Cold model load on server | First request after server boot is slow while the Whisper model loads. Subsequent ones are fast. |

## Notes

- The **Whisper page in MyWeb is a test surface and will be removed** once the
  voice → LLM agent path is wired up. The endpoint (`/api/whisper/transcribe`)
  and the device token stay; your Shortcut will continue to work and your
  transcripts remain in the DB.
- One device token per user. Rotating invalidates the old one immediately.
