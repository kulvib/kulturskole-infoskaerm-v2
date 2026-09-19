export function isPageVisible() {
  if (typeof document === "undefined") return true;
  return document.visibilityState !== "hidden";
}
