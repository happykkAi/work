import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import DocumentPreviewCore from "./DocumentPreviewCore";

vi.mock("react-pdf", () => ({
  Document: () => <div data-testid="pdf-document" />,
  Page: () => <div data-testid="pdf-page" />,
  pdfjs: { GlobalWorkerOptions: { workerSrc: "" } },
}));

describe("DocumentPreviewCore Excel safety", () => {
  it("does not parse workbooks and keeps the original download available", () => {
    const fetchBlob = vi.fn(() => new Promise<Blob>(() => {}));
    const onDownload = vi.fn();
    render(
      <DocumentPreviewCore
        kind="excel"
        filename="records.xlsx"
        fetchBlob={fetchBlob}
        onDownload={onDownload}
      />,
    );

    expect(fetchBlob).not.toHaveBeenCalled();
    expect(screen.getByRole("note").textContent).toMatch(
      /Excel|Spreadsheet|表格/i,
    );
    fireEvent.click(screen.getByRole("button"));
    expect(onDownload).toHaveBeenCalledOnce();
  });
});
