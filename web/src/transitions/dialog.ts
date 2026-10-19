import { fade } from "svelte/transition";

// Match dialog.css: ease-out (0, 0, .58, 1) and ease-in (.42, 0, 1, 1).
function dialogEasing(progress: number, entering: boolean): number {
  if (progress === 0 || progress === 1) return progress;
  const x1 = entering ? 0 : 0.42;
  const x2 = entering ? 0.58 : 1;
  let low = 0;
  let high = 1;
  for (let step = 0; step < 20; step++) {
    const t = (low + high) / 2;
    const x = 3 * (1 - t) ** 2 * t * x1 + 3 * (1 - t) * t ** 2 * x2 + t ** 3;
    if (x < progress) low = t;
    else high = t;
  }
  const t = (low + high) / 2;
  return 3 * (1 - t) * t ** 2 + t ** 3;
}

export function fadeTransition(
  node: Element,
  _params: undefined,
  { direction }: { direction: "in" | "out" | "both" },
) {
  const entering = direction === "in";
  return fade(node, {
    duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? 0 : entering ? 180 : 130,
    easing: (progress) => dialogEasing(progress, entering),
  });
}
