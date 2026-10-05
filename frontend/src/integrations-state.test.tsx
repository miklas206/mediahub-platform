import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import {
  IntegrationProvider,
  useIntegrations,
  type Integration,
} from "./integrations";

const row: Integration = {
  id: "fjordhub",
  name: "FjordHub",
  baseUrl: "http://192.168.1.40:8888",
  allowHttp: true,
  tokenConfigured: true,
  enabled: true,
  snapshot: { status: "online" },
  lastSuccessfulSync: null,
  nextSync: 0,
};

describe("shared integration state", () => {
  it("gives all route consumers the shell snapshot and the same refresh function", async () => {
    const state = {
      items: [row],
      error: "",
      loading: false,
      reload: vi.fn().mockResolvedValue(undefined),
    };
    const snapshots: ReturnType<typeof useIntegrations>[] = [];
    function Consumer() {
      const value = useIntegrations();
      snapshots.push(value);
      return <span>{value.items[0]?.name}</span>;
    }
    const html = renderToStaticMarkup(
      <IntegrationProvider value={state}>
        <Consumer />
        <Consumer />
      </IntegrationProvider>,
    );
    expect(html).toBe("<span>FjordHub</span><span>FjordHub</span>");
    expect(snapshots).toEqual([state, state]);
    expect(snapshots[0]).toBe(state);
    expect(snapshots[1].reload).toBe(state.reload);
    await snapshots[1].reload();
    expect(state.reload).toHaveBeenCalledTimes(1);
  });

  it("shares loading and error states without replacing existing items", () => {
    function Consumer() {
      const { items, loading, error } = useIntegrations();
      return (
        <span>
          {items[0]?.name}:{String(loading)}:{error}
        </span>
      );
    }
    const html = renderToStaticMarkup(
      <IntegrationProvider
        value={{
          items: [row],
          error: "Offline",
          loading: false,
          reload: async () => {},
        }}
      >
        <Consumer />
      </IntegrationProvider>,
    );
    expect(html).toContain("FjordHub:false:Offline");
  });
});
