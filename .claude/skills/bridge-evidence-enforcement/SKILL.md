---
name: bridge-evidence-enforcement
description: Use when completing any task via bridge_task_done, claiming work is finished, or about to report task results on the Bridge platform - requires concrete verification evidence with command output before any completion claim
---

# Bridge Evidence Enforcement

## Overview

Every task completion on Bridge requires **concrete, verifiable evidence**. No exceptions.

**Core principle:** Your evidence must allow someone else to verify your claim without running anything themselves.

**Violating the letter of this rule is violating the spirit of this rule.**

## The Iron Law

```
NO bridge_task_done WITHOUT CONCRETE VERIFICATION OUTPUT IN THIS CONTEXT
```

If you haven't run the verification command in this conversation, you cannot claim done.

## The Gate (MANDATORY before bridge_task_done)

```
1. IDENTIFY: What command proves this task is complete?
   - API change → curl command showing response
   - Code change → test execution output
   - UI change → screenshot
   - Config change → validation command output

2. RUN: Execute the verification command NOW
   - Not "I ran it earlier"
   - Not "it should work"
   - In THIS context, in THIS message

3. CAPTURE: Copy the exact output
   - Full command + full output
   - Exit code / HTTP status
   - Error count = 0 confirmed

4. EMBED: Put output in result_summary
   - NOT "es funktioniert"
   - NOT "habe getestet"
   - The ACTUAL output

5. CHOOSE evidence_type correctly:
   test       → automated test output (BEST)
   log        → server/application log excerpt
   screenshot → visual proof (UI changes)
   code       → code diff showing the change
   review     → another agent reviewed and approved
   manual     → LAST RESORT ONLY (see below)

6. ONLY THEN: Call bridge_task_done
```

## evidence_type Hierarchy

| Type | Quality | When to use |
|------|---------|-------------|
| `test` | BEST | Automated test passed, curl response ok |
| `log` | GOOD | Server log confirms behavior |
| `screenshot` | GOOD | UI change visually confirmed |
| `code` | OK | Code diff is the deliverable (spec, doc) |
| `review` | OK | Another agent reviewed and confirmed |
| `manual` | WARNING | No automated check possible — MUST justify why |

**Using `manual` triggers automatic warning to your manager.** Only use when genuinely no command can verify the result (e.g., pure documentation review).

## evidence_ref Requirements

Your `evidence_ref` must contain **concrete proof** (minimum 50 characters):

```
GOOD: "curl -s http://127.0.0.1:9111/task/tracker → HTTP 200,
       returned 12 tasks with filter agent=kai, all fields present"

BAD:  "done"
BAD:  "tested and works"
BAD:  "ok"
BAD:  ""
```

## Red Flags — STOP

If you catch yourself thinking any of these, STOP and run verification:

- "Es sollte funktionieren"
- "Habe ich schon getestet" (but no output in this context)
- "Der Code sieht richtig aus"
- "Ist offensichtlich korrekt"
- "Nur eine kleine Aenderung"
- "Braucht keinen Test"
- Using evidence_type "manual" to avoid running a command

**All of these mean: Run the verification command. Capture output. THEN report.**

## Rationalization Prevention

| Excuse | Reality |
|--------|---------|
| "Ich habe es manuell geprueft" | Wo ist der Output? |
| "Der Code ist selbsterklaerend" | Code erklaert nicht ob es LAEUFT |
| "Ist nur ein Einzeiler" | Einzeiler koennen Systeme zerstoeren |
| "Test dauert zu lange" | Ungetesteter Code kostet mehr Zeit |
| "evidence_type manual reicht" | manual = Warnung an Manager |
| "Vorheriger Test gilt noch" | Nein. Frische Evidenz. Jetzt. |

## Common Verification Commands

| Task Type | Verification |
|-----------|-------------|
| API endpoint | `curl -s http://127.0.0.1:9111/endpoint` |
| Server change | Restart + `curl` health check |
| Python code | `python3 -c "import module; ..."` or pytest |
| File creation | `ls -la file && head -20 file` |
| Config change | Restart service + functional test |

## The Bottom Line

**Evidence is not optional. Evidence is not negotiable.**

Run the command. Capture the output. Embed it in your report. Choose the right evidence_type.

This is how professionals work. This is how Bridge works.
