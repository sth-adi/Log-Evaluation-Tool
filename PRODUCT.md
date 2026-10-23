# Product

**What it is.** A local, offline log evaluation tool for the UWE Formula Student hybrid car. It reads CSV logs from the engine control unit (ECU, Life Racing F88R) and the hybrid control unit (HCU), aligns them in time and helps engineers work out what the car did.

**Who uses it.** UWE FS powertrain and data engineers, on Windows laptops, in the workshop and at events. No internet is assumed.

**What it must never do.** Talk to the car. The tool only reads log files; it has no path to the ECU or HCU.

## Principles

1. Offline first. No CDNs, no accounts, no network calls at run time.
2. Honest about its assumptions. Every guess the importer makes (time unit, units, delimiter) is shown, and can be overridden with a mapping profile.
3. Fast on big logs. The browser only ever receives about one point per pixel.
4. Dense but calm. Built for long sessions staring at many signals.

## Status

Early scaffold. Channel names and file layouts in `samples/synthetic` are invented. They are not the real F88R or HCU formats. Replace them with real logs as soon as they exist.

## Roadmap

1. Viewer: import, overlaid lanes, synced zoom and cursor (started)
2. Multi-file ECU and HCU time alignment
3. Derived channels (power, energy, slip)
4. Hybrid views: energy, torque split, HCU mode timeline
5. Lap and distance analysis
6. Live telemetry
