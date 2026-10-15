import { renderToStaticMarkup } from "react-dom/server";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import type { AppInfo, Metrics } from "./contracts";
import { ReferenceOverview } from "./reference-overview";
const state = vi.hoisted(() => ({ ready: false, checkedAt: 0 }));
vi.mock("./use-data", () => ({useData: () => ({data:[],error:"",reload:()=>{}})}));
vi.mock("./app-overview", async original => ({...await original<Record<string,unknown>>(), useAppOverview: () => ({ mediaseed:{status:"ok",data:{ready:state.ready,checkedAt:state.checkedAt,torrents:[{hash:"test",name:"Observed download",progress:.5,state:"downloading",dlspeed:1024}]}} })}));
const metrics = { host:{sampledAt:Date.now()/1000,scope:"docker-host",cpu:{percent:12,cores:8},ram:{percent:20,usedBytes:200,totalBytes:16000}}, coreUptimeSeconds: 3600, cpu:{percent:8,cores:4},ram:{percent:20,usedBytes:200,totalBytes:1000},disk:{percent:30,usedBytes:300,totalBytes:1000},network:{} } as Metrics;
const apps = [{id:"seed",name:"MediaSeed",packageId:"org.mediahub.mediaseed",isMock:false,health:{status:"healthy"}}] as AppInfo[];
function render(live=true) {return renderToStaticMarkup(<MemoryRouter><ReferenceOverview metrics={metrics} apps={apps} reports={{}} dashboard={{}} live={live} failed={false}/></MemoryRouter>);}
describe("compact Overview observations", () => {
  it("shows the system disk separately from media or Core data storage", () => {
    const original = metrics.host;
    metrics.host = {...original!, systemDisk: {usedBytes:23*1024**3,totalBytes:32*1024**3,freeBytes:9*1024**3,percent:71.875,scope:"host-system-filesystem"}};
    const html=render();expect(html).toContain("System disk");expect(html).toContain("23.0 GiB / 32.0 GiB");expect(html).toContain("9.0 GiB free");
    metrics.host = original;
  });
  it("shows host usage instead of the Core limit and never falls back to Core", () => {
    const original = metrics.host;
    expect(render()).toContain("12.0%");
    expect(render()).not.toContain("8.0%");
    metrics.host = null;
    const unavailable = render();
    expect(unavailable).toContain("Total server measurements are unavailable");
    expect(unavailable).not.toContain("8.0%");
    metrics.host = original;
  });
  it("does not equate reachable MediaSeed with verified VPN readiness", () => {
    state.ready=false; state.checkedAt=Date.now()/1000;
    const html=render(); expect(html).toContain("Check service status");expect(html).not.toContain("All systems operational");expect(html).toContain("Observed download");
  });
  it("does not display stale app download data or disconnected CPU measurements", () => {
    state.ready=true;state.checkedAt=Date.now()/1000-60;
    expect(render()).not.toContain("Observed download");
    const disconnected=render(false);expect(disconnected).not.toContain("12.0%");expect(disconnected).not.toContain("All systems operational");expect(disconnected).toContain("Status unavailable");
  });
  it("shows healthy aggregate only for fresh verified observations", () => {
    state.ready=true;state.checkedAt=Date.now()/1000;
    const html=render();expect(html).toContain("All systems operational");expect(html).toContain("12.0%");
  });
});
