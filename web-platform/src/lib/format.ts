// Safe text rendering: escape HTML first, then auto-link raw http(s) URLs.
// Used by inbox + past broadcasts (via dangerouslySetInnerHTML) and by email HTML.
export function escapeHtml(s: string): string {
  return s
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

export function linkifyHtml(text: string): string {
  const escaped = escapeHtml(text);
  const linked = escaped.replace(/(https?:\/\/[^\s<]+)/g, (url) => {
    // Trim trailing punctuation that is rarely part of a URL
    const m = url.match(/^(.*?)([.,;:!?)\]]+)$/);
    const clean = m ? m[1] : url;
    const trail = m ? m[2] : "";
    return `<a href="${clean}" target="_blank" rel="noopener noreferrer nofollow" class="text-cyan-300 hover:text-cyan-200 underline underline-offset-2 break-all">${clean}</a>${trail}`;
  });
  return linked.replace(/\n/g, "<br/>");
}
