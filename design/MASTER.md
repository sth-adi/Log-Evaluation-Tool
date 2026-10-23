# Design system: Log Evaluation Tool (UWE Formula Student)

Source of truth for look and feel. Tokens live in `frontend/src/styles/tokens.css`; change them there.

## Who and what

- **Users:** UWE FS engineers reading ECU and hybrid-control-unit (HCU) logs in the workshop or at the track, on a Windows laptop, often in poor light.
- **Primary job:** find out what the car did, and why, in as few clicks as possible.
- **Context:** dense, long sessions, many overlaid signals. Readability beats decoration.

## Direction

A timing screen, not a SaaS dashboard. The plot canvas is true black so traces carry maximum contrast. The chrome around it is flat graphite: no cards, no shadows, no gradients, no blur. Structure comes from thin rules and alignment.

The one memorable element is the **live readout column**. Each plot lane has a column on its right edge showing the value of every signal at the cursor, in large white tabular numerals, like a timing board. The cursor line itself is the only large use of brand red. Everything else stays quiet.

## Tokens

| Role | Name | Value |
|---|---|---|
| Plot canvas | Black | `#000000` |
| Chrome surface | Graphite | `#171717` |
| Raised surface, hover | Steel | `#242424` |
| Rules and borders | Rule | `#333333` |
| Primary text | Chalk | `#f2f2f2` |
| Secondary text | Ash | `#9a9a9a` |
| Brand red (placeholder, swap for the official UWE FS red) | Livery red | `#e11d2a` |

Data colours carry meaning and are never used for chrome:

| Meaning | Value |
|---|---|
| Combustion engine | `#ffb020` amber |
| Electric motor and inverter | `#38c8f0` cyan |
| Regeneration | `#3ddc84` green |
| Battery pack | `#b79bff` violet |

Eight-colour trace cycle (colour-blind-safe order, no red): `#ffb020 #38c8f0 #3ddc84 #b79bff #ff8fb1 #e8e8e8 #7fa6ff #d6e34a`.

**Red rules.** Brand red is used for the cursor, the selected state and the primary action. Red is never a data trace. A fault is shown as a filled marker with an icon and the word "Fault", never colour alone.

## Type

One family, two widths, chosen for motorsport timing-screen heritage: **Barlow Semi Condensed** for UI text and numerals, **Barlow Condensed** (semibold) for panel and lane titles. Numbers always use tabular figures (`font-variant-numeric: tabular-nums`) so columns of values do not jitter.

Scale (px): 11 / 12 / 13 (base) / 15 / 18 / 28 (readout). Sentence case everywhere. No all-caps labels, no eyebrow text.

## Layout

```
+------------------------------------------------------------------+
| Log Evaluation Tool        [Import logs]          offset  zoom   |
+---------+--------------------------------------------+-----------+
| Sources |  Engine speed                       rpm    |  9 840    |
|  ECU    |  ~~~~~~/\~~~~/\~~~~                        |           |
|   RPM   +--------------------------------------------+-----------+
|   TPS   |  Motor torque                       Nm     |   18.4    |
|  HCU    |  ____/-----\____                           |           |
|   SOC   +--------------------------------------------+-----------+
|         |  shared time axis                          |  t 83.42  |
+---------+--------------------------------------------+-----------+
```

- Left: source and channel tree. Middle: stacked plot lanes on one shared time axis. Right: readout column aligned to each lane.
- Text and numbers are left-aligned, except numeric readouts, which are right-aligned.
- Later: an HCU state timeline strip under the lanes.

## Motion

Only motion that answers an action: the cursor tracks the pointer, zoom animates over about 120 ms, panels open in about 120 ms. Nothing animates on load. `prefers-reduced-motion` turns all of it off. No bounce or elastic easing.

## Quality floor

Visible keyboard focus on every control, 4.5:1 text contrast, status never conveyed by colour alone, text that reflows without clipping, usable down to a 1280 px laptop width.

## Words

Plain verbs, sentence case, the same name for an action throughout (Import logs, Imported). Errors say what went wrong and what to do next, with no apology.
