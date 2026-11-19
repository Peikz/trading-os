// The editor and the autosave, in jsdom: what a line renders as, what Enter, Tab and Backspace do,
// the slash menu, a checkbox, and one write after a pause. Made-up text and tickers.
import { act, fireEvent, render, renderHook, screen, waitFor, within } from "@testing-library/react";
import { mockApi } from "../test/mockApi";
import { SAVE_DELAY_MS, useAutosave } from "./autosave";
import { Editor } from "./Editor";
import { NbEnvContext } from "./env";

const T = ["W", "Z", "Q", "W"].join("");
const env = { tags: ["ep", "late"], tickers: [T], symbols: [], pages: [{ slug: "plan", title: "Plan" }] };

function setup(value: string) {
  const changes: string[] = [];
  render(
    <NbEnvContext.Provider value={env}>
      <Editor value={value} onChange={(t) => changes.push(t)} imageRef="x" label="Note" />
    </NbEnvContext.Provider>,
  );
  const editor = screen.getByLabelText("Note");
  return { changes, editor };
}

const area = () => screen.getByRole("textbox", { name: /Note, line/ }) as HTMLTextAreaElement;
const typeIn = (text: string) => {
  const el = area();
  fireEvent.change(el, { target: { value: text, selectionStart: text.length } });
  el.setSelectionRange(text.length, text.length);
};

describe("the editor draws markdown and keeps it plain", () => {
  it("renders headings, lists, checklists, quotes, tags and stocks off the active line", () => {
    const { editor } = setup(`# Title\n- one\n1. first\n- [ ] todo\n- [x] done\n> said\nSee #ep and $${T} and **bold**\n---`);
    expect(editor.querySelector(".ed-h1")).toHaveTextContent("Title");
    expect(editor.querySelectorAll(".ed-li")).toHaveLength(4);
    expect(editor.querySelectorAll('input[type="checkbox"]')).toHaveLength(2);
    expect(editor.querySelector(".ed-quote")).toHaveTextContent("said");
    expect(editor.querySelector("a.nb-tag")).toHaveAttribute("href", "#/journal/notes?p=tag%3Aep");
    expect(editor.querySelector("a.nb-ticker")).toHaveAttribute("href", `#/journal/notes?p=stock%3A${T}`);
    expect(editor.querySelector("strong")).toHaveTextContent("bold");
    expect(editor.querySelector("hr")).toBeInTheDocument();
    expect(editor.querySelector("textarea")).toBeNull(); // nothing is being edited
  });

  it("shows the plain markdown of the line you click, and nothing else", () => {
    const { editor } = setup("# Title\nSome **bold** text");
    fireEvent.click(editor.querySelectorAll(".ed-line")[1]);
    expect(area()).toHaveValue("Some **bold** text");
    expect(editor.querySelector(".ed-h1")).toHaveTextContent("Title");
  });

  it("toggles a checkbox in the stored text", () => {
    const { changes, editor } = setup("- [ ] todo\nplain");
    fireEvent.click(within(editor).getByRole("checkbox", { name: "Done: todo" }));
    expect(changes.at(-1)).toBe("- [x] todo\nplain");
  });
});

describe("the keys", () => {
  it("Enter continues a list, an empty item ends it, `[ ] ` becomes a checklist item", () => {
    const { changes, editor } = setup("- one");
    fireEvent.click(editor.querySelector(".ed-line")!);
    const el = area();
    el.setSelectionRange(5, 5);
    fireEvent.keyDown(el, { key: "Enter" });
    expect(changes.at(-1)).toBe("- one\n- ");
    typeIn("- ");
    fireEvent.keyDown(area(), { key: "Enter" }); // an empty item ends the list
    expect(changes.at(-1)).toBe("- one\n");
    typeIn("[ ] buy");
    expect(changes.at(-1)).toBe("- one\n- [ ] buy");
  });

  it("Tab indents a list item and Backspace at the start joins the line to the one above", () => {
    const { changes, editor } = setup("- one\n- two");
    fireEvent.click(editor.querySelectorAll(".ed-line")[1]);
    fireEvent.keyDown(area(), { key: "Tab" });
    expect(changes.at(-1)).toBe("- one\n  - two");
    const el = area();
    el.setSelectionRange(0, 0);
    fireEvent.keyDown(el, { key: "Backspace" });
    expect(changes.at(-1)).toBe("- one  - two");
  });

  it("the slash menu opens on `/`, filters, and Enter turns the line into a heading", () => {
    const { changes, editor } = setup("");
    fireEvent.click(editor.querySelector(".ed-line")!);
    typeIn("/head");
    const menu = screen.getByRole("listbox", { name: "Suggestions" });
    expect(within(menu).getAllByRole("option")).toHaveLength(3);
    fireEvent.keyDown(area(), { key: "Enter" });
    expect(changes.at(-1)).toBe("# ");
    expect(screen.queryByRole("listbox")).toBeNull();
  });

  it("# suggests the tags in use and `$` the stocks, and Enter writes the pick", () => {
    const { changes, editor } = setup("");
    fireEvent.click(editor.querySelector(".ed-line")!);
    typeIn("see #e");
    expect(within(screen.getByRole("listbox")).getByRole("option", { name: /#ep/ })).toBeInTheDocument();
    fireEvent.keyDown(area(), { key: "Enter" });
    expect(changes.at(-1)).toBe("see #ep ");
    typeIn(`see #ep $${T.slice(0, 2)}`);
    fireEvent.keyDown(area(), { key: "Enter" });
    expect(changes.at(-1)).toBe(`see #ep $${T} `);
  });
});

describe("pasting an image", () => {
  it("saves it as an attachment and puts it in the text as a markdown image", async () => {
    const calls = mockApi({
      "POST /api/notebook/images": { path: "data/journal/attachments/x/a_shot.png", url: "/api/attachments/data/journal/attachments/x/a_shot.png" },
    });
    const { changes, editor } = setup("");
    fireEvent.click(editor.querySelector(".ed-line")!);
    const file = new File([new Uint8Array([1, 2, 3])], "shot.png", { type: "image/png" });
    fireEvent.paste(area(), { clipboardData: { files: [file], getData: () => "" } });
    await waitFor(() => expect(changes.at(-1)).toBe("![shot](/api/attachments/data/journal/attachments/x/a_shot.png)\n"));
    expect(calls.find((c) => c.method === "POST")!.body).toMatchObject({ ref: "x", name: "shot.png" });
  });
});

describe("autosave", () => {
  beforeEach(() => vi.useFakeTimers());
  afterEach(() => vi.useRealTimers());

  it("writes once after the pause, with the newest value, and says Saved", async () => {
    const saved: string[] = [];
    const { result } = renderHook(() => useAutosave(async (v: string) => void saved.push(v)));
    act(() => {
      result.current.push("a");
      result.current.push("ab");
    });
    expect(result.current.status).toBe("dirty");
    expect(saved).toEqual([]);
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    });
    expect(saved).toEqual(["ab"]);
    expect(result.current.status).toBe("saved");
  });

  it("writes at once when the page is left, and reports a failed write", async () => {
    const saved: string[] = [];
    const first = renderHook(() => useAutosave(async (v: string) => void saved.push(v)));
    act(() => first.result.current.push("left"));
    first.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(saved).toEqual(["left"]);
    const failing = renderHook(() =>
      useAutosave(async () => {
        throw new Error("disk full");
      }),
    );
    act(() => failing.result.current.push("x"));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(SAVE_DELAY_MS + 10);
    });
    expect(failing.result.current.status).toBe("error");
    expect(failing.result.current.error).toBe("disk full");
  });
});
