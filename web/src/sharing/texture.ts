export function fitFamilyTexture(node: HTMLSpanElement, texture: string) {
  const context = document.createElement("canvas").getContext("2d")!;
  let active = true;

  function updateTexture() {
    if (!active) return;
    const style = getComputedStyle(node);
    context.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
    const width = node.getBoundingClientRect().width;
    let low = 0;
    let high = texture.length;
    while (low < high) {
      const count = Math.ceil((low + high) / 2);
      if (context.measureText(texture.slice(0, count)).width <= width) {
        low = count;
      } else {
        high = count - 1;
      }
    }
    node.textContent = texture.slice(0, low);
  }

  const observer = new ResizeObserver(updateTexture);
  observer.observe(node);
  document.fonts.addEventListener("loadingdone", updateTexture);
  void document.fonts.ready.then(updateTexture);
  updateTexture();

  return {
    update(value: string) {
      texture = value;
      updateTexture();
    },
    destroy() {
      active = false;
      observer.disconnect();
      document.fonts.removeEventListener("loadingdone", updateTexture);
    },
  };
}
