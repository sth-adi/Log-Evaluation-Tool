import type { Source } from "./store";

export type Preset = {
  title: string;
  name: string;
  unit: string;
  expr: string;
  /** Channels the formula reads; the template is offered only when the log has them all. */
  needs: string[];
};

export const PRESETS: Preset[] = [
  { title: "Angular speed", name: "engine_rad_s", unit: "rad/s", expr: "rpm * 2 * pi / 60", needs: ["rpm"] },
  { title: "RPM rise rate", name: "rpm_rate", unit: "rpm/s", expr: "smooth(deriv(rpm), 0.2)", needs: ["rpm"] },
  { title: "Throttle rate", name: "tps_rate", unit: "%/s", expr: "smooth(deriv(tps1), 0.2)", needs: ["tps1"] },
  { title: "Acceleration", name: "accel_ms2", unit: "m/s²", expr: "smooth(deriv(vehicleSpeed), 0.5) / 3.6", needs: ["vehicleSpeed"] },
  { title: "Acceleration in g", name: "accel_g", unit: "g", expr: "smooth(deriv(vehicleSpeed), 0.5) / 3.6 / 9.81", needs: ["vehicleSpeed"] },
  { title: "Distance travelled", name: "distance_m", unit: "m", expr: "integ(vehicleSpeed / 3.6)", needs: ["vehicleSpeed"] },
  { title: "Air-fuel ratio (petrol)", name: "afr", unit: "", expr: "lam1 * 14.7", needs: ["lam1"] },
  { title: "Coolant temperature rise", name: "ect_rise", unit: "°C/min", expr: "smooth(deriv(ect1), 5) * 60", needs: ["ect1"] },
];

export const presetsFor = (src: Source): Preset[] => {
  const have = new Set(src.channels.map((c) => c.name));
  return PRESETS.filter((p) => p.needs.every((n) => have.has(n)));
};
