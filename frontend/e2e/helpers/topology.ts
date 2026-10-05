/** Serialized with page.evaluate: every geometry operation runs in the browser. */
export function topologyDistances() {
  const core = document
    .querySelector(".topology-core")!
    .getBoundingClientRect();
  const nodes = [...document.querySelectorAll(".topology-node")].map((node) =>
    node.getBoundingClientRect(),
  );
  const svg = document.querySelector<SVGSVGElement>(".topology-links")!;
  const segments = [
    ...svg.querySelectorAll<SVGGraphicsElement>(
      "path:not(.signal), line:not(.signal)",
    ),
  ].flatMap((shape) => {
    const matrix = shape.getScreenCTM()!;
    const transform = (x: number, y: number) =>
      new DOMPoint(x, y).matrixTransform(matrix);
    if (shape instanceof SVGLineElement)
      return [
        {
          start: transform(shape.x1.baseVal.value, shape.y1.baseVal.value),
          end: transform(shape.x2.baseVal.value, shape.y2.baseVal.value),
        },
      ];
    // Retain straight legacy paths so the regression still rejects the old geometry.
    return [
      ...shape
        .getAttribute("d")!
        .matchAll(/M([\d.]+)\s+([\d.]+)L([\d.]+)\s+([\d.]+)/g),
    ].map((match) => ({
      start: transform(Number(match[1]), Number(match[2])),
      end: transform(Number(match[3]), Number(match[4])),
    }));
  });
  return segments.map((segment, index) => ({
    core: Math.hypot(
      segment.start.x - (core.left + core.width / 2),
      segment.start.y - (core.top + core.height / 2),
    ),
    node: Math.hypot(
      segment.end.x - (nodes[index].left + nodes[index].width / 2),
      segment.end.y - (nodes[index].top + nodes[index].height / 2),
    ),
  }));
}
