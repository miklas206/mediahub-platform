import {renderToStaticMarkup} from "react-dom/server";
import {MemoryRouter} from "react-router-dom";
import {expect,it,vi} from "vitest";
import {PlexInstallPage} from "./plex-install";
const state=vi.hoisted(()=>({completed:false}));
vi.mock("./use-data",()=>({useData:()=>({data:{claimed:false,operation:{state:"idle",message:"Plex account setup is required"}},reload:()=>{}})}));
vi.mock("./phase2",()=>({
 useLoad:(path:string)=>({data:path.endsWith("install-status")?{operation:{action:"install",state:state.completed?"succeeded":"idle",message:"Installation complete",progress:100,phase:"start"}}:{hostId:"local",storage:[{id:"media",kind:"movies",label:"Media"},{id:"data",kind:"appdata",label:"App data"}]},reload:()=>{}}),
 Panel:({children}:{children:React.ReactNode})=><section>{children}</section>,ErrorBox:()=>null
}));
function render(){return renderToStaticMarkup(<MemoryRouter><PlexInstallPage/></MemoryRouter>);}
it("gets the short-lived token only after download and installation have finished",()=>{
 state.completed=false;
 expect(render()).toContain("Link your Plex account in the next step");
 expect(render()).not.toContain("https://www.plex.tv/claim/");
 state.completed=true;
 const html=render();
 expect(html).toContain("https://www.plex.tv/claim/");
 expect(html).toContain("Link Plex account");
 expect(html).toContain('type="password"');
 expect(html).not.toContain("127.0.0.1:18888");
});
