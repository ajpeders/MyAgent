# MyDevTeam Architecture

## Component Overview

```mermaid
graph TD
    subgraph Entry["Entry Points"]
        CLI["CLI<br/>cli.py"]
        HTTP["HTTP Server<br/>server.py"]
    end

    subgraph State["State Layer"]
        SESSIONS["sessions.db<br/>SQLite"]
    end

    subgraph Routing["Routing"]
        HEAD["HeadAgent<br/>head.py"]
    end

    subgraph Agents["Subagents (plan-based)"]
        MAIL["MailAgent<br/>(mail tools)"]
        CMD["CommandAgent<br/>(command tools)"]
        ANS["AnswerAgent<br/>(answer tools)"]
    end

    subgraph Execution["Execution"]
        EXECUTOR["executor.py<br/>plan queue processor"]
        MAILENGINE["MailEngine<br/>mail_engine.py"]
    end

    subgraph LLM["LLM"]
        ADAPTER["LLMAdapter<br/>llm.py"]
        OLLAMA["Ollama<br/>(qwen3:8b)"]
    end

    subgraph External["External Systems"]
        IMAP["IMAP<br/>(multi-account)"]
        APPLEMAIL["Apple Mail<br/>(AppleScript fallback)"]
        DOCKER["Docker Sandbox"]
    end

    CLI -->|"stateless"| EXECUTOR
    HTTP -->|"stateless"| EXECUTOR
    CLI -->|"multi-turn"| SESSIONS
    HTTP -->|"multi-turn"| SESSIONS
    SESSIONS -->|"no active agent"| HEAD
    SESSIONS -->|"active agent"| MAIL
    SESSIONS -->|"active agent"| CMD
    SESSIONS -->|"active agent"| ANS
    HEAD --> MAIL
    HEAD --> CMD
    HEAD --> ANS

    MAIL --> EXECUTOR
    CMD --> EXECUTOR
    ANS --> EXECUTOR

    EXECUTOR --> ADAPTER
    EXECUTOR --> MAILENGINE
    MAILENGINE --> ADAPTER
    HEAD --> ADAPTER
    ADAPTER --> OLLAMA

    MAILENGINE --> IMAP
    MAILENGINE --> APPLEMAIL
    EXECUTOR --> DOCKER
```

## Plan-Based Execution

All subagents return a **Plan** — an ordered list of Actions. The executor processes the full queue before returning control to the user.

```
User: "delete emails 1, 2, and 3"
  → LLM returns Plan: [mail_move(#1), mail_move(#2), mail_move(#3)]
  → Executor: confirm #1 → delete → confirm #2 → delete → confirm #3 → delete
  → Prompt user for next action
```

This avoids the single-action loop where the model would re-interpret the request after each action, leading to retries and hallucinated repeats.

## Runtime Flow

```mermaid
sequenceDiagram
    participant Client as Client (CLI or HTTP)
    participant Entry as Entry Point
    participant Store as sessions.db
    participant Head as HeadAgent
    participant Agent as Subagent
    participant Exec as executor.py
    participant LLM as Ollama
    participant Ext as External

    alt stateless
        Client->>Entry: prompt
        Entry->>Exec: dispatch single action
    else multi-turn
        Client->>Entry: prompt
        Entry->>Store: load_session()
        Store-->>Entry: SessionState

        alt no active agent
            Entry->>Head: route(prompt)
            Head->>LLM: classify intent
            LLM-->>Head: AgentRoute
            Head-->>Entry: agent + intent
        end

        Entry->>Agent: append prompt, get context
        Agent->>LLM: complete(messages, scoped_schema)
        LLM-->>Agent: Plan JSON (list of actions)
        Agent->>Exec: dispatch action queue
    end

    loop for each action in Plan
        alt display action (summary, answer)
            Exec-->>Client: show content
        else external action (mail_move, command)
            Exec-->>Client: confirm?
            Client->>Exec: y/n
            Exec->>Ext: execute action
            Ext-->>Exec: result
        else needs data (mail_read)
            Exec->>Ext: fetch
            Ext-->>Exec: data
            Exec->>Agent: replan with new data
            Agent->>LLM: complete(messages, scoped_schema)
            LLM-->>Agent: extended Plan
        end
    end

    Exec-->>Client: prompt for next input
    Entry->>Store: save_session()
```

## Mail Flow

Mail uses a stateful `MailEngine` instead of an LLM-driven conversation loop. The engine owns the inbox cache, pagination, formatting, and execution. The LLM is called with fresh context only for recommendations and intent parsing.

1. User says "check my email"
2. If multiple accounts configured → ask which (Gmail / Yahoo / all)
3. `MailEngine.fetch()` reads emails with body preview and stores them in `SessionState.mail_engine`
4. `MailEngine.recommend()` tags cached emails as keep/delete/save
5. `MailEngine.display()` renders the current page deterministically
6. User interacts: read, delete, next, previous, page N
7. `MailEngine.handle()` parses intent with current-page context, resolves page-relative indices to cached UIDs, and returns structured results
8. Destructive actions return confirmation; confirmed moves update the cache and redisplay from engine state
9. User says "done" or the session is cleared → exit

Folder names are resolved per-provider: `Trash` → `[Gmail]/Trash` on Gmail, `Trash` on Yahoo.
