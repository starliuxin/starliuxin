import DOMPurify from "dompurify";

const CSP =
  "default-src 'none'; script-src 'none'; connect-src 'none'; img-src data:; media-src 'none'; " +
  "font-src data:; style-src 'unsafe-inline'; form-action 'none'; base-uri 'none'; navigate-to 'none'";

export function buildPrototypeDocument(source: string): string {
  const sanitized = DOMPurify.sanitize(source, {
    ALLOWED_TAGS: [
      "article",
      "b",
      "blockquote",
      "br",
      "button",
      "caption",
      "code",
      "dd",
      "div",
      "dl",
      "dt",
      "em",
      "figcaption",
      "figure",
      "footer",
      "h1",
      "h2",
      "h3",
      "h4",
      "header",
      "hr",
      "i",
      "li",
      "main",
      "ol",
      "p",
      "section",
      "small",
      "span",
      "strong",
      "style",
      "table",
      "tbody",
      "td",
      "th",
      "thead",
      "tr",
      "ul",
    ],
    ALLOWED_ATTR: ["class", "colspan", "id", "rowspan", "style", "title"],
    FORBID_CONTENTS: ["script", "iframe", "object"],
    RETURN_TRUSTED_TYPE: false,
  });
  return `<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta http-equiv="Content-Security-Policy" content="${CSP}"><meta name="referrer" content="no-referrer"><meta name="viewport" content="width=device-width, initial-scale=1"></head><body>${sanitized}</body></html>`;
}
