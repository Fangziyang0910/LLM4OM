export function production({ cutting = 8, finishing = 8, minimumB = 0, integer = true } = {}) {
  const feasible = ([a, b]) => a >= -1e-9 && b >= minimumB - 1e-9 && 2 * a + b <= cutting + 1e-9 && a + 2 * b <= finishing + 1e-9;
  const points = [];
  if (integer) {
    for (let a = 0; a <= Math.floor(cutting / 2); a++) for (let b = minimumB; b <= finishing / 2; b++) if (feasible([a, b])) points.push([a, b]);
  } else {
    const lines = [[1, 0, 0], [0, 1, minimumB], [2, 1, cutting], [1, 2, finishing]];
    for (let i = 0; i < lines.length; i++) for (let j = i + 1; j < lines.length; j++) {
      const [a, b, c] = lines[i], [d, e, f] = lines[j], det = a * e - b * d;
      if (Math.abs(det) > 1e-9) {
        const point = [(c * e - b * f) / det, (a * f - c * d) / det];
        if (feasible(point)) points.push(point);
      }
    }
  }
  const best = points.reduce((current, point) => !current || 3 * point[0] + 2 * point[1] > 3 * current[0] + 2 * current[1] + 1e-9 ? point : current, null);
  return { points, best, objective: best ? 3 * best[0] + 2 * best[1] : null };
}

export function projection(limit) {
  if (limit < 0) return null;
  const x = limit >= 3 ? 1 : Math.max(0, (limit - 1) / 2);
  const y = limit >= 3 ? 2 : limit - x;
  return { x, y, objective: (x - 1) ** 2 + (y - 2) ** 2 };
}

export const nonconvex = x => (x * x - 1) ** 2 + .2 * x;
export function descent(start, iterations = 60) {
  const path = [start];
  for (let i = 0; i < iterations; i++) {
    const x = path.at(-1);
    path.push(x - .04 * (4 * x * (x * x - 1) + .2));
  }
  return path;
}
