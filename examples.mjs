export function solveExample(kind, { cutting = 8, minimumB = 0, change = false } = {}) {
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
