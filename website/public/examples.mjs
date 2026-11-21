// Exact finite examples + verified multi-objective GPU scheduling Pareto front for the interactive landing showcase.
export const PARETO_FRONT = [
  { id: 1, tag: "cost", cost: 272.5, risk: 18.49, loads: [80, 89, 75, 14], caps: [80, 90, 75, 85] },
  { id: 2, tag: null, cost: 274.7, risk: 18.00, loads: [79, 90, 70, 19], caps: [80, 90, 75, 85] },
  { id: 3, tag: null, cost: 277.6, risk: 17.34, loads: [80, 88, 63, 27], caps: [80, 90, 75, 85] },
  { id: 4, tag: null, cost: 280.9, risk: 16.58, loads: [78, 90, 54, 36], caps: [80, 90, 75, 85] },
  { id: 5, tag: null, cost: 283.5, risk: 15.98, loads: [80, 89, 47, 42], caps: [80, 90, 75, 85] },
  { id: 6, tag: "knee", cost: 286.4, risk: 15.36, loads: [80, 90, 40, 48], caps: [80, 90, 75, 85] },
  { id: 7, tag: null, cost: 290.2, risk: 14.52, loads: [77, 90, 31, 60], caps: [80, 90, 75, 85] },
  { id: 8, tag: null, cost: 294.8, risk: 13.51, loads: [72, 90, 22, 74], caps: [80, 90, 75, 85] },
  { id: 9, tag: "risk", cost: 299.6, risk: 12.48, loads: [69, 89, 15, 85], caps: [80, 90, 75, 85] },
];

export function solveExample(kind, { cutting = 8, minimumB = 0, change = false, paretoIndex = 5 } = {}) {
  if (kind === "pareto") {
    const idx = Math.max(0, Math.min(PARETO_FRONT.length - 1, Math.round(paretoIndex)));
    return { index: idx, totalSolutions: 200, point: PARETO_FRONT[idx], front: PARETO_FRONT };
  }
  if (kind === "production") {
    if (!Number.isInteger(cutting) || cutting < 8 || cutting > 12 || ![0, 3, 5].includes(minimumB)) throw new RangeError("Invalid example conditions");
    let best = null;
    for (let a = 0; a <= Math.floor(cutting / 2); a++) {
      for (let b = minimumB; b <= 4; b++) {
        const total = 3 * a + 2 * b;
        if (2 * a + b <= cutting && a + 2 * b <= 8 && (!best || total > best.total)) best = { total, quantities: [a, b] };
      }
    }
    return best;
  }
  if (kind === "shifts") {
    const costs = [[1, 7], [2, 8], [7, 1], [8, 2]];
    let best = null;
    for (let mask = 0; mask < 16; mask++) {
      const days = costs.map((_, index) => (mask >> index) & 1);
      if (days.reduce((sum, day) => sum + day, 0) !== 2 || (change && days[0] !== 1)) continue;
      const total = costs.reduce((sum, cost, index) => sum + cost[days[index]], 0);
      if (!best || total < best.total) best = { total, days };
    }
    return best;
  }
  if (kind === "delivery") {
    const costs = [[4, 8, 6], [7, 3, 9], [5, 6, 2]];
    let best = null;
    for (const destinations of [[0, 1, 2], [0, 2, 1], [1, 0, 2], [1, 2, 0], [2, 0, 1], [2, 1, 0]]) {
      if (change && destinations[1] === 1) continue;
      const total = destinations.reduce((sum, target, source) => sum + costs[source][target], 0);
      if (!best || total < best.total) best = { total, destinations };
    }
    return best;
  }
  throw new RangeError("Unknown example");
}
