# Design system: Log Evaluation Tool (UWE Formula Student)

Source of truth for look and feel. Tokens live in `frontend/src/styles/tokens.css`; change them there.

## Who and what

- **Users:** UWE FS engineers reading engine and dyno logs in the workshop or at the track, on a Windows laptop, often in poor light.
- **Primary job:** find out what the car did, and why, in as few clicks as possible.
- **Context:** several logs per session, many signals. The tool must feel calm and obvious, and show only what is needed right now.

## Direction

A modern instrument, not an admin panel. Near-black surfaces, soft one-pixel lines, rounded controls, generous spacing, and **UWE FS red as the single accent**. Red marks what is selected or primary (the active view tab, the primary button, the selected log, focus, progress, the cursor line). Everything else is neutral, and the trace colours belong to the data. Nothing decorative: no gradients, no glow, no glass, no repeated card boxes.

The memorable element is **Plot a channel** (press `/` or Ctrl+K): a search palette with recent and suggested channels, group filters and keyboard control. It replaces the old always-open channel lists, so the screen starts nearly empty and fills only with what the engineer asked for.

## Principles

1. **Show less.** Logs live in a slim left rail as a small timeline. Everything about one log that is not needed all the time (offset, calculated channels, import notes, close) is behind that log's Manage drawer. Closing a log only takes it off the screen.
   The **Library** holds every processed log. Importing something already there opens the existing log instead of copying it, and an `.LRD` that was converted before is never run through LifeView again.
2. **Values sit with the data.** Each plot has a header with the channel name, unit and the value at the cursor in large numerals. There is no separate readout column, so plots get the full width.
3. **One timeline.** A channel is plotted across every log that has it, in session-start order, with dashed boundaries and start times. Calculated channels and event rules apply to all logs at once.
4. **Honest and offline.** No network at run time. The importer's guesses stay visible in the Manage drawer.

## Tokens

| Role | Name | Value |
|---|---|---|
| Plot canvas | Ink | `#0a0b0d` |
| Chrome | Panel | `#111317` |
| Controls, popovers | Raised | `#181b21` |
| Hover | Hover | `#1f232a` |
| Hairlines | Line | `#23272e` (strong `#343944`) |
| Primary text | Text | `#eceef2` |
| Secondary text | Muted | `#8b919c` |
| Quiet text | Faint | `#5d636e` |
| Accent: selection, primary action, focus, cursor | UWE FS red | `#e11d2a` (bright `#ff3b47`, soft fill 16%) |

Data colours carry meaning and are never used for chrome: `#ffb020` amber, `#38c8f0` cyan, `#3ddc84` green, `#b79bff` violet, then `#ff8fb1 #e8e8e8 #7fa6ff #d6e34a`. Red is never a data trace.

Red is the only accent and is never a data trace. Primary buttons and the active view tab are solid red with white text; chips and tags use the soft red fill with a red outline; the selected log has a red bar. The red is a placeholder until the official livery value is known; change `--red` in `tokens.css`.

## Type

One family: **Geist Variable**, bundled with the app so it works offline. Numbers use tabular figures so values do not jitter. Sizes (px): 12 / 13 / 14 (base) / 16 / 22 (single-plot value) / 26 (empty-state title). Sentence case everywhere, no all-caps labels.

## Shape and space

Radii: 6 px controls, 10 px list items and toasts, 14 px popovers. Panels are separated by hairlines, not shadows; only floating layers (palette, drawer, toast) have a shadow. Spacing steps of 4/8/12/16/20.

## Layout

```
+-------------------------------------------------------------------+
| Log Evaluation Tool  [Plots|Analysis]  [ Plot a channel  / ]  Report Import |
+-----------+-------------------------------------------------------+
| Logs      |  rpm  rpm, 4 logs        2,382                    x   |
| 11:42:03  |  ~~~~~~~~/\~~~~~/\~~~~                                |
| 11:43:39  +-------------------------------------------------------+
| 11:49:58  |  act1 degC, 4 logs       25.20                    x   |
| 11:53:32  |  ____/-----\____                                      |
|           +-------------------------------------------------------+
| Show all  |  shared time axis, dashed lines where each log starts |
+-----------+-------------------------------------------------------+
```

- Left: logs only. Click a log to zoom to it; the three dots open Manage.
- Middle: plots stacked on one shared time axis, each with its own header.
- Analysis (statistics, histogram, spectrum, scatter, events) is a second view, not extra panels on the plots.

## Motion

Only motion that answers an action, about 140 ms. Nothing animates on load. `prefers-reduced-motion` turns it all off.

## Quality floor

Visible keyboard focus on every control, 4.5:1 text contrast, status never by colour alone (events carry a marker and the rule name), full keyboard use of the channel search, usable down to a 1280 px laptop width.

## Words

Plain verbs, sentence case, the same name for an action throughout (Import logs, Plot a channel, Manage). Errors say what went wrong and what to do next, with no apology.
