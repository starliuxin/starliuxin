import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import App from "./App";
import { buildPrototypeDocument } from "./preview";

describe("Agent Elf welcome screen", () => {
  beforeEach(() => {
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: RequestInfo | URL) => {
        const path = String(input);
        const body =
          path === "/api/settings"
            ? {
                provider: "demo",
                model: "local-demo",
                external_data_disclosure: null,
                requires_token_budget: true,
                default_token_budget: null,
              }
            : [];
        return new Response(JSON.stringify(body), {
          status: 200,
          headers: { "Content-Type": "application/json" },
        });
      }),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requires a token budget before a run can start", () => {
    render(<App />);

    expect(screen.getByLabelText(/token 硬上限/)).toBeRequired();
    expect(screen.getByRole("button", { name: /整理目标/ })).toBeDisabled();
    expect(screen.getByText(/代码产出，不在本机运行/)).toBeInTheDocument();
  });

  it("strips active markup and navigation from an untrusted prototype", () => {
    const preview = buildPrototypeDocument(
      '<script>fetch("https://example.test")</script><meta http-equiv="refresh" content="0;url=https://example.test"><a href="https://example.test">leave</a><h1>Preview</h1>',
    );

    expect(preview).toContain("default-src 'none'");
    expect(preview).toContain("<h1>Preview</h1>");
    expect(preview).not.toContain("<script");
    expect(preview).not.toContain("https://example.test");
    expect(preview).not.toContain('href="');
  });

  it("sends PDF uploads as multipart data", async () => {
    render(<App />);
    fireEvent.click(screen.getAllByRole("button", { name: "知识库" })[0]);
    fireEvent.change(screen.getByLabelText(/选择一个本地文件/), {
      target: {
        files: [new File(["%PDF-1.4"], "reference.pdf", { type: "application/pdf" })],
      },
    });

    await waitFor(() => {
      const uploadCall = vi
        .mocked(fetch)
        .mock.calls.find(([input]) => String(input) === "/api/knowledge/upload");
      expect(uploadCall).toBeDefined();
      expect(uploadCall?.[1]?.body).toBeInstanceOf(FormData);
      expect(uploadCall?.[1]?.headers).toEqual({});
    });
  });
});
